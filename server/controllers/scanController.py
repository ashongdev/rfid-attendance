from datetime import datetime, timezone

from dreema.requests import Request
from dreema.responses import response

API_KEY = "CHANGE_ME"  # must match API_KEY in main.cpp
USERS = {
    "01020304": "Ama Mensah",
    "11223344": "Kofi Boateng",
}
SEEN_SCANS = {}  # scan_id -> name, remembers scans already saved


class ScanController:
    @staticmethod
    async def scan(request: Request):
        # Check the key the ESP32 sends
        if request.headers().get("authorization") != f"Bearer {API_KEY}":
            return response(message="unauthorized"), 401

        data = await request.body()
        if not data or "uid" not in data:
            return response(message="bad request"), 400

        uid = data.get("uid")
        device_id = data.get("device_id", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        scan_id = data.get("scan_id")
        scanned_at = data.get("scanned_at", 0)

        # Already saved this exact scan? (the ESP32 retried) -> don't save it twice
        if scan_id and scan_id in SEEN_SCANS:
            return response(
                data={"status": "duplicate", "uid": uid, "name": SEEN_SCANS[scan_id]}
            )

        name = USERS.get(uid)
        if name is None:
            print(f"{now}  {device_id}  {uid}  UNKNOWN CARD")
            return response(data={"status": "unknown", "uid": uid})

        # Use the time the card was tapped, if the device knew it
        if scanned_at:
            scan_time = datetime.fromtimestamp(scanned_at, timezone.utc).isoformat()
        else:
            scan_time = now

        # Save one line per scan: time,device,uid,name,scan_id
        with open("attendance.csv", "a") as f:
            f.write(f"{scan_time},{device_id},{uid},{name},{scan_id}\n")

        if scan_id:
            SEEN_SCANS[scan_id] = name

        print(f"{scan_time}  {device_id}  {uid}  {name}")
        return response(
            data={"status": "ok", "uid": uid, "name": name, "time": scan_time}
        )
