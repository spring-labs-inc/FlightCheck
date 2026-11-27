"""Explicit private Settings session over the common configuration transaction.

Guide: docs/settings.md in source, .flightcheck/docs/settings.md in a copied project.
"""
import argparse
import copy
import hmac
from http.client import HTTPConnection
import importlib.util
import json
import os
from pathlib import Path
import secrets
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from types import SimpleNamespace

from . import cli, transaction as tx
from .source import encoded, sha

SERVICE_REVISION = sha(b"\0".join(Path(__file__).with_name(name).read_bytes()
                                 for name in ("settings.py", "cli.py", "transaction.py", "source.py")))
_HELPER_LOCK = threading.RLock()


class Settings:
    def __init__(self, engine, root, task, session, registry=None, *, reference):
        self.engine, self.root = engine, Path(root).resolve()
        if not task or not session or not reference:
            raise ValueError("Explicit project, task, session and local Settings authorization reference required")
        self.task, self.session, self.reference = task, session, reference
        self.registry = Path(registry) if registry else None
        self.repository = engine.git(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        self.project = sha(encoded({"root": str(self.root), "repository": self.repository}))
        self.token = secrets.token_urlsafe(32)
        self.context = {"project": self.project, "task": task, "session": session}
        self.plans = {}

    def verify_context(self):
        if self.engine.git(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir") != self.repository:
            raise ValueError("Settings project identity changed; explicitly launch a new scoped session")

    def helpers(self):
        # Select this project's verified installed common helper. Ambient
        # imports from another project/session cannot replace its pinned model.
        state, _ = cli.configuration_integrity(self.engine, self.root)
        scripts = self.root / ".flightcheck/scripts"
        names = ("flight_associations.py", "repository_audit.py", "project_config.py")
        identity = tuple(state["files"][".flightcheck/scripts/" + n]["sha256"] for n in names)
        with _HELPER_LOCK:
            cached = getattr(self, "_helpers", None)
            if cached and cached[0] == identity:
                return cached[1]
            associations = cli.load_installer(scripts / "flight_associations.py")
            model = cli.configuration_model(self.engine, self.root)
            previous = {name: sys.modules.get(name) for name in ("flight_associations", "project_config")}
            try:
                sys.modules.update(flight_associations=associations, project_config=model)
                audit = cli.load_installer(scripts / "repository_audit.py")
            finally:
                for name, module in previous.items():
                    if module is None:
                        sys.modules.pop(name, None)
                    else:
                        sys.modules[name] = module
            self._helpers = (identity, (associations, audit))
            return self._helpers[1]

    def bindings(self):
        if not self.registry:
            return []
        associations, _ = self.helpers()
        return [r for r in associations.Registry(self.registry).read()["records"]
                if r["repository"]["git_common_dir"] == self.engine.git(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir")]

    def read(self):
        self.verify_context()
        if not (self.root / self.engine.CONFIG).exists() or not (self.root / self.engine.STATE).exists():
            return {"status": "unconfigured", "reason": "Configure this project through shared setup before editing Settings", "context": self.context}
        if tx.pending(self.root):
            return {"status": "recovery_required", "reason": "An interrupted common transaction requires explicit recovery", "context": self.context}
        _, pin = cli.configuration_integrity(self.engine, self.root)
        model = cli.configuration_model(self.engine, self.root)
        current = model.snapshot(self.root)
        if getattr(model, "SETTINGS_SCHEMA", None) != 1:
            return {"status": "incompatible", **current, "context": self.context,
                    "reason": "This pinned configuration adapter predates Settings. Preview and explicitly apply the bounded configuration-adapter update before editing; workflow and runtime pins remain preserved."}
        details = getattr(self, "_board_details", None)
        board = current["values"].get("resources", {}).get("project_board")
        if not (details and isinstance(board, dict) and board.get("url", "").rstrip("/") == details["url"].rstrip("/") and details["project_id"] == current["values"]["status_sync"]["project_id"] and details["field"]["id"] == current["values"]["status_sync"]["field_id"]):
            details = None
        return {"status": "configuration", **current, "context": self.context, "board_details": details,
                "repository": {"checkout": str(self.root), "git_common_dir": self.repository},
                "runtime": cli.runtime_structure(current["values"], pin["runtime"]) if pin else {"status": "unconfigured"},
                "flights": [{"flight": r["flight"], "configuration": r["configuration"], "reconfiguration": r.get("reconfiguration"),
                             "grants": r["grants"], "cleanup": r.get("cleanup"), "lifecycle": r["lifecycle"]} for r in self.bindings()],
                "capabilities": {"native_checkout": "Unavailable observation; managed in the native client's checkout settings",
                                 "runtime_reconciliation": "Explicit terminal runtime reconciliation; displayed executable is pinned",
                                 "mandatory": "Checkout verification, ownership, protected branches and safe closeout remain required"}}

    def preview(self, data):
        self.verify_context()
        if getattr(cli.configuration_model(self.engine, self.root), "SETTINGS_SCHEMA", None) != 1:
            raise ValueError("Explicit configuration-adapter update required before Settings editing")
        # The local capability already carries the owner's explicit write
        # authorization. Record the deliberate preview/save decision internally,
        # retaining explicit references supplied by existing API callers.
        reference = data.get("reference") or self.reference + "#settings-" + secrets.token_hex(12)
        changes = copy.deepcopy(data["changes"])
        if changes.get("activation") == "default-for-coding" and "activation_reference" not in changes:
            changes["activation_reference"] = reference
        policy = changes.get("checkout_policy")
        if not data.get("reference") and policy and policy.get("git_fallback") and not policy.get("fallback_reference"):
            policy["fallback_reference"] = reference
        plan, _ = cli.configuration_plan(self.engine, self.root, changes, data["expected_revision"], reference)
        self.verify_context()
        identifier = sha(encoded(plan))
        self.plans[identifier] = plan
        current = cli.configuration_model(self.engine, self.root).snapshot(self.root)
        return {"status": "configuration_preview", "plan_id": identifier, "revision": current["revision"],
                "changes": {k: {"before": current["values"].get(k), "after": plan["configuration"].get(k)} for k in data["changes"]},
                "effects": {"scope": "Future flights; active snapshots and grants unchanged", "operations": plan["operations"],
                            "revalidation": "Explicit active-flight adoption requires a separate reconfiguration decision"}}

    def apply(self, data):
        self.verify_context()
        plan = self.plans.get(data["plan_id"])
        if plan is None:
            raise ValueError("Unknown or expired preview; preview again")
        result = cli.configuration_apply(self.engine, self.root, plan)
        self.plans.clear()
        return result

    def board_provider(self):
        """Reuse the verified installed provider's existing read-only transport."""
        state, _ = cli.configuration_integrity(self.engine, self.root)
        path = self.root / ".flightcheck/scripts/status_sync_github.py"
        expected = state["files"].get(".flightcheck/scripts/status_sync_github.py", {}).get("sha256")
        if path.is_symlink() or not expected or sha(path.read_bytes()) != expected:
            raise ValueError("Verified board provider is unavailable; use Advanced connection setup")
        provider = cli.load_installer(path)
        return provider.GitHubProjects("", self.read()["values"]["status_sync"])

    def board_discover(self, data):
        self.verify_context()
        if data.get("authorize_read") is not True:
            raise ValueError("Board details require an explicit read authorization")
        url = data.get("url")
        if not isinstance(url, str) or not re.fullmatch(r"https://github\.com/(orgs|users)/[A-Za-z0-9_.-]+/projects/[1-9][0-9]*/?", url):
            raise ValueError("Use the exact existing GitHub project URL or Advanced connection setup")
        kind, owner, _, number = urlsplit(url).path.strip("/").split("/")
        board = self.read()["values"].get("resources", {}).get("project_board")
        policy = self.read()["values"]["status_sync"]
        fields = "id title url closed fields(first:100){pageInfo{hasNextPage} nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}"
        if isinstance(board, dict) and board.get("url", "").rstrip("/") == url.rstrip("/") and board.get("project_id") == policy["project_id"]:
            query = "query($project:ID!){project:node(id:$project){... on ProjectV2{" + fields + "}}}"
            variables = {"project": policy["project_id"]}
        else:
            owner_type = "organization" if kind == "orgs" else "user"
            query = "query($owner:String!,$number:Int!){owner:" + owner_type + "(login:$owner){project:projectV2(number:$number){" + fields + "}}}"
            variables = {"owner": owner, "number": int(number)}
        result = self.board_provider().query(query, variables)
        project = result.get("project") or (result.get("owner") or {}).get("project")
        if (not isinstance(project, dict) or not project.get("id") or not project.get("title")
                or project.get("url", "").rstrip("/") != url.rstrip("/") or project.get("closed") is not False):
            raise ValueError("Existing board identity or availability could not be verified")
        if "project" in variables and project["id"] != variables["project"]:
            raise ValueError("Board identity changed; reconcile its connection")
        connection = project.get("fields", {})
        if connection.get("pageInfo", {}).get("hasNextPage") is not False or not isinstance(connection.get("nodes"), list):
            raise ValueError("Board field observation is incomplete; use Advanced connection setup")
        fields = [f for f in connection["nodes"] if isinstance(f, dict) and f.get("options") is not None]
        same_board = project["id"] == policy["project_id"]
        chosen = [f for f in fields if same_board and f.get("id") == policy["field_id"]]
        if not chosen:
            chosen = [f for f in fields if f.get("name", "").casefold() == "status"]
        if len(chosen) != 1:
            raise ValueError("Status field is missing or ambiguous; use Advanced connection setup")
        field = chosen[0]
        if (not field.get("id") or not field.get("name") or not isinstance(field.get("options"), list)
                or not field["options"] or any(not isinstance(o, dict) or not o.get("id") or not o.get("name") for o in field["options"])
                or len({o["id"] for o in field["options"]}) != len(field["options"])):
            raise ValueError("Status options are incomplete; use Advanced connection setup")
        self._board_details = {"observed_at": time.time(), "provider": "github-projects-v2", "project_id": project["id"], "title": project["title"],
                "url": project["url"], "field": {"id": field["id"], "name": field["name"],
                                               "options": [{"id": o["id"], "name": o["name"]} for o in field["options"]]}}
        return copy.deepcopy(self._board_details)

    def recover(self):
        self.verify_context()
        with tx.locked(self.root) as state:
            record = tx.journal(state)
            interrupted = bool(record and record["status"] in ("prepared", "rollback_required"))
            if interrupted:
                tx.restore(self.engine, self.root, state, record)
            return {"status": "rolled_back" if interrupted else "nothing_to_recover"}

    def audit(self, remote=False):
        self.verify_context()
        if type(remote) is not bool:
            raise ValueError("Audit remote observations require an explicit boolean choice")
        if not self.registry:
            raise ValueError("Read-only audit needs the explicit private Registry locator")
        associations, audit = self.helpers()
        repository = self.engine.git(self.root, "remote", "get-url", "origin")
        repository = audit._github_repository(repository)
        if not repository:
            raise ValueError("Read-only audit needs an explicit supported repository identity")
        return audit.audit(self.root, self.registry, repository, remote=remote)

    def reconfigure_preview(self, data):
        self.verify_context()
        if not self.registry:
            raise ValueError("Explicit active-flight reconfiguration needs the private Registry")
        associations, _ = self.helpers()
        registry = associations.Registry(self.registry)
        state = registry.read()
        old = next((r for r in state["records"] if r["flight"] == data["flight"]), None)
        if not old or old["flight"] != self.task or old["lifecycle"]["state"] not in ("active", "review"):
            raise ValueError("This Settings capability can reconfigure only its own active flight")
        if old["repository"]["git_common_dir"] != self.engine.git(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir"):
            raise ValueError("Active flight belongs to another repository")
        current = cli.configuration_model(self.engine, self.root).snapshot(self.root)
        reference = data.get("reference") or self.reference + "#active-settings-" + secrets.token_hex(12)
        updated = associations.reconfigure(old, current, reference)
        plan = {"kind": "active-reconfiguration", "registry_revision": state["revision"], "configuration_revision": current["revision"], "record": updated}
        identifier = sha(encoded(plan)); self.plans[identifier] = plan
        return {"status": "reconfiguration_preview", "plan_id": identifier, "effects": updated["reconfiguration"], "grants_unchanged": True,
                "next": "Affected checkout/check/evidence/status-sync validation remains required before execution"}

    def reconfigure_apply(self, data):
        self.verify_context()
        plan = self.plans.get(data["plan_id"])
        if not plan or plan.get("kind") != "active-reconfiguration":
            raise ValueError("Preview the exact active-flight reconfiguration first")
        associations, _ = self.helpers()
        if cli.configuration_model(self.engine, self.root).snapshot(self.root)["revision"] != plan["configuration_revision"]:
            raise ValueError("Configuration changed; preview active reconfiguration again")
        result = associations.Registry(self.registry).save(plan["record"], expected_revision=plan["registry_revision"])
        self.plans.clear()
        return {"status": "reconfigured_pending_revalidation", "reconfiguration": result["record"]["reconfiguration"]}


class Handler(BaseHTTPRequestHandler):
    def send(self, status, value, content_type="application/json; charset=utf-8"):
        raw = encoded(value) if content_type.startswith("application/json") else value
        self.send_response(status)
        for key, val in {"Content-Type": content_type, "Content-Length": str(len(raw)), "Cache-Control": "no-store",
                         "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
                         "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"}.items():
            self.send_header(key, val)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def allowed(self, private=False):
        from urllib.parse import urlsplit
        for field in ("Host", "Origin"):
            values = self.headers.get_all(field, [])
            if field == "Origin" and not values:
                continue
            if len(values) != 1:
                return False
            try:
                route = urlsplit(values[0] if field == "Origin" else "http://" + values[0])
                if route.scheme != "http" or route.hostname not in ("localhost", "127.0.0.1", "::1") or route.username or route.password or route.path or route.query or route.fragment or route.port == 0:
                    return False
            except ValueError:
                return False
        if private:
            s = self.server.settings
            if len(self.headers.get_all("Authorization", [])) != 1:
                return False
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + s.token):
                return False
            if any(self.headers.get_all("X-FlightCheck-" + k.title(), []) != [v] for k, v in s.context.items()):
                return False
        return True

    def do_GET(self):
        if not self.allowed():
            self.send(403, {"error": "Settings session unavailable"}); return
        path = urlsplit(self.path).path
        route = self.server.route
        assets = {route: ("settings.html", "text/html; charset=utf-8"), route + "settings.js": ("settings.js", "text/javascript; charset=utf-8"), route + "card.css": ("card.css", "text/css; charset=utf-8"), route + "settings.css": ("settings.css", "text/css; charset=utf-8")}
        if path in assets:
            name, kind = assets[path]; self.send(200, (self.server.assets / name).read_bytes(), kind); return
        if path != route + "api/read" or not self.allowed(True):
            self.send(403, {"error": "An explicit matching local Settings capability is required"}); return
        try:
            self.send(200, {**self.server.settings.read(), "service_revision": SERVICE_REVISION})
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.send(409, {"status": "conflict", "error": str(error)})

    def do_POST(self):
        route = self.server.route
        if not self.allowed(True) or not urlsplit(self.path).path.startswith(route + "api/"):
            self.send(403, {"error": "An explicit matching local Settings capability is required"}); return
        try:
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise ValueError("Unsupported Settings request framing")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 * 1024:
                raise ValueError("Settings request size is invalid")
            data = json.loads(self.rfile.read(length))
            action = urlsplit(self.path).path[len(route + "api/"):]
            s = self.server.settings
            actions = {"preview": lambda: s.preview(data), "apply": lambda: s.apply(data), "recover": s.recover,
                       "board-discover": lambda: s.board_discover(data),
                       "audit": lambda: s.audit(remote=data.get("remote", False)), "reconfigure-preview": lambda: s.reconfigure_preview(data), "reconfigure-apply": lambda: s.reconfigure_apply(data)}
            if action not in actions:
                raise ValueError("Unsupported Settings action")
            self.send(200, actions[action]())
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.send(409, {"status": "conflict", "error": str(error)})

    def log_message(self, *args):
        pass  # Tokens, plans, references and private project values stay out of logs.


class CardRequest(Handler):
    """Use the existing task listener and its delivered browser route."""
    def __init__(self, request, service, route, assets):
        self.request = request
        self.server = SimpleNamespace(settings=service, route=route, assets=assets)

    def __getattr__(self, key):
        return getattr(self.request, key)

    def send_response(self, *args): return self.request.send_response(*args)
    def send_header(self, *args): return self.request.send_header(*args)
    def end_headers(self): return self.request.end_headers()


def card_request(request, assets):
    """A private owner-only binding enables this exact task, never a snapshot."""
    path = request.server.task_file.parent / "settings-session.json"
    if not path.exists():
        return None
    tx.no_links(path)
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Settings capability file must be private")
    raw = path.read_bytes()
    binding = json.loads(raw)
    task = request.server.task_route.removeprefix("/task/").rstrip("/")
    if binding["task"] != task:
        raise ValueError("Settings capability belongs to another task")
    cached = getattr(request.server, "settings_binding", None)
    if cached is None or cached[0] != sha(raw):
        engine = cli.load_installer(binding["engine"])
        service = Settings(engine, Path(binding["root"]), task, binding["session"], binding.get("registry"), reference=binding["reference"])
        service.token = binding["token"]
        request.server.settings_binding = (sha(raw), service)
    return CardRequest(request, request.server.settings_binding[1], request.server.task_route + "settings/", assets)


def prepare_route(engine, status, task, session, browser_observation=None):
    """Revalidate through #128's existing task lifecycle, not saved URL reuse."""
    recorded = json.loads((status.parent / "reply-route.json").read_bytes())
    if recorded.get("task") != task or not recorded.get("checkout"):
        raise ValueError("Settings route belongs to another task or lacks its checkout")
    base = Path(engine.__file__).resolve().parent
    assets = base / "status-card" if base.name == ".flightcheck" else base.parent / "status-card"
    sys.path.insert(0, str(assets))
    import reply
    args = SimpleNamespace(task=task, title=None, summary=None, details=None, verdict=None, verdict_candidate=None,
                           session=session, execution=recorded["execution"], user_url=None,
                           browser_observation=browser_observation, reconcile_route=False)
    result = reply.prepare(Path(recorded["checkout"]), status.parent.parent.parent, args)
    if result.get("task") != task:
        raise ValueError("Prepared route belongs to another task")
    return result


def ensure_settings_listener(engine, status, settings, route):
    """Refresh only a verified owned listener whose loaded Settings code is old."""
    if route.get("publication") != "verified":
        raise ValueError("The task listener is unavailable; restore it before opening Settings")
    observed = urlsplit(route["host_url"])
    if observed.hostname not in ("127.0.0.1", "localhost", "::1") or observed.scheme != "http":
        raise ValueError("Expected the supported task loopback listener")
    headers = {"Authorization": "Bearer " + settings.token,
               **{"X-FlightCheck-" + k.title(): v for k, v in settings.context.items()}}
    def current():
        connection = HTTPConnection(observed.hostname, observed.port, timeout=2)
        try:
            connection.request("GET", observed.path.rstrip("/") + "/settings/api/read", headers=headers)
            result = connection.getresponse(); raw = result.read()
            if result.status == 404:
                return False
            if result.status != 200:
                raise ValueError("Settings configuration is unavailable; reconcile its reported conflict before opening it")
            return json.loads(raw).get("service_revision") == SERVICE_REVISION
        finally:
            connection.close()
    if current():
        return
    base = Path(engine.__file__).resolve().parent
    assets = base / "status-card" if base.name == ".flightcheck" else base.parent / "status-card"
    sys.path.insert(0, str(assets))
    import fcntl, maintainer
    with (status.parent / "listener.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        endpoint = maintainer.read_json(status.parent / "endpoint.json")
        data = maintainer.read_json(status)
        if endpoint.get("port") != observed.port or data.get("task") != settings.task or data.get("candidate") != route.get("candidate"):
            raise ValueError("Task listener changed; prepare the exact Settings session again")
        if not current():
            maintainer.stop_outdated_listener(status, data, endpoint)
            endpoint = maintainer.start_listener(status, data, endpoint["port"])
            maintainer.write_json(status.parent / "endpoint.json", endpoint)
        if not current():
            raise ValueError("Current Settings handler is unavailable on the preserved task route")


def main(argv, engine):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--task", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--authorize-local-settings", required=True, metavar="OWNER_REFERENCE")
    parser.add_argument("--registry")
    parser.add_argument("--card-status", type=Path, required=True, help="Existing private status.json for this exact task listener")
    parser.add_argument("--browser-observation", type=Path, help="Existing fresh supported browser observation for this exact connection")
    args = parser.parse_args(argv)
    root = cli.target(engine, args.target)
    if not args.task.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid task identifier")
    settings = Settings(engine, root, args.task, args.session, args.registry, reference=args.authorize_local_settings)
    status = tx.no_links(args.card_status.expanduser().absolute())
    tx.private_dir(status.parent, create=False)
    snapshot = json.loads(status.read_bytes())
    if snapshot.get("task") != args.task:
        raise ValueError("Settings must use the exact task card")
    binding = {"schema": 1, "task": args.task, "root": str(root), "session": args.session,
               "registry": args.registry, "reference": args.authorize_local_settings,
               "engine": str(Path(engine.__file__).resolve()), "token": settings.token}
    tx.atomic(status.parent / "settings-session.json", encoded(binding))
    fragment = "&".join(k + "=" + v for k, v in {"cap": settings.token, **settings.context}.items())
    route = prepare_route(engine, status, args.task, args.session, args.browser_observation)
    ensure_settings_listener(engine, status, settings, route)
    url = route.get("user_url") if route.get("status") == "published" else None
    if not url:
        # This result is private local output, never card publication. The host
        # target is only for a supported native-preview request, not a client URL.
        print(json.dumps({"status": "browser_route_unavailable", "task": args.task, "candidate": route.get("candidate"),
                          "host_preview_url": route["host_url"].rstrip("/") + "/settings/#" + fragment if route.get("publication") == "verified" else None,
                          "guidance": route.get("guidance")}))
        return 1
    print(url.rstrip("/") + "/settings/#" + fragment)
    return 0
