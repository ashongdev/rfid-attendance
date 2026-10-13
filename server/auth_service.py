"""
Admin accounts, passwords and login tokens. Standard library only (no extra packages).

  create_admin(conn, ...)            make an admin account
  authenticate(conn, email, pw)      check a login and hand back a token
  get_admin_from_token(conn, token)  turn a token back into an admin (and check they're still active)

Passwords are stored as salted PBKDF2-SHA256 hashes, never as text.
Tokens are signed with SECRET_KEY from .env, so they can't be forged or edited.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque

import pymysql
import scan_service as svc
from pymysql.cursors import DictCursor
from scan_service import ServiceError, _audit

TOKEN_TTL_SECONDS = 8 * 60 * 60  # a login lasts 8 hours
PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10
MAX_FAILURES = 5  # failed logins allowed per email...
FAILURE_WINDOW_SECONDS = 15 * 60  # ...within this many seconds
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_failures = defaultdict(
    deque
)  # email -> times of recent failed logins (kept in memory)
_failures_lock = threading.Lock()
_dummy = None


# ---------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------
def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ---------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------
def hash_password(password, iterations=PBKDF2_ITERATIONS):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password, stored):
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        expected = _unb64(digest)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _unb64(salt), int(iterations)
        )
    except (ValueError, TypeError, AttributeError):
        return False
    return hmac.compare_digest(actual, expected)


def _dummy_hash():
    """A throwaway hash, so a login for an unknown email takes as long as a real one."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password("not-a-real-password")
    return _dummy


# ---------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------
def _secret():
    key = svc.setting("SECRET_KEY")
    if not key or len(key) < 32:
        raise ServiceError(
            "server_not_configured",
            "SECRET_KEY is missing from .env (it must be at least 32 characters).",
        )
    return key.encode("utf-8")


def make_token(admin_id, role):
    payload = {
        "sub": admin_id,
        "role": role,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read_token(token):
    try:
        body, signature = token.split(".")
        expected = _b64(
            hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(_unb64(body))
    except ServiceError:
        raise
    except Exception:
        raise ServiceError("unauthorized", "Please log in again.")
    if payload.get("exp", 0) < time.time():
        raise ServiceError(
            "token_expired", "Your session has expired. Please log in again."
        )
    return payload


# ---------------------------------------------------------------
# Failed-login limit
# ---------------------------------------------------------------
def _check_not_locked(key):
    now = time.time()
    with _failures_lock:
        attempts = _failures[key]
        while attempts and now - attempts[0] > FAILURE_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= MAX_FAILURES:
            raise ServiceError(
                "too_many_attempts",
                "Too many failed attempts. Try again in a few minutes.",
            )


def _record_failure(key):
    with _failures_lock:
        _failures[key].append(time.time())


def _clear_failures(key):
    with _failures_lock:
        _failures.pop(key, None)


# ---------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------
def _public(row):
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def create_admin(conn, email, password, full_name=None, role="admin"):
    email = (email or "").strip().lower()
    password = password or ""
    if not EMAIL_PATTERN.match(email) or len(email) > 190:
        raise ServiceError("bad_input", "Enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ServiceError(
            "bad_input",
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if role not in ("admin", "viewer"):
        raise ServiceError("bad_input", "Role must be 'admin' or 'viewer'.")
    full_name = (full_name or "").strip() or None

    try:
        with conn.cursor(DictCursor) as cur:
            try:
                cur.execute(
                    "INSERT INTO admins (email, password_hash, full_name, role) VALUES (%s, %s, %s, %s)",
                    (email, hash_password(password), full_name, role),
                )
            except pymysql.err.IntegrityError:
                raise ServiceError(
                    "duplicate_email", "An admin with that email already exists."
                )
            admin_id = cur.lastrowid
            _audit(
                cur,
                None,
                "admin.create",
                "admin",
                admin_id,
                {"email": email, "role": role},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"id": admin_id, "email": email, "full_name": full_name, "role": role}


def authenticate(conn, email, password):
    """Check a login. Returns {"token", "expires_in", "admin"} or raises ServiceError."""
    email = (email or "").strip().lower()
    password = password or ""
    if not email or not password:
        raise ServiceError("bad_input", "Enter your email and password.")

    _check_not_locked(email)

    with conn.cursor(DictCursor) as cur:
        cur.execute(
            "SELECT id, email, password_hash, full_name, role, active FROM admins WHERE email = %s",
            (email,),
        )
        row = cur.fetchone()
    conn.commit()

    stored = row["password_hash"] if row else _dummy_hash()
    password_ok = verify_password(password, stored)

    if not (row and password_ok and row["active"]):
        _record_failure(email)
        with conn.cursor() as cur:
            _audit(
                cur,
                None,
                "auth.login_failed",
                "admin",
                row["id"] if row else "unknown",
                {"email": email},
            )
        conn.commit()
        raise ServiceError("invalid_credentials", "Wrong email or password.")

    _clear_failures(email)
    with conn.cursor() as cur:
        _audit(cur, row["id"], "auth.login", "admin", row["id"])
    conn.commit()

    return {
        "token": make_token(row["id"], row["role"]),
        "expires_in": TOKEN_TTL_SECONDS,
        "admin": _public(row),
    }


def get_admin_from_token(conn, token):
    """The admin a token belongs to. Re-checks the database every time,
    so deactivating an admin or changing their role takes effect immediately."""
    payload = read_token(token)
    with conn.cursor(DictCursor) as cur:
        cur.execute(
            "SELECT id, email, full_name, role, active FROM admins WHERE id = %s",
            (payload.get("sub"),),
        )
        row = cur.fetchone()
    conn.commit()
    if not row or not row["active"]:
        raise ServiceError("unauthorized", "That account is no longer active.")
    return _public(row)
