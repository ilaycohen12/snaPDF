import os
import uuid
import json
import boto3
import psycopg2
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

SIGNED_QUEUE_URL = os.environ["SIGNED_QUEUE_URL"]
FREE_QUEUE_URL   = os.environ["FREE_QUEUE_URL"]
S3_BUCKET        = os.environ["S3_BUCKET"]
API_KEY          = os.environ["API_KEY"]
DB_HOST          = os.environ["DB_HOST"]
DB_NAME          = os.environ.get("DB_NAME", "projectview")
DB_USER          = os.environ["DB_USER"]
DB_PASSWORD      = os.environ["DB_PASSWORD"]

sqs = boto3.client("sqs", region_name="us-east-1")
s3  = boto3.client("s3",  region_name="us-east-1")

PAGE = """
<!DOCTYPE html>
<html>
<head>
  <title>PDF Converter</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: sans-serif; max-width: 560px; margin: 80px auto; padding: 0 24px; color: #222; }
    h1 { font-size: 1.6rem; margin-bottom: 4px; }
    .sub { color: #666; margin-bottom: 32px; }
    label { display: block; font-weight: 600; margin-bottom: 6px; }
    .hint { font-weight: normal; color: #888; font-size: 0.85rem; }
    input[type=file], input[type=text] {
      display: block; width: 100%; padding: 9px 12px;
      border: 1px solid #ccc; margin-bottom: 20px; font-size: 0.95rem;
    }
    button {
      width: 100%; padding: 11px; background: #1a56db; color: #fff;
      border: none; font-size: 1rem; cursor: pointer;
    }
    button:disabled { background: #888; cursor: default; }
    #result { margin-top: 24px; padding: 16px; background: #f5f5f5; display: none; line-height: 1.6; }
    a { color: #1a56db; }
  </style>
</head>
<body>
  <h1>PDF Converter</h1>
  <p class="sub">Upload a Word document and receive a PDF.</p>

  <form id="form">
    <label>Word File (.docx)</label>
    <input type="file" id="file" accept=".docx" required>

    <label>API Key <span class="hint">(optional — signed users get priority queue)</span></label>
    <input type="text" id="apiKey" placeholder="Leave empty for free tier">

    <label>Username <span class="hint">(required if using API key)</span></label>
    <input type="text" id="username" placeholder="e.g. john">

    <button type="submit" id="btn">Convert to PDF</button>
  </form>

  <div id="result"></div>

  <script>
    const form   = document.getElementById('form');
    const result = document.getElementById('result');
    const btn    = document.getElementById('btn');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      btn.disabled = true;
      btn.textContent = 'Uploading...';
      result.style.display = 'block';
      result.textContent = 'Sending file...';

      const data = new FormData();
      data.append('file', document.getElementById('file').files[0]);

      const headers = {};
      const apiKey  = document.getElementById('apiKey').value.trim();
      const username = document.getElementById('username').value.trim();
      if (apiKey)    headers['X-API-Key']  = apiKey;
      if (username)  headers['X-Username'] = username;

      const res  = await fetch('/convert', { method: 'POST', headers, body: data });
      const json = await res.json();

      btn.disabled = false;
      btn.textContent = 'Convert to PDF';

      if (!res.ok) { result.textContent = 'Error: ' + json.error; return; }

      const tier = json.queue === 'signed' ? 'Signed (priority)' : 'Free';
      result.innerHTML = `Job submitted — <strong>${tier}</strong> queue<br>ID: <code>${json.job_id}</code><br><br>Checking status...`;
      poll(json.job_id);
    });

    async function poll(jobId) {
      const res  = await fetch('/jobs/' + jobId);
      const json = await res.json();
      if (json.status === 'done') {
        result.innerHTML = 'Done! <a href="' + json.download_url + '" target="_blank">Download PDF</a>';
      } else if (json.status === 'failed') {
        result.innerHTML = 'Conversion failed. Please try again.';
      } else {
        setTimeout(() => poll(jobId), 3000);
      }
    }
  </script>
</body>
</html>
"""

def get_db():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, sslmode="require")

@app.route("/")
def index():
    return render_template_string(PAGE)

@app.route("/health")
def health():
    return {"status": "ok"}

@app.route("/convert", methods=["POST"])
def convert():
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".docx"):
        return jsonify({"error": "only .docx files are supported"}), 400

    api_key   = request.headers.get("X-API-Key", "")
    is_signed = api_key == API_KEY
    job_id    = str(uuid.uuid4())

    s3_input_key = f"uploads/{job_id}.docx"
    s3.upload_fileobj(file, S3_BUCKET, s3_input_key)

    message = {"job_id": job_id, "s3_input_key": s3_input_key}
    if is_signed:
        message["username"] = request.headers.get("X-Username", "unknown")

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
