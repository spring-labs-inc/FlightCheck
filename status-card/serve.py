"""Serve the SpringDev status card on IPv4 loopback with no write routes."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/card.css": ("card.css", "text/css; charset=utf-8"),
    "/card.js": ("card.js", "text/javascript; charset=utf-8"),
}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


class StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/status.json":
            body = json.dumps(self.server.snapshot).encode()
            self.reply(200, body, "application/json; charset=utf-8")
        elif path in ASSETS:
            filename, content_type = ASSETS[path]
            self.reply(200, (ROOT / filename).read_bytes(), content_type)
        else:
            self.reply(404, b"Not found.\n", "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):
        self.reply(405, b"Read-only endpoint.\n", "text/plain; charset=utf-8")

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 405:
            self.send_header("Allow", "GET, HEAD")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    snapshot = json.loads((ROOT / "pilot.json").read_text(encoding="utf-8"))
    with ThreadingHTTPServer(("127.0.0.1", args.port), StatusHandler) as server:
        snapshot["publicationPort"] = server.server_port
        server.snapshot = snapshot
        print(f"SpringDev status card at http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
