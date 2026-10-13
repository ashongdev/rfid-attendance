import admin_service as admin
import scan_service as svc
from api_helpers import (
    get,
    read_json,
    require_admin,
    run,
    server_error,
    service_error,
    to_int,
)
from dreema.requests import Request
from dreema.responses import response

# Every handler needs a logged-in admin (Authorization: Bearer <token> from /api/auth/login).
# Reading is allowed for the 'viewer' role. Anything that changes data needs the 'admin' role.


class AdminController:
    # ---------- People ----------
    async def createPerson(request: Request):
        """POST /api/people/create   {"full_name": "...", "external_id": "...", "group_name": "...", "email": "..."}"""
        who, denied = await require_admin(request, write=True)
        if denied:
            return denied
        data = await read_json(request)
        try:
            person = await run(
                admin.create_person,
                get(data, "full_name"),
                external_id=get(data, "external_id"),
                group_name=get(data, "group_name"),
                email=get(data, "email"),
                admin_id=who["id"],
            )
        except svc.ServiceError as e:
            return service_error(e)
        except Exception:
            return server_error()
        return response({"person": person}, custom=True, statuscode=201)

    async def listPeople(request: Request):
        """GET /api/people?search=ama&limit=50&offset=0"""
        who, denied = await require_admin(request)
        if denied:
            return denied
        query = request.queryParam()
        try:
            people = await run(
                admin.list_people,
                get(query, "search"),
                limit=to_int(get(query, "limit", 100), "limit"),
                offset=to_int(get(query, "offset", 0), "offset"),
            )
        except svc.ServiceError as e:
            return service_error(e)
        except Exception:
            return server_error()
        return response({"people": people}, custom=True, statuscode=200)

    # ---------- Readers ----------
    async def listDevices(request: Request):
        """GET /api/devices   (readers appear after their first scan)"""
        who, denied = await require_admin(request)
        if denied:
            return denied
        try:
            devices = await run(admin.list_devices)
        except Exception:
            return server_error()
        return response({"devices": devices}, custom=True, statuscode=200)

    # ---------- Tap-to-assign ----------
    async def startAssignment(request: Request):
        """POST /api/assignments/start   {"person_id": 1, "device_id": "reader-01"}"""
        who, denied = await require_admin(request, write=True)
        if denied:
            return denied
        data = await read_json(request)
        try:
            session = await run(
                svc.start_assignment,
                to_int(get(data, "person_id"), "person_id"),
                str(get(data, "device_id") or "").strip(),
                admin_id=who["id"],
            )
        except svc.ServiceError as e:
            return service_error(e)
        except Exception:
            return server_error()
        return response({"session": session}, custom=True, statuscode=201)

    async def getAssignment(request: Request):
        """GET /api/assignments?id=3   (poll this while waiting for the tap)"""
        who, denied = await require_admin(request)
        if denied:
            return denied
        query = request.queryParam()
        try:
            session = await run(svc.get_session, to_int(get(query, "id"), "id"))
        except svc.ServiceError as e:
            return service_error(e)
        except Exception:
            return server_error()
        return response({"session": session}, custom=True, statuscode=200)

    async def cancelAssignment(request: Request):
        """POST /api/assignments/cancel   {"id": 3}"""
        who, denied = await require_admin(request, write=True)
        if denied:
            return denied
        data = await read_json(request)
        try:
            cancelled = await run(
                svc.cancel_session,
                to_int(get(data, "id"), "id"),
                admin_id=who["id"],
            )
        except svc.ServiceError as e:
            return service_error(e)
        except Exception:
            return server_error()
        return response({"cancelled": cancelled}, custom=True, statuscode=200)
