const http = require("http");
const fs = require("fs");

const PORT = 3000;
const API_KEY = "CHANGE_ME"; // must match API_KEY in main.cpp

function send(res, status, obj) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(obj));
}

const server = http.createServer((req, res) => {
  if (req.method === "POST" && req.url === "/api/attendance") {
    // Check the key the ESP32 sends
    if (req.headers.authorization !== `Bearer ${API_KEY}`) {
      return send(res, 401, { error: "unauthorized" });
    }

    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try {
        const { uid, device_id } = JSON.parse(body);
        const time = new Date().toISOString();

        // Save one line per scan: time,device,uid
        fs.appendFileSync("attendance.csv", `${time},${device_id},${uid}\n`);
        console.log(`${time}  ${device_id}  ${uid}`);

        send(res, 200, { status: "ok", uid, time });
      } catch (err) {
        send(res, 400, { error: "bad request" });
      }
    });
  } else {
    send(res, 404, { error: "not found" });
  }
});

server.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});