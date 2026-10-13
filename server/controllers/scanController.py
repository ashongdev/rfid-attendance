import scan_service as svc
from api_helpers import check_bearer, get, read_json, run, server_error, service_error
from dreema.requests import Request
from dreema.responses import SysCodes, response


class ScanController:
    async def scan(request: Request):
        """POST /api/attendance  (called by the ESP32 readers)

        Body: {"uid": "01020304", "device_id": "reader-01",
               "scan_id": "reader-01-...", "scanned_at": 1791848101}
        Auth: Authorization: Bearer <DEVICE_API_KEY from .env>

        Always answers 200 with {"data": {"status": ...}} for a scan the server understood,
        so the reader treats it as delivered. Problems with the request itself are 4xx
        (the reader drops those), and server faults are 5xx (the reader retries later).
        """
        denied = check_bearer(request, svc.setting("DEVICE_API_KEY", "CHANGE_ME"))
        if denied:
            return denied

        data = await read_json(request)

        try:
            result = await run(
                svc.process_scan,
                get(data, "uid"),
                get(data, "device_id"),
                scan_id=get(data, "scan_id"),
                scanned_at=get(data, "scanned_at", 0),
            )
        except svc.ServiceError as e:
            return service_error(e)
        except Exception:
            return server_error()

        return response(
            data=result,
            message="Operation completed",
            status=SysCodes.READ_SUCCESS,
            statuscode=200,
        )
