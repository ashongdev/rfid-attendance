from datetime import datetime, timezone

from dreema.requests import Request
from dreema.responses import SysCodes, response
from models.usersModel import UsersModel

API_KEY = "CHANGE_ME"  # must match API_KEY in main.cpp
USERS = {
    "01020304": "Ama Mensah",
    "11223344": "Kofi Boateng",
}


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

        name = USERS.get(uid)
        if name is None:
            print(f"{now}  {device_id}  {uid}  UNKNOWN CARD")
            return response(data={"status": "unknown", "uid": uid})

        # Save one line per scan: time,device,uid,name
        with open("attendance.csv", "a") as f:
            f.write(f"{now},{device_id},{uid},{name}\n")

        print(f"{now}  {device_id}  {uid}  {name}")
        return response(data={"status": "ok", "uid": uid, "name": name, "time": now})
