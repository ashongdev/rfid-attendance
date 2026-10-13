<img width="883" height="496" alt="image" src="https://github.com/user-attachments/assets/c98be955-f0ce-4c7e-b32f-189e6555ddb0" />

# RFID Attendance System

An attendance system built around an ESP32 and an MFRC522 RFID reader. When someone taps a card, the device sends the card's UID to a backend API, the backend looks up the person and logs the attendance, and the ESP32 shows the result on an I2C LCD.

The firmware keeps working when the network doesn't: scans are queued on the device and sent in the background, with automatic retries, so taps are never blocked by a slow or unreachable server.

This repository contains:

- ESP32 firmware (PlatformIO / Arduino) for scanning, queuing and LCD feedback
- A Python backend API (built with dreema) that receives scans and logs attendance to CSV
- A Wokwi simulation (`diagram.json`) for testing without hardware

## Features

- RFID card scanning with the MFRC522 module
- Name lookup on the server, shown on the LCD (`Welcome, <name>`)
- **Taps are never missed:** card reading runs in its own task, so a tap is registered instantly (and the card can be pulled away) even while another scan is being sent
- **Offline-tolerant scan queue:** up to 20 scans wait on the device and are sent oldest-first
- **Automatic retries** with growing delays (1 s up to 30 s) until the server confirms each scan
- **Fast sends:** the HTTPS connection is kept open between scans, so only the first scan pays for the TLS handshake
- **Duplicate protection:** every tap carries a unique `scan_id`, so a retry never creates a second record
- **Tap timestamps:** each scan carries the time of the tap (via NTP), not the time it finally reached the server
- Same-card cooldown (3 s) to avoid accidental double taps
- CSV attendance log
- Wokwi-compatible simulation

## Project Structure

```text
.
├── .gitignore
├── diagram.json          # Wokwi circuit
├── platformio.ini
├── wokwi.toml
├── include/
├── lib/
├── src/
│   └── main.cpp          # ESP32 firmware
├── server/
│   ├── attendance.csv    # attendance log (generated; do not commit)
│   ├── endpoints.py
│   ├── controllers/
│   ├── models/
│   ├── plug.template.py
│   ├── settings.template.py
│   └── .dreema.json
├── test/
└── README.md
```

## Hardware

- ESP32 development board
- MFRC522 RFID reader module
- 16x2 LCD with an I2C backpack
- Breadboard and jumper wires

### Wiring

The LCD is on GPIO 25/26 because the ESP32's default I2C pins (21 and 22) are used by the RFID reader.

| Module | Pin | ESP32 |
|---|---|---|
| MFRC522 | SDA (chip select) | GPIO 21 |
| | RST | GPIO 22 |
| | SCK | GPIO 18 |
| | MISO | GPIO 19 |
| | MOSI | GPIO 23 |
| | 3.3V | 3V3 |
| | GND | GND |
| LCD (I2C) | SDA | GPIO 25 |
| | SCL | GPIO 26 |
| | VCC | 5V |
| | GND | GND |

> **The MFRC522 must be powered from 3.3V, never 5V.** The LCD backpack normally needs 5V to be readable.
> On the MFRC522, "SDA" is the SPI chip-select line, not I2C data.

The same layout is modeled in `diagram.json` for Wokwi.

## Firmware

The firmware lives in `src/main.cpp` and uses these libraries (declared in `platformio.ini`):

```ini
lib_deps =
    miguelbalboa/MFRC522
    marcoschwartz/LiquidCrystal_I2C
    bblanchon/ArduinoJson@^7
```

### How it works

The firmware runs two tasks, so reading cards and talking to the server never get in each other's way:

- **Reader task:** polls the RFID reader about 30 times a second, puts each tap in the queue, and keeps the LCD up to date. It never touches the network.
- **`loop()`:** takes queued scans one at a time and sends them to the API over a kept-open HTTPS connection, handling retries and showing the result.

The two share a thread-safe queue, and the LCD is protected by a lock so both can write to it safely.

1. Starts the RFID reader and LCD, connects to WiFi, and syncs the clock over NTP.
2. When a card is tapped, the reader task immediately adds a scan (UID, unique `scan_id`, tap time) to the queue and shows `Saved`. This never waits on the network, and it works even while another scan is mid-send.
3. `loop()` sends the oldest queued scan to the API, reusing the open HTTPS connection when it can. The scan is removed from the queue **only after the server confirms it**.
4. If the network or server fails (or returns a 5xx error), the scan stays in the queue and is retried with a growing delay.
5. If the server rejects a scan with a client error (for example a wrong API key), the scan is dropped so it can't block the queue, and the LCD shows `Rejected`.

> The queue is held in memory. If the ESP32 loses power or resets, scans still waiting are lost.

> Names are looked up by the server, so while it is unreachable the LCD can only show `Saved` and `Pending: N`. The names appear as the queued scans are delivered.

### LCD messages

| Screen | Meaning |
|---|---|
| `Scan your card` | Idle |
| `Scan your card` / `Pending: N` | N scans are waiting to be delivered (offline or server slow) |
| `Saved` / `<uid>` | Scan queued |
| `Welcome,` / `<name>` | Server confirmed and recognised the card |
| `Unknown card` / `<uid>` | Server received the scan but the card isn't registered |
| `Rejected` / `Contact admin` | Server refused the scan (e.g. invalid API key) |
| `Queue full` / `Try later` | 20 scans are already waiting; this one was dropped |

### Configuration

Edit these values at the top of `src/main.cpp`:

```cpp
const char* WIFI_SSID    = "Wokwi-GUEST";   // your network on real hardware
const char* WIFI_PASS    = "";
const int   WIFI_CHANNEL = 6;               // Wokwi only; use 0 on real hardware

const char* API_URL   = "https://your-backend-url/api/attendance";
const char* API_KEY   = "CHANGE_ME";        // must match the server
const char* DEVICE_ID = "reader-01";        // unique per reader/location
```

Change `API_KEY` to a real secret before using this with anyone's data, and keep real credentials out of version control.

### Tuning

These constants are also near the top of `src/main.cpp`:

| Constant | Default | What it controls |
|---|---|---|
| `HTTP_TIMEOUT_MS` | 5000 | Longest wait for the server's reply |
| `CONNECT_TIMEOUT_MS` | 2000 | Longest wait to open a connection. This also caps how long one failed attempt can take when the server is unreachable |
| `SAME_CARD_COOLDOWN_MS` | 3000 | A card tapped again within this time is ignored |
| `MESSAGE_SHOW_MS` | 2000 | How long a result stays on the LCD before the idle screen returns |
| `QUEUE_MAX` | 20 | How many scans can wait while offline; new taps are refused when full |

## Backend

The backend is a Python API built with [dreema](https://pypi.org/project/dreema/). It listens on **port 8888** and handles `POST /api/attendance`.

### Running the backend

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install dreema

cd server
dreema run
```

The server runs at `http://localhost:8888`.

If your setup uses the template files (`settings.template.py`, `plug.template.py`), copy them to `settings.py` and `plug.py` and fill in your values first.

### Authentication

Every request must include the API key as a bearer token:

```http
Authorization: Bearer CHANGE_ME
```

The value must match `API_KEY` in the firmware.

### Request

```json
{
  "uid": "11223344",
  "device_id": "reader-01",
  "scan_id": "reader-01-1A2B3C4D5E6F7A8B",
  "scanned_at": 1791848101
}
```

| Field | Description |
|---|---|
| `uid` | Card UID as uppercase hex, no separators |
| `device_id` | Which reader sent the scan |
| `scan_id` | Unique per tap; the server uses it to ignore retries of a scan it already saved |
| `scanned_at` | Time of the tap in seconds since 1970 (UTC). `0` if the device's clock wasn't set yet, in which case the server uses its own receive time |

Example with curl:

```bash
curl -X POST http://localhost:8888/api/attendance \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer CHANGE_ME" \
  -d '{"uid":"11223344","device_id":"reader-01","scan_id":"test-0001","scanned_at":0}'
```

### Response

The result is nested inside `data`:

```json
{
  "data": {
    "status": "ok",
    "uid": "11223344",
    "name": "Kofi Boateng",
    "time": "2026-10-12T23:35:01.211027+00:00"
  },
  "message": "Operation completed",
  "status": 28,
  "trace": null
}
```

`data.status` tells the firmware what happened:

| `data.status` | Meaning | Contains |
|---|---|---|
| `ok` | Scan recorded | `uid`, `name`, `time` |
| `duplicate` | This `scan_id` was already recorded (a retry); nothing new was saved | `uid`, `name` |
| `unknown` | Card isn't registered; nothing was saved | `uid` |

The outer `status` and `trace` fields come from the framework's standard response wrapper.

### User lookup

Names are currently looked up from a hard-coded dictionary in the server code (UID to name). To register a person, add their card's UID and name there. A database table is the natural next step (see below).

### Attendance log

Each recorded scan is appended to `server/attendance.csv`:

```text
time,device_id,uid,name,scan_id
```

Example:

```text
2026-10-12T23:35:01.211027+00:00,reader-01,11223344,Kofi Boateng,reader-01-1A2B3C4D5E6F7A8B
```

`time` is the moment of the tap when the device knew it, otherwise the moment the server received the scan. Unknown cards and duplicate scans are not logged. Duplicate detection is held in memory, so it resets when the server restarts.

## Running with Wokwi

The simulation lets you test without hardware.

1. Install the **Wokwi Simulator** extension in VS Code and run **Wokwi: Request a new License**.
2. Build the firmware: PlatformIO checkmark, or `pio run`. Wokwi needs the files in `.pio/build/esp32dev/`.
3. Start the backend (see above).
4. **Expose the backend with a tunnel.** The simulated ESP32 can't reach `localhost` on your machine, so use a tunnel such as Cloudflare's:
   ```bash
   cloudflared tunnel --url http://localhost:8888
   ```
5. Copy the `https://...trycloudflare.com` address it prints and set `API_URL` in `src/main.cpp`:
   ```cpp
   const char* API_URL = "https://<your-address>.trycloudflare.com/api/attendance";
   ```
   The address **changes every time the tunnel restarts**, so repeat this step (and rebuild) each time.
6. Rebuild, then run **Wokwi: Start Simulator**.
7. Click the RFID module in the simulation, pick a card, and turn on **Hold** (or press **TAP**). The built-in cards have UIDs `01020304` (Blue) and `11223344` (Green).

To test offline behavior, stop the server, tap a few cards (the LCD shows `Pending: N`), then start the server again and watch the queued scans go through.

On real hardware you don't need a tunnel: point `API_URL` at your server's local address, for example `http://192.168.1.50:8888/api/attendance`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Firmware Version: 0x0` / "Communication failure" | RFID wiring. Check that SDA goes to GPIO 21 and that part ids in `diagram.json` match the connection names |
| Wokwi: "firmware binary ... not found" | Project hasn't been built, or paths in `wokwi.toml` don't match the folder under `.pio/build/` |
| Build error: multiple definition of `setup()` | A leftover `sketch.ino` next to `main.cpp` in `src/` |
| LCD stays blank | LCD wires on the wrong pins, or the I2C address isn't `0x27` |
| LCD shows `Welcome,` with no name | The firmware reads the name from `data.name`; check the server's response shape |
| `Pending: N` never goes down | Server or tunnel unreachable, or the tunnel address changed. Update `API_URL` and rebuild |
| `Rejected` | The server returned a 4xx, usually `API_KEY` not matching |
| First scan is slower than later ones | Normal: the first send sets up the secure connection and later ones reuse it. The terminal prints `Send took ... ms` for each send, so you can compare |
| Every send takes the same long time | The connection isn't being reused. Check the `Send took` lines and make sure the server or tunnel allows keep-alive |
| `Connection dropped, retrying with a fresh one` | The server closed the idle connection. The firmware retries once on its own, so this is harmless unless it repeats on every scan |
| Taps missed or nothing happens when a card is pulled away quickly | Check that the reader task is running (you should see `Queued scan` in the terminal for every tap). If not, the reader wiring or `SS_SPI_PIN` is the usual cause |
| `HTTP 307` | The URL uses `http://` but the server redirects to `https://`. Use the `https://` address |
| SSL error `-80` | The secure connection to that host is being cut off. Try another tunnel or network |
| Browser can't open the tunnel address | DNS problem on your network. Try `ipconfig /flushdns`, a different DNS (`1.1.1.1`), or another network |

## Security and privacy

- **Don't commit attendance data.** `attendance.csv` contains real names. Add it to `.gitignore`, along with any real `settings.py` / API keys.
- The firmware calls `setInsecure()`, which **skips TLS certificate verification**. That's fine for prototyping but not for production. Load your server's root CA with `setCACert()` instead.
- **Card UIDs can be cloned.** Basic MIFARE cards only broadcast a fixed ID, so this system is suitable for convenience-level attendance, not for access control or anything security-critical.
- Anyone who can see the LCD sees the name of whoever just checked in.

## Roadmap

- Move the user list and attendance records to a database (with a unique constraint on `scan_id`)
- Persist the scan queue to flash so pending scans survive a power cut
- Admin page to register cards and view attendance
- Check-in / check-out support
- Proper certificate validation

## License

This repository does not currently specify a license. If you plan to distribute or publish the project, consider adding one.
