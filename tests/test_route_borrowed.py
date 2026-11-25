"""Public duplicate connector invocations retain the actual monitor's route identity."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import unittest

import test_card_startup as startup
import test_route_discovery as fixture


class BorrowedMonitorTests(unittest.TestCase):
    project = fixture.RouteDiscoveryTests.project
    prepared = fixture.RouteDiscoveryTests.prepared
    checked = fixture.RouteDiscoveryTests.checked
    fake_ssh = startup.StartupTests.fake_ssh
    stop_forwarders = startup.StartupTests.stop_forwarders

    def test_existing_monitor_borrowed_forward_witness(self):
        case = self.project(); self.root, self.checkout, self.env = case
        self.env.update(CODEX_THREAD_ID="controller", SSH_CONNECTION="synthetic-worker")
        def hook(kind, message=""):
            return json.loads(subprocess.check_output(
                [sys.executable, "-B", "status-card/maintainer.py", "hook"],
                input=json.dumps({"hook_event_name": kind, "cwd": str(self.checkout), "session_id": "controller",
                                  "turn_id": "borrowed-monitor", "last_assistant_message": message}),
                cwd=self.checkout, env=self.env, text=True, timeout=20))
        self.assertEqual(hook("UserPromptSubmit"), {})
        self.prepared(case)
        self.fake_ssh()
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0)); local_port = free.getsockname()[1]
        command = [sys.executable, "-B", str(self.checkout / "status-card/connect.py"), "--ssh", "worker-fixture",
                   "--checkout", str(self.checkout), "--card-dir", "status-card", "--remote-python", sys.executable,
                   "--remote-state-dir", str(self.root / "state"), "--task", "first", "--local-port", str(local_port)]
        def connect():
            result = subprocess.run(command, cwd=self.root, env=self.connector_env, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        first = connect(); self.assertEqual(first["monitor"], "active")
        directory, = (self.root / "state").glob("*/tasks/first")
        original = json.loads((directory / "reply-route.json").read_text())
        connection_path, = (self.root / "connector-state").glob("connections/*/connection.json")
        owner_pid = json.loads(connection_path.read_text())["supervisor_pid"]
        def native_adopt(published):
            reply = fixture.load("reply")
            publication_port = json.loads((directory / "endpoint.json").read_text())["port"]
            snapshot = reply.maintainer.current_card("first", local_port, published["candidate"], publication_port)
            self.assertIsNotNone(snapshot)
            observation = self.root / "native.json"
            observation.write_text(json.dumps({"schema": 1, "context": published["context"], "observed_at": time.time(),
                                               "can_open": True, "tabs": [{"id": "native-owned-forward", "visible": True,
                                               "url": first["user_url"], "endpoint_reached": True, "snapshot": snapshot}]}))
            observation.chmod(0o600)
            return self.prepared(case, extra=["--browser-observation", str(observation)], expected=0)
        (self.checkout / "next-candidate.txt").write_text("Candidate advances while the original monitor stays live\n")
        native_adopt(self.prepared(case))
        native_record = json.loads((directory / "reply-route.json").read_text())
        with self.subTest(boundary="native-transport-dependency"):
            self.assertEqual(native_record.get("connection_owner", {}).get("attempt"), original["route_verification"]["attempt"])
        second = connect(); self.assertEqual(second["monitor"], "existing")
        self.assertNotEqual(second["candidate"], first["candidate"])
        self.assertEqual(json.loads(connection_path.read_text())["supervisor_pid"], owner_pid)
        borrowed = json.loads((directory / "reply-route.json").read_text())
        forwards = [json.loads(line) for line in self.records.read_text().splitlines() if "-N" in json.loads(line)["args"]]
        self.assertEqual(len(forwards), 1)
        with self.subTest(boundary="live-owner-identity"):
            self.assertEqual(borrowed["route_verification"]["attempt"], original["route_verification"]["attempt"])
        borrowed["route_verification"]["observed_at"] -= 31
        (directory / "reply-route.json").write_text(json.dumps(borrowed))
        lease = (directory / "monitor.json").read_bytes()
        with self.subTest(boundary="healthy-owner-renewal"):
            self.checked(case, second, expected=1)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                renewed = json.loads((directory / "reply-route.json").read_text())
                if renewed["route_verification"]["observed_at"] > borrowed["route_verification"]["observed_at"]:
                    break
                time.sleep(.1)
            self.assertGreater(renewed["route_verification"]["observed_at"], borrowed["route_verification"]["observed_at"])
            self.assertEqual((directory / "monitor.json").read_bytes(), lease)
            self.checked(case, second)
        # Independently reach teardown with a fresh proof, even in the original
        # product where the preceding renewal assertion is a real failure.
        fresh = json.loads((directory / "reply-route.json").read_text())
        fresh["route_verification"]["observed_at"] = time.time()
        (directory / "reply-route.json").write_text(json.dumps(fresh))
        self.checked(case, second)
        # Hold the actual owner while adopting a fresh native observation of
        # this exact forward, then exercise its real signal/finally teardown.
        def resume_owner():
            try:
                os.kill(owner_pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        self.addCleanup(resume_owner)
        os.kill(owner_pid, signal.SIGSTOP)
        try:
            native = native_adopt(self.prepared(case, expected=0))
            self.checked(case, native)
            self.assertEqual(hook("Stop", native["footer"]), {})
            os.kill(owner_pid, signal.SIGTERM)
        finally:
            resume_owner()
        startup.StartupTests.stop_monitors(self)
        with self.subTest(boundary="owning-supervisor-teardown"):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", local_port), timeout=.1):
                        pass
                except OSError:
                    break
                time.sleep(.05)
            else:
                self.fail("The fixture's owning supervisor did not stop its forward")
            self.checked(case, second, expected=1)
            self.assertEqual(hook("Stop", second["footer"]).get("decision"), "block")
            self.prepared(case, expected=1)


if __name__ == "__main__":
    unittest.main()
