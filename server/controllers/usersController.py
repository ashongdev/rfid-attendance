from datetime import datetime, timezone

from dreema.requests import Request
from dreema.responses import SysCodes, response
from models.usersModel import UsersModel

API_KEY = "CHANGE_ME"  # must match API_KEY in main.cpp


class UsersController:
    @staticmethod
    async def welcome():
        return response(message="Setup completed", status=SysCodes.SETUP_COMPLETED)

    @staticmethod
    async def attendance(request: Request):
        # Check the key the ESP32 sends
        if request.headers().get("authorization") != f"Bearer {API_KEY}":
            return response(message="unauthorized"), 401

        data = await request.body()
        if not data or "uid" not in data:
            return response(message="bad request"), 400

        uid = data.get("uid")
        device_id = data.get("device_id", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        # Save one line per scan: time,device,uid
        with open("attendance.csv", "a") as f:
            f.write(f"{now},{device_id},{uid}\n")

        print(f"{now}  {device_id}  {uid}")
        return response(data={"status": "ok", "uid": uid, "time": now})
