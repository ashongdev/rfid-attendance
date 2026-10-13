import auth_service as auth
import scan_service as svc
from api_helpers import get, read_json, require_admin, run, server_error, service_error
from dreema.requests import Request
from dreema.responses import response


class AuthController:
    async def login(request: Request):
        """POST /api/auth/login   {"email": "...", "password": "..."}
        Returns {"token": "...", "expires_in": 28800, "admin": {...}}.
        Send the token on later requests as:  Authorization: Bearer <token>"""
        data = await read_json(request)
        try:
            result = await run(
                auth.authenticate, get(data, "email"), get(data, "password")
            )
        except svc.ServiceError as e:
            return service_error(e)
        except Exception:
            return server_error()
        return response(result, custom=True, statuscode=200)

    async def me(request: Request):
        """GET /api/auth/me   (the dashboard uses this to check a saved login is still valid)"""
        admin, denied = await require_admin(request)
        if denied:
            return denied
        return response({"admin": admin}, custom=True, statuscode=200)
