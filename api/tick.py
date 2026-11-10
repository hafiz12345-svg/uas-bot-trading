from http.server import BaseHTTPRequestHandler
import os, json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        secret = os.environ.get("CRON_SECRET", "")
        auth = self.headers.get("Authorization", "")
        if not secret or auth != f"Bearer {secret}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"unauthorized")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())
