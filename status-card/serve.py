"""Serve the FlightCheck status card on IPv4 loopback with no write routes."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from task_details import issue_stages
from task_status import read_task, task_path
from progress import freshness_observation

ROOT = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/card.css": ("card.css", "text/css; charset=utf-8"),
    "/shared.css": ("shared.css", "text/css; charset=utf-8"),
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
        if self.server.task_route and path.startswith(self.server.task_route + "settings/"):
            adapter = self.settings_request()
            if adapter is not None:
                adapter.do_GET()
                return
        if self.server.task_route:
            route = self.server.task_route
            if path == f"{route}status.json":
                self.task_status()
                return
            assets = {
                route: ("task.html", "text/html; charset=utf-8"),
                "/task.js": ("task.js", "text/javascript; charset=utf-8"),
                "/card.css": ASSETS["/card.css"],
                "/shared.css": ASSETS["/shared.css"],
                route + "settings/": ("settings.html", "text/html; charset=utf-8"),
                route + "settings/settings.js": ("settings.js", "text/javascript; charset=utf-8"),
                route + "settings/card.css": ASSETS["/card.css"],
                route + "settings/shared.css": ASSETS["/shared.css"],
                route + "settings/settings.css": ("settings.css", "text/css; charset=utf-8"),
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
        freshness = freshness_observation(snapshot)
        if freshness is not None:
            snapshot["freshness"] = freshness
        snapshot.pop("tracked_flights", None)
        status = 503 if snapshot["mode"] == "flight" and not snapshot["completeness"]["ready"] else 200
        self.json_status(snapshot, status)

    def json_status(self, snapshot, status=200):
        body = json.dumps({**snapshot, "publicationPort": self.server.server_port}).encode()
        self.reply(status, body, "application/json; charset=utf-8")

    def do_POST(self):
        if not self.allowed_request():
            return
        if self.server.task_route and urlsplit(self.path).path.startswith(self.server.task_route + "settings/api/"):
            adapter = self.settings_request()
            if adapter is not None:
                adapter.do_POST()
                return
        self.reply(405, b"Read-only endpoint.\n", "text/plain; charset=utf-8")

    def read_only(self):
        self.reply(405, b"Read-only endpoint.\n", "text/plain; charset=utf-8")

    do_PUT = read_only
    do_PATCH = read_only
    do_DELETE = read_only

    def settings_request(self):
        if not (self.server.task_file.parent / "settings-session.json").exists():
            return None
        import sys
        source = ROOT.parent / "src"
        if not (source / "flightcheck_cli/settings.py").exists():
            source = ROOT.parent / "cli"
            import hashlib
            try:
                state = json.loads((ROOT.parent / "installation.json").read_bytes())
                for name in ("__init__.py", "cli.py", "source.py", "transaction.py", "settings.py"):
                    path = source / "flightcheck_cli" / name
                    relative = ".flightcheck/cli/flightcheck_cli/" + name
                    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != state["files"][relative]["sha256"]:
                        return None
            except (OSError, ValueError, KeyError, TypeError):
                return None
        sys.path.insert(0, str(source))
        from flightcheck_cli.settings import card_request
        try:
            return card_request(self, ROOT)
        except (OSError, ValueError, KeyError, TypeError):
            return None

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
