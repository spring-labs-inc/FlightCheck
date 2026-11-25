"""Focused adapter-boundary witnesses; observed browser data is synthetic here."""

import argparse
import fcntl
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))
CARD = PRODUCT / "status-card"
sys.path.insert(0, str(CARD))


def load(name):
    spec = importlib.util.spec_from_file_location("route_test_" + name, CARD / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RouteDiscoveryTests(unittest.TestCase):
    def project(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); checkout = root / "project"; checkout.mkdir()
        shutil.copytree(CARD, checkout / "status-card")
        env = {key: value for key, value in os.environ.items() if key not in
               ("CODEX_THREAD_ID", "CLAUDE_SESSION_ID", "FLIGHTCHECK_SESSION", "FLIGHTCHECK_REGISTRY", "FLIGHTCHECK_FLIGHT")}
        env.update(FLIGHTCHECK_STATE_DIR=str(root / "state"))
        for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                     "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture"]):
            subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True)
        def cleanup():
            for path in (root / "state").glob("*/tasks/*/endpoint.json"):
                try: os.kill(json.loads(path.read_text())["pid"], signal.SIGTERM)
                except ProcessLookupError: pass
        self.addCleanup(cleanup)
        return root, checkout, env

    def prepared(self, fixture, task="first", session="controller", extra=(), expected=1):
        root, checkout, env = fixture; reply = load("reply")
        current = reply.maintainer.candidate(checkout)
        stages = ["Plan", "Implement", "Cheap Tests", "Interactive UI Approval", "Independent Code Review",
                  "Authoritative Gates", "Skeptical Evidence Review", "Final Verdict", "PR & Merge"]
        details = {"stages": {name: "current" if name == "Plan" else "pending" for name in stages},
                   "check_plan": [], "checks": [], "checks_unavailable": "Synthetic fixture.",
                   "links_unavailable": {"issue": "Synthetic fixture.", "pr": "No delivery."}}
        path = root / (task + "-details.json"); path.write_text(json.dumps(details))
        args = [sys.executable, "-B", "status-card/reply.py", "prepare", "--task", task, "--session", session,
                "--execution", "remote", "--details", str(path), *extra]
        result = subprocess.run(args, cwd=checkout, env=env, capture_output=True, text=True, timeout=20)
        data = json.loads(result.stdout); self.assertEqual(result.returncode, expected, data)
        return data

    def observed(self, fixture, prepared, task="first", **updates):
        root, checkout, env = fixture; reply = load("reply")
        directory, = (root / "state").glob("*/tasks/" + task)
        number = json.loads((directory / "endpoint.json").read_text())["port"]
        snapshot = reply.maintainer.current_card(task, number, prepared["candidate"])
        tab = dict(self.tab(task=task, candidate=prepared["candidate"]), snapshot=snapshot)
        value = dict(schema=1, context=prepared["context"], observed_at=time.time(), tabs=[tab], can_reveal=True, can_open=True)
        value.update(updates)
        path = root / (task + "-browser.json"); path.write_text(json.dumps(value)); path.chmod(0o600)
        return path, value, directory

    def checked(self, fixture, prepared, task="first", session="controller", expected=0):
        root, checkout, env = fixture; draft = root / "draft.txt"; draft.write_text(prepared["footer"])
        result = subprocess.run([sys.executable, "-B", "status-card/reply.py", "check", "--task", task,
                                 "--session", session, "--execution", "remote", "--reply-file", str(draft)],
                                cwd=checkout, env=env, capture_output=True, text=True, timeout=20)
        data = json.loads(result.stdout); self.assertEqual(result.returncode, expected, data); return data

    def test_native_route_refresh_witness(self):
        fixture = self.project(); initial = self.prepared(fixture)
        path, observation, directory = self.observed(fixture, initial)
        old = dict(observation["tabs"][0], id="wrong-visible", visible=True,
                   snapshot=dict(observation["tabs"][0]["snapshot"], candidate="a" * 64))
        observation["tabs"].insert(0, old); path.write_text(json.dumps(observation))
        exact = self.prepared(fixture, extra=["--browser-observation", str(path)], expected=0)
        actions = []; actions.append((exact["browser_action"], exact["tab_id"]))
        self.assertEqual(actions, [("reveal", "exact")])
        self.checked(fixture, exact)
        saved = json.loads((directory / "reply-route.json").read_text())
        self.assertEqual(saved["route_verification"]["candidate"], exact["candidate"])
        saved["route_verification"]["observed_at"] = time.time() - 31
        (directory / "reply-route.json").write_text(json.dumps(saved))
        stale = self.checked(fixture, exact, expected=1); self.assertNotIn("http", stale["footer"])
        resumed = self.prepared(fixture); self.assertNotIn("http", resumed["footer"])
        (fixture[1] / "changed.txt").write_text("A new source candidate\n")
        changed = self.prepared(fixture); self.assertNotEqual(changed["candidate"], exact["candidate"])
        path, _, _ = self.observed(fixture, changed)
        fresh = self.prepared(fixture, extra=["--browser-observation", str(path)], expected=0)
        self.checked(fixture, fresh)

    def test_manual_two_controller_witness(self):
        fixture = self.project(); url = "http://localhost:61295/task/first/"
        worker = self.prepared(fixture, extra=["--user-url", url], expected=0)
        # Existing explicit reconciliation records the authorized PM handoff;
        # it does not supply a new URL or inherit fresh browser observations.
        pm = self.prepared(fixture, session="pm", extra=["--reconcile-route"], expected=0)
        self.assertEqual(pm["user_url"], url)
        for session in ("controller", "pm"):
            reused = self.prepared(fixture, session=session, expected=0)
            self.assertEqual(reused["footer"], worker["footer"])
            self.assertEqual(reused["browser_reachability"], "unobserved")
            self.assertEqual(reused["browser_rendering"], "unobserved")
            self.checked(fixture, reused, session=session)
        directory, = (fixture[0] / "state").glob("*/tasks/first")
        saved = json.loads((directory / "reply-route.json").read_text())
        self.assertEqual(set(saved["manual_route"]["sessions"]), {"controller", "pm"})
        self.assertEqual(saved["manual_route"]["source_context"]["session"], "controller")
        # Configuration is retained beyond observation freshness. Neither its
        # old timestamp nor later host publication becomes browser verification.
        saved["route_verification"]["observed_at"] = 0
        (directory / "reply-route.json").write_text(json.dumps(saved))
        self.prepared(fixture, session="pm", expected=0)
        denied = self.prepared(fixture, session="unregistered")
        self.assertNotIn("http", denied["footer"])
        self.assertEqual(json.loads((directory / "reply-route.json").read_text())["user_url"], url)
        self.prepared(fixture, session="controller", expected=0)

    def test_saved_conflict_native_fallback_witness(self):
        fixture = self.project(); initial = self.prepared(fixture)
        path, observation, _ = self.observed(fixture, initial)
        response = dict(observation["tabs"][0]["snapshot"])
        class Endpoint(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(response).encode(); self.send_response(200)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join(2)))
        observation["tabs"][0]["url"] = f"http://127.0.0.1:{server.server_port}/task/first/"
        path.write_text(json.dumps(observation))
        verified = self.prepared(fixture, extra=["--browser-observation", str(path)], expected=0)
        # The adapter observed a responding saved endpoint with the wrong
        # candidate, then an available native inventory with no replacement.
        response["candidate"] = "a" * 64
        browser = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            browser.request("GET", "/task/first/status.json"); received = browser.getresponse()
            self.assertEqual(received.status, 200); wrong_snapshot = json.loads(received.read())
        finally: browser.close()
        old = dict(observation["tabs"][0], snapshot=wrong_snapshot)
        observation.update(observed_at=time.time(), saved_endpoint=old, tabs=[])
        path.write_text(json.dumps(observation))
        failed = self.prepared(fixture, extra=["--browser-observation", str(path)])
        self.assertEqual(failed["route_attempts"], ["saved", "native"])
        self.assertIn("candidate", failed["guidance"])
        self.assertNotIn("http", failed["footer"])
        self.assertEqual(failed["browser_action"], "fallback")
        self.assertEqual(failed["browser_rendering"], "unobserved")

    def test_desktop_action_contract_witness(self):
        instructions = (PRODUCT / "workflow/skills/develop-change/references/task-status.md").read_text()
        self.assertIn("selected-flight activation MUST use the exact current candidate", instructions)
        self.assertIn("MUST NOT override selected-flight discovery", instructions)
        helper = load("task_tab")
        old = dict(self.tab(candidate="a" * 64), id="wrong", visible=True)
        current = self.tab()
        observed = {"tabs": [old, current], "can_reveal": True, "can_open": True}
        # The compatibility-only helper would keep the old foreground tab;
        # the documented selected-flight driver must use the exact decision.
        self.assertEqual(helper.decide("second", observed)["action"], "keep")
        exact = helper.discover("second", "b" * 64, observed, 44001)
        actions = [(exact["action"], exact["tab_id"])]
        self.assertEqual(actions, [("reveal", "exact")])

    def test_queued_open_ui_approval_witness(self):
        fixture = self.project(); initial = self.prepared(fixture)
        path, observation, directory = self.observed(fixture, initial)
        endpoint = observation["tabs"][0]
        observation.update(tabs=[], endpoints=[endpoint], activation={"status": "queued", "url": endpoint["url"]})
        path.write_text(json.dumps(observation))
        result = self.prepared(fixture, extra=["--browser-observation", str(path)], expected=0)
        self.assertEqual(result["browser_action"], "requested")
        self.assertEqual(result["browser_visibility"], "unobserved")
        self.assertEqual(result["browser_reachability"], "verified")
        self.assertEqual(result["browser_rendering"], "unobserved")
        self.assertEqual(json.loads((directory / "status.json").read_text())["stages"]["Interactive UI Approval"], "pending")

    def test_ssh_controller_resume_witness(self):
        fixture = self.project(); root, checkout, env = fixture
        self.prepared(fixture)
        binary = root / "bin"; binary.mkdir(); script = binary / "ssh"
        script.write_text("#!" + sys.executable + "\n" + '''import json,os,socket,socketserver,subprocess,sys,threading
from pathlib import Path
a=sys.argv[1:]
with Path(os.environ['SSH_RECORDS']).open('a') as f:f.write(json.dumps({'pid':os.getpid(),'args':a})+'\\n')
if '-N' not in a:
 r=subprocess.run(a[-1],shell=True,capture_output=True,text=True);sys.stdout.write(r.stdout);sys.stderr.write(r.stderr);sys.exit(r.returncode)
_,local,_,remote=a[a.index('-L')+1].split(':')
class Relay(socketserver.BaseRequestHandler):
 def handle(self):
  try:up=socket.create_connection(('127.0.0.1',int(remote)),timeout=2)
  except OSError:return
  def pump(x,y):
   try:
    while True:
     b=x.recv(65536)
     if not b:break
     y.sendall(b)
   except OSError:pass
   finally:
    try:y.shutdown(socket.SHUT_WR)
    except OSError:pass
  t=threading.Thread(target=pump,args=(self.request,up),daemon=True);t.start();pump(up,self.request);t.join(2);up.close()
class Server(socketserver.ThreadingTCPServer):
 allow_reuse_address=True
 daemon_threads=True
with Server(('127.0.0.1',int(local)),Relay) as server:server.serve_forever()
'''); script.chmod(0o755)
        records = root / "ssh.jsonl"
        connector_env = dict(env, PATH=str(binary) + os.pathsep + env.get("PATH", ""), SSH_RECORDS=str(records),
                             FLIGHTCHECK_STATE_DIR=str(root / "browser-state"))
        def stop_owned():
            for path in (root / "browser-state").glob("connections/*/connection.json"):
                row = json.loads(path.read_text()); pid = row.get("supervisor_pid")
                if pid:
                    probe = subprocess.run(["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True)
                    if str(root / "browser-state") in probe.stdout:
                        try: os.kill(pid, signal.SIGTERM)
                        except ProcessLookupError: pass
            if records.exists():
                for line in records.read_text().splitlines():
                    row = json.loads(line)
                    if "-N" in row["args"]:
                        probe = subprocess.run(["ps", "-p", str(row["pid"]), "-o", "args="], capture_output=True, text=True)
                        if str(script) in probe.stdout:
                            try: os.kill(row["pid"], signal.SIGTERM)
                            except ProcessLookupError: pass
        self.addCleanup(stop_owned)
        def free_port():
            with socket.socket() as free:free.bind(("127.0.0.1", 0)); return free.getsockname()[1]
        ports = [free_port() for _ in range(3)]
        def connect(task, number, extra=(), expected=0, project=None):
            command = [sys.executable, "-B", str(checkout / "status-card/connect.py"), "--checkout", str(project or checkout),
                       "--task", task, "--card-dir", "status-card", "--remote-python", sys.executable,
                       "--remote-state-dir", str(root / "state"), "--local-port", str(number), *extra]
            result = subprocess.run(command, cwd=root, env=connector_env, capture_output=True, text=True, timeout=45)
            data = json.loads(result.stdout);self.assertEqual(result.returncode, expected, data);return data
        first = connect("first", ports[0], ["--ssh", "worker-fixture"])
        self.checked(fixture, first)
        stop_owned()
        # A stopped TCP listener does not prove its supervisor has finished
        # attempt-bound rejection and released recovery ownership.
        for lock_path in (root / "browser-state").glob("connections/*/monitor.lock"):
            with lock_path.open("a") as lock:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        self.assertLess(time.monotonic(), deadline, "Previous route owner did not finish teardown")
                        time.sleep(.05)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", ports[0]), timeout=.1):pass
            except OSError:break
            time.sleep(.05)
        resumed = connect("first", ports[1], ["--reconcile-route"])
        self.assertEqual(resumed["task"], "first"); self.assertIn(str(ports[1]), resumed["user_url"])
        self.checked(fixture, resumed)
        second_checkout = root / "second-worker"
        subprocess.run(["git", "worktree", "add", "--detach", str(second_checkout), "HEAD"], cwd=checkout, check=True, capture_output=True)
        (second_checkout / "second-candidate.txt").write_text("Separate flight source\n")
        second_fixture = (root, second_checkout, env)
        self.prepared(second_fixture, task="second", session="controller2")
        second = connect("second", ports[2], project=second_checkout)
        self.assertIn("/task/second/", second["user_url"])
        self.assertIn(str(ports[2]), second["user_url"])
        self.checked(second_fixture, second, task="second", session="controller2")
        wrong_flight = connect("first", free_port(), project=second_checkout, expected=1)
        self.assertIn("checkout", wrong_flight["error"])
        first_directory, = (root / "state").glob("*/tasks/first")
        self.assertEqual(json.loads((first_directory / "status.json").read_text())["candidate"], resumed["candidate"])
        other = root / "other"; shutil.copytree(checkout, other)
        shutil.rmtree(other / ".git"); subprocess.run(["git", "init", "-q"], cwd=other, check=True)
        failed = connect("unintended", free_port(), expected=1, project=other)
        self.assertIn("repository", failed["error"])
        self.assertFalse(list((root / "state").glob("*/tasks/unintended")))

    def tab(self, task="second", candidate="b" * 64, number=44002, **extra):
        return dict(id="exact", url=f"http://localhost:{number}/task/{task}/", visible=False,
                    endpoint_reached=True, snapshot={"snapshot": "live", "task": task,
                    "candidate": candidate, "publicationPort": 44001, "completeness": {"ready": True}}, **extra)

    def test_native_discovery(self):
        tabs = load("task_tab")
        exact = self.tab()
        old = dict(self.tab(candidate="a" * 64), id="old", visible=True)
        other = dict(self.tab(task="first"), id="other", visible=True)
        inventory = {"tabs": [old, other, exact], "can_reveal": True, "can_open": True}
        result = tabs.discover("second", "b" * 64, inventory, 44001)
        self.assertEqual(result["action"], "reveal")
        self.assertEqual(result["tab_id"], "exact")
        self.assertEqual(result["user_url"], exact["url"])
        self.assertEqual(result["browser_reachability"], "verified")
        self.assertEqual(result["browser_rendering"], "unobserved")
        exact["visible"] = True
        exact["rendered_candidate"] = "b" * 64
        self.assertEqual(tabs.discover("second", "b" * 64, inventory, 44001)["action"], "keep")
        self.assertEqual(tabs.discover("second", "b" * 64, inventory, 44001)["browser_rendering"], "verified")
        for changed in (dict(exact, endpoint_reached=False), dict(exact, snapshot={}),
                        dict(exact, url="https://example.com/task/second/"),
                        dict(exact, url="http://user@localhost:44002/task/second/"),
                        dict(exact, url=exact["url"] + "?token=private")):
            with self.subTest(changed=changed):
                result = tabs.discover("second", "b" * 64, dict(inventory, tabs=[changed]), 44001)
                self.assertIsNone(result["user_url"])
                self.assertEqual(result["browser_rendering"], "unobserved")
        duplicate = dict(exact, url="http://127.0.0.1:44003/task/second/")
        self.assertIsNone(tabs.discover("second", "b" * 64, dict(inventory, tabs=[exact, duplicate]), 44001)["user_url"])

    def args(self, **extra):
        values = dict(ssh="worker-alias", checkout="/remote/old-worker", task="first", title=None,
                      card_dir="status-card", remote_python="python3", remote_state_dir="/private/state",
                      details=None, local_port=44002, reconcile_route=False, profile=None)
        values.update(extra)
        return argparse.Namespace(**values)

    def test_connection_reuse(self):
        connector = load("connect")
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, FLIGHTCHECK_STATE_DIR=temporary):
            root = Path(temporary)
            context = {"host": "worker-host", "repository": "/remote/repo/.git", "session": "old-session"}
            connector.remember_profile(self.args(), {"context": context})
            selected = connector.resolve_profile(self.args(ssh=None, checkout="/remote/new-worker", task="second"))
            self.assertEqual(selected.ssh, "worker-alias")
            self.assertEqual(selected.checkout, "/remote/new-worker")
            self.assertEqual(selected.task, "second")
            self.assertEqual(selected.profile_context, {"host": "worker-host", "repository": "/remote/repo/.git"})
            with self.assertRaisesRegex(ValueError, "exact.*checkout"):
                connector.resolve_profile(self.args(ssh=None, checkout=None, task="first"))
            profiles = list((root / "connection-profiles").glob("*.json"))
            self.assertEqual(len(profiles), 1)
            self.assertFalse(profiles[0].stat().st_mode & 0o077)
            self.assertNotIn("user_url", profiles[0].read_text())
            self.assertNotIn("candidate", profiles[0].read_text())
            first_dir = connector.connection_directory(self.args())
            second_dir = connector.connection_directory(selected)
            self.assertNotEqual(first_dir, second_dir)
            remote = {"host_url": "http://127.0.0.1:44001/task/second/", "candidate": "b" * 64,
                      "context": context, "task": "second", "user_url": "http://127.0.0.1:44002/task/second/"}
            with patch.object(connector, "prepare_remote", return_value=remote) as prepare, \
                    patch.object(connector, "identify_remote", return_value=selected.profile_context), \
                    patch.object(connector.maintainer, "current_card", return_value={"task": "second", "candidate": "b" * 64}), \
                    patch.object(connector, "start_forward") as start, patch.object(connector, "available", return_value=True):
                start.return_value.poll.return_value = None
                start.return_value.pid = 12345
                result, process = connector.establish(selected, second_dir)
                self.assertEqual(result["task"], "second")
                self.assertEqual(result["candidate"], "b" * 64)
                self.assertEqual(result["user_url"], remote["user_url"])
                self.assertEqual(start.call_args.args[2:], (44002, 44001))
                again, reused = connector.establish(selected, second_dir)
                self.assertEqual(again["user_url"], result["user_url"])
                self.assertIsNone(reused)
                self.assertEqual(start.call_count, 1)
                # An explicitly reconciled expired forward may move its local
                # port; no saved PID is signalled or borrowed as ownership.
                moved = self.args(**dict(vars(selected), local_port=44003, reconcile_route=True))
                remote["user_url"] = "http://127.0.0.1:44003/task/second/"
                with patch.object(connector.maintainer, "current_card", side_effect=[None, {"task": "second"}, {"task": "second"}]):
                    moved_result, _ = connector.establish(moved, second_dir)
                self.assertEqual(moved_result["user_url"], remote["user_url"])
                self.assertEqual(start.call_args.args[2:], (44003, 44001))
            # A changed host/clone cannot silently consume this saved profile.
            with patch.object(connector, "prepare_remote", return_value=dict(remote, context=dict(context, host="other"))), \
                    patch.object(connector, "identify_remote", return_value=selected.profile_context), \
                    patch.object(connector, "start_forward") as start:
                with self.assertRaisesRegex(ValueError, "another host"):
                    connector.establish(selected, second_dir)
                start.assert_not_called()
            response = argparse.Namespace(returncode=0, stdout=json.dumps(dict(remote, context=dict(context, repository="/other/.git"))))
            with patch.object(connector.subprocess, "run", return_value=response):
                with self.assertRaisesRegex(connector.RouteMismatch, "host or repository changed"):
                    connector.remote_observation(selected)

    def test_safe_fallback(self):
        tabs = load("task_tab")
        for inventory in ({"tabs": None}, {"tabs": []}, {"tabs": [self.tab(candidate="a" * 64)]},
                          {"tabs": [{"url": self.tab()["url"]}], "requested": True}):
            with self.subTest(inventory=inventory):
                result = tabs.discover("second", "b" * 64, inventory, 44001)
                self.assertEqual(result["action"], "fallback")
                self.assertIsNone(result["user_url"])
                self.assertEqual(result["browser_reachability"], "unobserved")
        connector = load("connect")
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, FLIGHTCHECK_STATE_DIR=temporary):
            context = {"host": "host", "repository": "/repo/.git"}
            connector.remember_profile(self.args(), {"context": context})
            connector.remember_profile(self.args(ssh="different-alias"), {"context": context})
            with self.assertRaisesRegex(ValueError, "No unique compatible"):
                connector.resolve_profile(self.args(ssh=None))
            directory = connector.connection_directory(self.args())
            connector.maintainer.write_json(directory / "connection.json", {"local_port": 44002, "remote_port": 44001, "pid": 99999})
            original = (directory / "connection.json").read_bytes()
            remote = {"host_url": "http://127.0.0.1:44001/task/first/", "candidate": "a" * 64}
            with patch.object(connector, "prepare_remote", return_value=remote), \
                    patch.object(connector.maintainer, "current_card", return_value=None), \
                    patch.object(connector, "available", return_value=False), \
                    patch.object(connector, "start_forward") as start:
                with self.assertRaisesRegex(ValueError, "occupied or serves the wrong"):
                    connector.establish(self.args(), directory)
                start.assert_not_called()
                self.assertEqual((directory / "connection.json").read_bytes(), original)

    def test_activation_integration(self):
        reply = load("reply")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observation = root / "browser.json"
            context = {"host": "worker", "repository": "/repo/.git", "session": "session"}
            value = {"schema": 1, "context": context, "observed_at": time.time(), "tabs": [self.tab()]}
            observation.write_text(json.dumps(value)); observation.chmod(0o600)
            self.assertEqual(reply.browser_observation(observation, context), value)
            for changed in (dict(value, observed_at=0), dict(value, context=dict(context, session="other"))):
                observation.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "stale or belongs"):
                    reply.browser_observation(observation, context)
            observation.write_text(json.dumps(value)); observation.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                reply.browser_observation(observation, context)
            url = "http://localhost:44002/task/second/"
            record = reply.route_record({}, "second", "http://127.0.0.1:44001/task/second/", "remote", url, context)
            publication = {"completeness": {"ready": True}}
            result = reply.observation(record, "b" * 64, publication)
            self.assertEqual(result["publication"], "verified")
            self.assertEqual(result["browser_rendering"], "unobserved")
            self.assertNotIn("approval", result)
            with self.assertRaisesRegex(ValueError, "already has a browser URL"):
                reply.route_record(record, "second", record["host_url"], "remote", "http://localhost:44003/task/second/", context)
            moved = reply.route_record(record, "second", record["host_url"], "remote", "http://localhost:44003/task/second/", context, True)
            self.assertIn(":44003/", moved["user_url"])
            unverified = dict(record, route_unverified=True)
            result = reply.observation(unverified, "b" * 64, publication)
            self.assertNotIn("http", result["footer"])
            retained = reply.route_record(unverified, "second", record["host_url"], "remote", None, context)
            self.assertTrue(retained["route_unverified"])
            changed_session = reply.route_record(record, "second", record["host_url"], "remote", None, dict(context, session="new"))
            self.assertEqual(changed_session["user_url"], url)
            self.assertTrue(changed_session["route_unverified"])
            self.assertEqual(changed_session["context"], context)
        # Public entry point: synthetic browser observations must affect the
        # real publisher and remain distinct from its unchanged UI-approval stage.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); checkout = root / "project"; checkout.mkdir()
            shutil.copytree(CARD, checkout / "status-card")
            env = dict(os.environ, FLIGHTCHECK_STATE_DIR=str(root / "state"))
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
            subprocess.run(["git", "add", "."], cwd=checkout, check=True)
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture"], cwd=checkout, check=True)
            current = reply.maintainer.candidate(checkout)
            names = ["Plan", "Implement", "Cheap Tests", "Interactive UI Approval", "Independent Code Review",
                     "Authoritative Gates", "Skeptical Evidence Review", "Final Verdict", "PR & Merge"]
            details = {"stages": {name: "current" if name == "Plan" else "pending" for name in names},
                       "check_plan": [], "checks_unavailable": "Synthetic route fixture.", "checks": [],
                       "links_unavailable": {"issue": "Synthetic fixture.", "pr": "No delivery."}}
            detail = root / "details.json"; detail.write_text(json.dumps(details))
            command = [sys.executable, "-B", "status-card/reply.py", "prepare", "--task", "second", "--session", "fixture", "--execution", "remote", "--details", str(detail)]
            def run(extra=()):
                result = subprocess.run(command + list(extra), cwd=checkout, env=env, capture_output=True, text=True, timeout=20)
                return result.returncode, json.loads(result.stdout)
            code, initial = run(); self.assertEqual(code, 1)
            directory, = (root / "state").glob("*/tasks/second")
            try:
                number = json.loads((directory / "endpoint.json").read_text())["port"]
                snapshot = reply.maintainer.current_card("second", number, current)
                tab = dict(self.tab(), snapshot=snapshot)
                observed = {"schema": 1, "context": initial["context"], "observed_at": time.time(),
                            "tabs": [tab], "can_reveal": True, "can_open": True}
                observation = root / "observed.json"; observation.write_text(json.dumps(observed)); observation.chmod(0o600)
                code, prepared = run(["--browser-observation", str(observation)])
                self.assertEqual(code, 0, prepared)
                self.assertEqual(prepared["candidate"], current)
                self.assertEqual(prepared["browser_action"], "reveal")
                self.assertEqual(prepared["browser_reachability"], "verified")
                self.assertEqual(prepared["browser_rendering"], "unobserved")
                self.assertEqual(json.loads((directory / "status.json").read_text())["stages"]["Interactive UI Approval"], "pending")
                draft = root / "reply.txt"; draft.write_text(prepared["footer"])
                checked = subprocess.run([sys.executable, "-B", "status-card/reply.py", "check", "--task", "second", "--execution", "remote",
                                          "--session", "another-session", "--reply-file", str(draft)], cwd=checkout, env=env, capture_output=True, text=True)
                self.assertEqual(checked.returncode, 1)
                self.assertNotIn("http", json.loads(checked.stdout)["footer"])
            finally:
                for name, key in (("endpoint.json", "pid"), ("monitor.json", "pid")):
                    path = directory / name
                    if path.exists() and json.loads(path.read_text()).get(key):
                        try: os.kill(json.loads(path.read_text())[key], signal.SIGTERM)
                        except ProcessLookupError: pass


if __name__ == "__main__":
    unittest.main()
