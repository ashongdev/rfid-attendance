"""
Small helpers shared by the Dreema controllers.
Put this file in the project root, next to scan_service.py.
"""

import asyncio
import hmac
import traceback

import scan_service as svc
from dreema.responses import response

# Which HTTP status each expected problem should produce.
# Anything not listed is treated as 400 (bad request).
STATUS_FOR_ERROR = {
    "bad_uid": 400,
    "bad_device": 400,
    "bad_input": 400,
    "person_not_found": 404,
    "session_not_found": 404,
    "device_not_found": 404,
    "person_inactive": 409,
    "person_has_card": 409,
    "session_busy": 409,
    "duplicate_external_id": 409,
    "duplicate_email": 409,
    "invalid_credentials": 401,
    "unauthorized": 401,
    "token_expired": 401,
    "forbidden": 403,
    "too_many_attempts": 429,
    "server_not_configured": 503,
}


def get(data, key, default=None):
    """Read a field from a request body or query, whether it behaves like a dict or an object."""
    if data is None:
        return default
    try:
        return data.get(key, default)
    except AttributeError:
        return getattr(data, key, default)


async def read_json(request):
    """The request's JSON body. In this Dreema setup request.body() IS the payload
    (there is no .data inside it), so read fields from it with get()."""
    body = await request.body()
    return body if body is not None else {}


def header(request, name):
    """Case-insensitive header lookup. Returns None if the header isn't there."""
    headers = request.headers()
    pairs = headers.items() if hasattr(headers, "items") else headers
    wanted = name.lower()
    try:
        for key, value in pairs:
            if isinstance(key, bytes):
                key = key.decode("latin-1")
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            if str(key).lower() == wanted:
                return value
    except (TypeError, ValueError):
        pass
    return None


def check_bearer(request, expected):
    """Return None if the request carries 'Authorization: Bearer <expected>',
    otherwise a ready-made error response to return from the handler."""
    if not expected:
        return response(
            {
                "error": "server_not_configured",
                "message": "The server is missing an API key setting.",
            },
            custom=True,
            statuscode=503,
        )
    auth = header(request, "authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(token.encode("utf-8"), str(expected).encode("utf-8")):
        return response({"error": "Unauthorized"}, custom=True, statuscode=401)
    return None


async def require_admin(request, write=False):
    """Check the login token. Returns (admin, None) for a logged-in admin,
    or (None, error_response) that the handler should return as-is.
    write=True also requires the 'admin' role (viewers are read-only)."""
    import auth_service  # imported here so this file still loads if auth isn't set up yet

    auth = header(request, "authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        return None, response(
            {"error": "unauthorized", "message": "Please log in."},
            custom=True,
            statuscode=401,
        )
    try:
        admin = await run(auth_service.get_admin_from_token, token)
    except svc.ServiceError as e:
        return None, service_error(e)
    except Exception:
        return None, server_error()

    if write and admin["role"] != "admin":
        return None, response(
            {"error": "forbidden", "message": "Your account is read-only."},
            custom=True,
            statuscode=403,
        )
    return admin, None


def _with_conn(fn, *args, **kwargs):
    conn = svc.connect()
    try:
        return fn(conn, *args, **kwargs)
    finally:
        conn.close()


async def run(fn, *args, **kwargs):
    """Run a service function (which takes a connection first) without blocking the server.
    A fresh connection is opened for each call and closed afterwards."""
    return await asyncio.to_thread(_with_conn, fn, *args, **kwargs)


def to_int(value, field):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise svc.ServiceError("bad_input", f"{field} must be a whole number.")


def service_error(e):
    return response(
        {"error": e.code, "message": e.message},
        custom=True,
        statuscode=STATUS_FOR_ERROR.get(e.code, 400),
    )


def server_error():
    traceback.print_exc()
    return response({"error": "server_error"}, custom=True, statuscode=500)
