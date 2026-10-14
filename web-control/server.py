"""Serve the local control page and relay dog commands through the matching LAN IP."""

import http.client
import ipaddress
import json
import os
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


DOG_IP = os.environ.get("XIAOZHI_DOG_IP", "10.1.56.231")
PORT = int(os.environ.get("XIAOZHI_WEB_PORT", "8080"))
ALLOWED_MOVES = {"F", "B", "L", "R", "S"}
ALLOWED_ACTIONS = {"2", "4", "7", "8", "9", "10", "12"}


def source_ip_for_dog():
    override = os.environ.get("XIAOZHI_DOG_SOURCE_IP")
    if override:
        return override
    try:
        dog = ipaddress.IPv4Address(DOG_IP)
        candidates = socket.gethostbyname_ex(socket.gethostname())[2]
        matching = [
            candidate
            for candidate in candidates
            if ipaddress.IPv4Address(candidate).packed[:2] == dog.packed[:2]
        ]
        return matching[0] if matching else None
    except (OSError, ValueError):
        return None


def dog_request(method, path, body=None):
    source = source_ip_for_dog()
    connection = http.client.HTTPConnection(
        DOG_IP,
        80,
        timeout=5,
        source_address=(source, 0) if source else None,
    )
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read(8192)
    finally:
        connection.close()


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlsplit(self.path).path != "/dog/status":
            return super().do_GET()
        try:
            status, body = dog_request("GET", "/")
            online = status == 200 and b"Espressif Systems" in body
            self.send_json(200, {"online": online, "ip": DOG_IP})
        except (OSError, http.client.HTTPException):
            self.send_json(200, {"online": False, "ip": DOG_IP})

    def do_POST(self):
        if urlsplit(self.path).path != "/dog/control":
            return self.send_error(404)
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send_json(403, {"error": "invalid origin"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 128:
                return self.send_json(400, {"error": "invalid request length"})
            payload = json.loads(self.rfile.read(length))
            valid = (
                isinstance(payload, dict)
                and (
                    (set(payload) == {"move"} and payload["move"] in ALLOWED_MOVES)
                    or (set(payload) == {"action"} and payload["action"] in ALLOWED_ACTIONS)
                )
            )
            if not valid:
                return self.send_json(400, {"error": "unsupported dog command"})
            status, body = dog_request("POST", "/control", json.dumps(payload).encode())
            result = json.loads(body)
            if status != 200 or str(result.get("code")) != "200":
                return self.send_json(
                    502,
                    {"error": "dog rejected command", "status": status, "device_code": result.get("code")},
                )
            self.send_json(200, {"code": 200})
        except (OSError, ValueError, http.client.HTTPException):
            self.send_json(502, {"error": "dog unavailable"})


if __name__ == "__main__":
    handler = partial(Handler, directory=str(Path(__file__).resolve().parent))
    with ThreadingHTTPServer(("127.0.0.1", PORT), handler) as server:
        print(f"Web control: http://127.0.0.1:{PORT}/ (dog {DOG_IP})", flush=True)
        server.serve_forever()
