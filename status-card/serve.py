"""Serve the FlightCheck status card on IPv4 loopback with no write routes."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from task_details import issue_stages
from task_status import read_task, task_path

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
    def allowed_request(self):
        """Reject rebinding origins; forwarding may use another loopback port."""
        def loopback(value, origin=False):
            if not value or any(char.isspace() or ord(char) < 32 for char in value):
                return False
            try:
                route = urlsplit(value if origin else "http://" + value)
                port = route.port
                host = route.hostname
                authority = "[::1]" if host == "::1" else host
                if port is not None:
                    authority += f":{port}"
                return (route.scheme == "http" and host in ("127.0.0.1", "localhost", "::1")
                        and route.netloc == authority and port != 0
                        and not route.path and not route.query and not route.fragment)
            except (ValueError, TypeError):
                return False
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        target = self.requestline.split()[1]
        if (not target.startswith("/") or target.startswith("//")
                or len(hosts) != 1 or not loopback(hosts[0])
                or (origins and (len(origins) != 1 or not loopback(origins[0], origin=True)))):
            self.reply(403, b"Use a loopback Host and, when supplied, a loopback HTTP Origin.\n",
                       "text/plain; charset=utf-8")
            return False
        return True

    def do_GET(self):
        if not self.allowed_request():
            return
        path = urlsplit(self.path).path
        if self.server.task_route:
            route = self.server.task_route
            if path == f"{route}status.json":
                self.task_status()
                return
            assets = {
                route: ("task.html", "text/html; charset=utf-8"),
                "/task.js": ("task.js", "text/javascript; charset=utf-8"),
                "/card.css": ASSETS["/card.css"],
            }
        else:
            if path == "/status.json":
                self.json_status(self.server.snapshot)
                return
            assets = ASSETS
        if path in assets:
            filename, content_type = assets[path]
            self.reply(200, (ROOT / filename).read_bytes(), content_type)
        else:
            self.reply(404, b"Not found.\n", "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def task_status(self):
        try:
            snapshot = read_task(self.server.task_file)
            if task_path(snapshot["task"]) != self.server.task_route:
                raise ValueError("Snapshot belongs to a different task")
        except (OSError, ValueError):
            self.reply(503, b"Task snapshot unavailable.\n", "text/plain; charset=utf-8")
            return
        snapshot["issue_stages"] = issue_stages(snapshot)
        snapshot.pop("tracked_flights", None)
        status = 503 if snapshot["mode"] == "flight" and not snapshot["completeness"]["ready"] else 200
        self.json_status(snapshot, status)

    def json_status(self, snapshot, status=200):
        body = json.dumps({**snapshot, "publicationPort": self.server.server_port}).encode()
        self.reply(status, body, "application/json; charset=utf-8")

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
    parser.add_argument("--task-status", type=Path, help="Private curated snapshot for one task")
    args = parser.parse_args()
    try:
        if args.task_status:
            snapshot = read_task(args.task_status)
            route = task_path(snapshot["task"])
        else:
            snapshot = json.loads((ROOT / "pilot.json").read_text(encoding="utf-8"))
            route = ""
    except (OSError, ValueError) as error:
        parser.error(str(error))
    with ThreadingHTTPServer(("127.0.0.1", args.port), StatusHandler) as server:
        server.snapshot = snapshot
        server.task_file = args.task_status
        server.task_route = route
        print(f"FlightCheck status card at http://127.0.0.1:{server.server_port}{route or '/'}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
