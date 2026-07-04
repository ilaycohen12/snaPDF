import os
import uuid
import json
import boto3
import psycopg2
import jwt
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

SIGNED_QUEUE_URL = os.environ["SIGNED_QUEUE_URL"]
FREE_QUEUE_URL   = os.environ["FREE_QUEUE_URL"]
S3_BUCKET        = os.environ["S3_BUCKET"]
JWT_SECRET       = os.environ.get("JWT_SECRET", "dev-secret-change-me")
AUTH_URL         = os.environ.get("AUTH_URL", "")
DB_HOST          = os.environ["DB_HOST"]
DB_NAME          = os.environ.get("DB_NAME", "snapdf")
DB_USER          = os.environ["DB_USER"]
DB_PASSWORD      = os.environ["DB_PASSWORD"]

sqs = boto3.client("sqs", region_name="us-east-1")
s3  = boto3.client("s3",  region_name="us-east-1")

PAGE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>snaPDF -- PDF Converter</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: sans-serif; max-width: 560px; margin: 80px auto; padding: 0 24px; color: #222; }
    h1 { font-size: 1.6rem; margin-bottom: 4px; }
    .sub { color: #666; margin-bottom: 32px; }
    .badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: 600; margin-bottom: 24px; }
    .badge.signed { background: #d1fae5; color: #065f46; }
    .badge.free   { background: #fef3c7; color: #92400e; }
    label { display: block; font-weight: 600; margin-bottom: 6px; }
    input[type=file] { display: block; width: 100%; padding: 9px 12px; border: 1px solid #ccc; margin-bottom: 20px; font-size: 0.95rem; }
    button { width: 100%; padding: 11px; background: #1a56db; color: #fff; border: none; font-size: 1rem; cursor: pointer; }
    button:disabled { background: #888; cursor: default; }
    #result { margin-top: 24px; padding: 16px; background: #f5f5f5; display: none; line-height: 1.6; }
    .login-link { text-align: center; margin-top: 20px; font-size: 0.9rem; color: #666; }
    .login-link a { color: #1a56db; }
    a { color: #1a56db; }
  </style>
</head>
<body>
  <h1>snaPDF</h1>
  <p class="sub">Upload a Word document and receive a PDF.</p>

  <div id="tier-badge"></div>

  <form id="form">
    <label>Word File (.docx)</label>
    <input type="file" id="file" accept=".docx" required>
    <button type="submit" id="btn">Convert to PDF</button>
  </form>

  <div id="result"></div>
  <p class="login-link" id="login-hint"></p>

  <script>
    // Read JWT from ?token= URL param (set by auth service after login) -- only
    // used below to attach it as a Bearer header on submit. The badge is never
    // decoded client-side: the server already verified the signature (decode_jwt()
    // in app.py) and rendered the real, trusted username/tier as verifiedUsername/
    // verifiedTier below -- a forged token can no longer make this badge lie.
    const params = new URLSearchParams(window.location.search);
    const token  = params.get('token') || '';

    const badge = document.getElementById('tier-badge');
    const hint  = document.getElementById('login-hint');

    const verifiedUsername = {{ username | tojson }};
    const verifiedTier     = {{ tier | tojson }};

    if (verifiedTier === 'signed') {
      const span = document.createElement('span');
      span.className = 'badge signed';
      span.textContent = 'Signed in as ' + verifiedUsername + ' — Priority Queue';
      badge.appendChild(span);
    } else {
      badge.innerHTML = '<span class="badge free">Free Tier</span>';
      if ('{{ auth_url }}') {
        hint.innerHTML = '<a href="{{ auth_url }}">Sign in for priority queue &rarr;</a>';
      }
    }

    document.getElementById('form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn    = document.getElementById('btn');
      const result = document.getElementById('result');

      btn.disabled = true;
      btn.textContent = 'Uploading...';
      result.style.display = 'block';
      result.textContent = 'Sending file...';

      const data = new FormData();
      data.append('file', document.getElementById('file').files[0]);

      const headers = {};
      if (token) headers['Authorization'] = 'Bearer ' + token;

      const res  = await fetch('/api/convert', { method: 'POST', headers, body: data });
      const json = await res.json();

      btn.disabled = false;
      btn.textContent = 'Convert to PDF';

      if (!res.ok) { result.textContent = 'Error: ' + json.error; return; }

      const tier = json.queue === 'signed' ? 'Signed (priority)' : 'Free';
      result.innerHTML = 'Job submitted &mdash; <strong>' + tier + '</strong> queue<br>'
        + 'ID: <code>' + json.job_id + '</code><br><br>Checking status...';
      poll(json.job_id);
    });

    async function poll(jobId) {
      const res  = await fetch('/api/jobs/' + jobId);
      const json = await res.json();
      if (json.status === 'done') {
        document.getElementById('result').innerHTML =
          'Done! <a href="' + json.download_url + '" target="_blank">Download PDF</a>';
      } else if (json.status === 'failed') {
        document.getElementById('result').innerHTML = 'Conversion failed. Please try again.';
      } else {
        setTimeout(() => poll(jobId), 3000);
      }
    }
  </script>
</body>
</html>
"""


def decode_jwt(token):
    """Returns (username, tier) if valid, or (None, None) if invalid/missing."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub", "unknown"), payload.get("tier", "free")
    except jwt.InvalidTokenError:
        return None, None


def get_db():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, sslmode="require")


@app.route("/")
def index():
    token = request.args.get("token", "")
    username, tier = decode_jwt(token) if token else (None, None)
    return render_template_string(PAGE, auth_url=AUTH_URL, username=username, tier=tier)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".docx"):
        return jsonify({"error": "only .docx files are supported"}), 400

    # Determine tier from JWT
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
    username, tier = decode_jwt(token)
    is_signed = tier == "signed"

    job_id = str(uuid.uuid4())
    s3_input_key = f"uploads/{job_id}.docx"
    s3.upload_fileobj(file, S3_BUCKET, s3_input_key)

    message = {"job_id": job_id, "s3_input_key": s3_input_key}
    if is_signed:
        message["username"] = username

    queue_url = SIGNED_QUEUE_URL if is_signed else FREE_QUEUE_URL
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))

    return jsonify({"job_id": job_id, "queue": "signed" if is_signed else "free"})


@app.route("/jobs/<job_id>")
def job_status(job_id):
    conn = get_db()
    cur  = conn.cursor()

    row = None
    for table in ("signed_jobs", "free_jobs"):
        cur.execute(f"SELECT status, s3_key FROM {table} WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
        if row:
            break

    cur.close()
    conn.close()

    if not row:
        return jsonify({"status": "pending"})

    status, s3_key = row
    if status == "done" and s3_key:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": s3_key},
            ExpiresIn=3600,
        )
        return jsonify({"status": "done", "download_url": url})

    return jsonify({"status": status})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

