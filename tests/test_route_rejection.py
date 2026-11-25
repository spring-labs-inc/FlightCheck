"""Observe rejected connector attempts through real disposable transport and worker state."""

import json
import contextlib
import io
import os
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_card_startup as startup
import test_route_discovery as fixture


class RouteRejectionTests(unittest.TestCase):
    project = fixture.RouteDiscoveryTests.project
    prepared = fixture.RouteDiscoveryTests.prepared
    observed = fixture.RouteDiscoveryTests.observed
    checked = fixture.RouteDiscoveryTests.checked
    tab = fixture.RouteDiscoveryTests.tab
    args = fixture.RouteDiscoveryTests.args
    fake_ssh = startup.StartupTests.fake_ssh
    stop_forwarders = startup.StartupTests.stop_forwarders

    def test_malformed_inventory_fallback_witness(self):
        tabs = fixture.load("task_tab")
        endpoint = self.tab()
        for malformed in ({}, {"url": []}, {"url": {}}, {"url": "http://["}):
            with self.subTest(malformed=malformed):
                result = tabs.discover("second", "b" * 64,
                                       {"tabs": [malformed], "endpoints": [endpoint], "can_open": True}, 44001)
                self.assertEqual(result["action"], "fallback")
                self.assertEqual(result["browser_visibility"], "unobserved")
                self.assertEqual(result["browser_rendering"], "unobserved")

    def test_post_confirmation_persistence_failure_witness(self):
        for target, prior, reject_unavailable in (("connection", False, False), ("profile", False, False),
                                                  ("connection", True, False), ("profile", True, False),
                                                  ("supervisor", False, False), ("supervisor", True, False),
                                                  ("profile", False, True)):
            with self.subTest(target=target, prior=prior, reject_unavailable=reject_unavailable):
                case = self.project(); self.root, self.checkout, self.env = case
                self.env.update(CODEX_THREAD_ID="controller", SSH_CONNECTION="synthetic-worker")
                def hook(kind, message=""):
                    return json.loads(subprocess.check_output(
                        [sys.executable, "-B", "status-card/maintainer.py", "hook"],
                        input=json.dumps({"hook_event_name": kind, "cwd": str(self.checkout),
                                          "session_id": "controller", "turn_id": "persistence",
                                          "last_assistant_message": message}),
                        cwd=self.checkout, env=self.env, text=True, timeout=20))
                self.assertEqual(hook("UserPromptSubmit"), {})
                initial = self.prepared(case)
                path, _, directory = self.observed(case, initial)
                if prior:
                    initial = self.prepared(case, extra=["--browser-observation", str(path)], expected=0)
                before = json.loads((directory / "reply-route.json").read_text())
                self.fake_ssh()
                with socket.socket() as free:
                    free.bind(("127.0.0.1", 0)); local_port = free.getsockname()[1]
                connector = fixture.load("connect")
                args = self.args(checkout=str(self.checkout), remote_state_dir=str(self.root / "state"),
                                 remote_python=sys.executable, local_port=local_port, reconcile_route=True)
                real_write = connector.maintainer.write_json
                real_start = connector.start_forward; real_reject = getattr(connector, "reject_remote", None)
                children = []; adoption = []
                def start(*values):
                    child = real_start(*values); children.append(child)
                    self.addCleanup(connector.stop_child, child)
                    return child
                def write(path, value):
                    matches = (path.name == "connection.json" if target == "connection" else
                               path.name == "connection.json" and value.get("supervisor_pid") == os.getpid()
                               if target == "supervisor" else path.parent.name == "connection-profiles")
                    if matches:
                        adopted = json.loads((directory / "reply-route.json").read_text())
                        self.assertEqual(adopted["route_verification"]["source"], "connector")
                        self.assertEqual(adopted["user_url"], connector.maintainer.card_url("first", local_port))
                        self.assertIsNotNone(connector.maintainer.current_card(
                            "first", local_port, initial["candidate"], json.loads((directory / "endpoint.json").read_text())["port"]))
                        adoption.append(adopted)
                        raise OSError("Injected local " + target + " persistence failure")
                    return real_write(path, value)
                with patch.dict(os.environ, self.connector_env), patch.object(connector, "start_forward", side_effect=start), \
                        patch.object(connector.maintainer, "write_json", side_effect=write):
                    connection = connector.connection_directory(args)
                    if reject_unavailable:
                        # The original lacks rejection: it must still fail the
                        # earlier observable rollback assertions in its controls.
                        self.assertIsNotNone(real_reject)
                        with patch.object(connector, "reject_remote", side_effect=ValueError("Worker access unavailable")):
                            with self.assertRaises(connector.RetainedForward) as retained:
                                connector.establish(args, connection)
                        self.assertIn(str(children[0].pid), str(retained.exception))
                        self.assertIsNone(children[0].poll())
                        self.assertTrue(connector.release_forward(args, children[0]))
                    elif target == "supervisor":
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            self.assertEqual(connector.supervise(args), 1)
                        self.assertNotIn("http", json.loads(output.getvalue())["footer"])
                    else:
                        with self.assertRaisesRegex(OSError, "Injected local"):
                            connector.establish(args, connection)
                self.assertEqual(len(children), 1); self.assertEqual(len(adoption), 1)
                self.assertIsNotNone(children[0].poll())
                after = json.loads((directory / "reply-route.json").read_text())
                self.assertEqual(after.get("route_verification"), before.get("route_verification"))
                rejected = "FlightCheck: [&lt; status /&gt;](" + connector.maintainer.card_url("first", local_port) + ")"
                resumed = self.prepared(case, expected=0 if prior else 1)
                self.checked(case, dict(resumed, footer=rejected), expected=1)
                self.assertEqual(hook("Stop", rejected).get("decision"), "block")
                if prior:
                    self.checked(case, initial)
                    self.assertEqual(hook("Stop", initial["footer"]), {})
                else:
                    self.assertNotIn("http", resumed["footer"])
                if real_reject:
                    with patch.dict(os.environ, self.connector_env):
                        real_reject(args, args.connection_confirmation)
                    self.assertEqual(json.loads((directory / "reply-route.json").read_text()), after)

    def test_healthy_monitor_renews_only_observed_connector_route(self):
        for fresh in (True, False):
            with self.subTest(fresh=fresh):
                case = self.project(); self.root, self.checkout, self.env = case
                initial = self.prepared(case)
                self.fake_ssh()
                with socket.socket() as free:
                    free.bind(("127.0.0.1", 0)); local_port = free.getsockname()[1]
                connector = fixture.load("connect")
                args = self.args(checkout=str(self.checkout), remote_state_dir=str(self.root / "state"),
                                 remote_python=sys.executable, local_port=local_port)
                with patch.dict(os.environ, self.connector_env):
                    connection = connector.connection_directory(args)
                    adopted, child = connector.establish(args, connection)
                    self.addCleanup(connector.stop_child, child)
                    directory, = (self.root / "state").glob("*/tasks/first")
                    record = json.loads((directory / "reply-route.json").read_text())
                    record["route_verification"]["observed_at"] -= 31
                    (directory / "reply-route.json").write_text(json.dumps(record))
                    self.prepared(case)  # Worker publication cannot renew it.
                    self.checked(case, adopted, expected=1)
                    worker_lease = (directory / "monitor.json").read_bytes()
                    tick = [0]
                    def advance(duration):
                        tick[0] += duration
                    current_card = connector.maintainer.current_card
                    with patch.object(connector.maintainer, "current_card", side_effect=current_card if fresh else lambda *a, **k: None):
                        # Borrow the already-owned test forward: this monitor
                        # must never gain a process handle or stop it by PID.
                        connector.monitor(args, connection, adopted, None, interval=40, lifetime=41,
                                          clock=lambda: tick[0], sleep=advance)
                    self.assertGreaterEqual(tick[0], 40)
                    self.assertEqual((directory / "monitor.json").read_bytes(), worker_lease)
                    after = json.loads((directory / "reply-route.json").read_text())
                    if fresh:
                        self.assertGreater(after["route_verification"]["observed_at"], record["route_verification"]["observed_at"])
                        self.checked(case, adopted)
                    else:
                        self.assertEqual(after["route_verification"], record["route_verification"])
                        self.checked(case, adopted, expected=1)
                    self.prepared(case, expected=0 if fresh else 1)
                    if hasattr(connector, "release_forward"):
                        self.assertTrue(connector.release_forward(args, child))
                    else:
                        connector.stop_child(child)


if __name__ == "__main__":
    unittest.main()
