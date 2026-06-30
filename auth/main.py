import os
import datetime
# testing
import bcrypt
import jwt
import psycopg2
from flask import Flask, request, jsonify, redirect, render_template_string

app = Flask(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
API_URL    = os.environ.get("API_URL", "http://localhost:5001")
DB_HOST    = os.environ["DB_HOST"]
DB_NAME    = os.environ.get("DB_NAME", "snapdf")
DB_USER    = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]


def get_db():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, sslmode="require"
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         SERIAL PRIMARY KEY,
            username   TEXT UNIQUE NOT NULL,
            password   TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>snaPDF &mdash; Sign In</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: sans-serif; max-width: 400px; margin: 100px auto; padding: 0 24px; color: #222; }
    h1 { font-size: 1.6rem; margin-bottom: 4px; }
    .sub { color: #666; margin-bottom: 32px; font-size: 0.95rem; }
    label { display: block; font-weight: 600; margin-bottom: 6px; }
    input { display: block; width: 100%; padding: 9px 12px; border: 1px solid #ccc; margin-bottom: 20px; font-size: 0.95rem; }
    button { width: 100%; padding: 11px; background: #1a56db; color: #fff; border: none; font-size: 1rem; cursor: pointer; }
    .error { color: #c0392b; margin-bottom: 16px; font-size: 0.9rem; }
    .links { text-align: center; margin-top: 20px; font-size: 0.9rem; color: #666; }
    .links a { color: #1a56db; margin: 0 8px; }
  </style>
</head>
<body>
  <h1>snaPDF</h1>
  <p class="sub">Sign in for priority queue access.</p>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="POST" action="/auth/login">
    <label>Username</label>
    <input type="text" name="username" required autofocus>
    <label>Password</label>
    <input type="password" name="password" required>
    <button type="submit">Sign In</button>
  </form>
  <p class="links">
    <a href="/auth/signup">Create an account &rarr;</a>
    &nbsp;&middot;&nbsp;
    <a href="{{ api_url }}">Use free tier</a>
  </p>
</body>
</html>
"""

SIGNUP_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>snaPDF &mdash; Create Account</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: sans-serif; max-width: 400px; margin: 100px auto; padding: 0 24px; color: #222; }
    h1 { font-size: 1.6rem; margin-bottom: 4px; }
    .sub { color: #666; margin-bottom: 32px; font-size: 0.95rem; }
    label { display: block; font-weight: 600; margin-bottom: 6px; }
    input { display: block; width: 100%; padding: 9px 12px; border: 1px solid #ccc; margin-bottom: 20px; font-size: 0.95rem; }
    button { width: 100%; padding: 11px; background: #059669; color: #fff; border: none; font-size: 1rem; cursor: pointer; }
    .error { color: #c0392b; margin-bottom: 16px; font-size: 0.9rem; }
    .links { text-align: center; margin-top: 20px; font-size: 0.9rem; color: #666; }
    .links a { color: #1a56db; }
  </style>
</head>
<body>
  <h1>Create Account</h1>
  <p class="sub">Signed users get priority queue access.</p>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <form method="POST" action="/auth/signup">
    <label>Username</label>
    <input type="text" name="username" required autofocus>
    <label>Password</label>
    <input type="password" name="password" required minlength="6">
    <label>Confirm Password</label>
    <input type="password" name="confirm" required minlength="6">
    <button type="submit">Create Account</button>
  </form>
  <p class="links">Already have an account" <a href="/auth">Sign in</a></p>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(LOGIN_PAGE, error=None, api_url=API_URL)


@app.route("/signup", methods=["GET"])
def signup_page():
    return render_template_string(SIGNUP_PAGE, error=None)


@app.route("/signup", methods=["POST"])
def signup():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm  = request.form.get("confirm", "")

    if not username or not password:
        return render_template_string(SIGNUP_PAGE, error="Username and password are required."), 400

    if password != confirm:
        return render_template_string(SIGNUP_PAGE, error="Passwords do not match."), 400

    if len(password) < 6:
        return render_template_string(SIGNUP_PAGE, error="Password must be at least 6 characters."), 400

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed))
        conn.commit()
        cur.close()
        conn.close()
    except psycopg2.errors.UniqueViolation:
        return render_template_string(SIGNUP_PAGE, error="Username already taken."), 409

    # Auto-login after signup
    return _issue_jwt_redirect(username)


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or not bcrypt.checkpw(password.encode(), row[0].encode()):
        return render_template_string(LOGIN_PAGE, error="Invalid username or password.", api_url=API_URL), 401

    return _issue_jwt_redirect(username)


def _issue_jwt_redirect(username):
    token = jwt.encode(
        {
            "sub": username,
            "tier": "signed",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=8),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return redirect(f"{API_URL}?token={token}")


@app.route("/verify", methods=["POST"])
def verify():
    data  = request.get_json(silent=True) or {}
    token = data.get("token", "")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return jsonify({"valid": True, "username": payload["sub"], "tier": payload.get("tier", "free")})
    except jwt.ExpiredSignatureError:
        return jsonify({"valid": False, "error": "token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"valid": False, "error": "invalid token"}), 401


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


with app.app_context():
    try:
        init_db()
    except Exception:
        pass  # DB may not be available at startup in dev -- worker retries on first request


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

