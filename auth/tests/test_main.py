import os
os.environ["JWT_SECRET"]  = "test-secret"
os.environ["DB_HOST"]     = "localhost"
os.environ["DB_USER"]     = "test"
os.environ["DB_PASSWORD"] = "test"

import datetime
import bcrypt
import jwt
import psycopg2
import pytest
from unittest.mock import patch, MagicMock

with patch("psycopg2.connect"):
    from main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _mock_db(fetchone_return=None, execute_side_effect=None):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone_return
    if execute_side_effect is not None:
        mock_cursor.execute.side_effect = execute_side_effect
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn


def _token_from_redirect(res):
    location = res.headers["Location"]
    return location.split("token=", 1)[1]


def test_index_returns_200(client):
    res = client.get("/")
    assert res.status_code == 200


def test_signup_page_returns_200(client):
    res = client.get("/signup")
    assert res.status_code == 200


def test_health(client):
    res = client.get("/health")
    assert res.json == {"status": "ok"}


def test_signup_missing_fields_returns_400(client):
    res = client.post("/signup", data={"username": "", "password": "", "confirm": ""})
    assert res.status_code == 400


def test_signup_password_mismatch_returns_400(client):
    res = client.post("/signup", data={
        "username": "alice", "password": "secret1", "confirm": "secret2",
    })
    assert res.status_code == 400


def test_signup_short_password_returns_400(client):
    res = client.post("/signup", data={
        "username": "alice", "password": "abc", "confirm": "abc",
    })
    assert res.status_code == 400


def test_signup_duplicate_username_returns_409(client):
    mock_conn = _mock_db(execute_side_effect=psycopg2.errors.UniqueViolation("duplicate key"))
    with patch("main.get_db", return_value=mock_conn):
        res = client.post("/signup", data={
            "username": "alice", "password": "secret1", "confirm": "secret1",
        })
        assert res.status_code == 409


def test_signup_success_redirects_with_signed_jwt(client):
    mock_conn = _mock_db()
    with patch("main.get_db", return_value=mock_conn):
        res = client.post("/signup", data={
            "username": "alice", "password": "secret1", "confirm": "secret1",
        })
        assert res.status_code == 302
        token = _token_from_redirect(res)
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert payload["sub"] == "alice"
        assert payload["tier"] == "signed"


def test_login_unknown_username_returns_401(client):
    mock_conn = _mock_db(fetchone_return=None)
    with patch("main.get_db", return_value=mock_conn):
        res = client.post("/login", data={"username": "ghost", "password": "whatever"})
        assert res.status_code == 401
        assert "Invalid username or password" in res.get_data(as_text=True)


def test_login_wrong_password_returns_401_with_same_message_as_unknown_user(client):
    hashed = bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode()
    mock_conn = _mock_db(fetchone_return=(hashed,))
    with patch("main.get_db", return_value=mock_conn):
        res_unknown = client.post("/login", data={"username": "ghost", "password": "whatever"})
        res_wrong = client.post("/login", data={"username": "alice", "password": "wrong-password"})
        assert res_wrong.status_code == 401
        assert res_unknown.get_data(as_text=True) == res_wrong.get_data(as_text=True)


def test_login_success_redirects_with_signed_jwt(client):
    hashed = bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode()
    mock_conn = _mock_db(fetchone_return=(hashed,))
    with patch("main.get_db", return_value=mock_conn):
        res = client.post("/login", data={"username": "alice", "password": "correct-password"})
        assert res.status_code == 302
        token = _token_from_redirect(res)
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert payload["sub"] == "alice"
        assert payload["tier"] == "signed"


def test_verify_valid_token(client):
    token = jwt.encode({"sub": "alice", "tier": "signed"}, "test-secret", algorithm="HS256")
    res = client.post("/verify", json={"token": token})
    assert res.status_code == 200
    assert res.json == {"valid": True, "username": "alice", "tier": "signed"}


def test_verify_expired_token_returns_401(client):
    token = jwt.encode(
        {"sub": "alice", "tier": "signed", "exp": datetime.datetime.utcnow() - datetime.timedelta(hours=1)},
        "test-secret", algorithm="HS256",
    )
    res = client.post("/verify", json={"token": token})
    assert res.status_code == 401
    assert res.json["error"] == "token expired"


def test_verify_invalid_signature_returns_401(client):
    forged = jwt.encode({"sub": "attacker", "tier": "signed"}, "wrong-secret", algorithm="HS256")
    res = client.post("/verify", json={"token": forged})
    assert res.status_code == 401
    assert res.json["error"] == "invalid token"


def test_verify_missing_token_returns_401(client):
    res = client.post("/verify", json={})
    assert res.status_code == 401
    assert res.json["error"] == "invalid token"
