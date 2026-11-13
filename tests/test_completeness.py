"""Exercise active-flight readiness through real CLI/HTTP and the browser script.

All data is synthetic. Node executes task.js's DOM/polling contract; this is not
an interactive browser render or native Claude qualification.
"""

import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import unittest
from http.client import HTTPConnection
from urllib.parse import urlsplit

from card_fixture import complete
import test_reply


class CompletenessTests(unittest.TestCase):
    setUp = test_reply.ReplyTests.setUp
    git = test_reply.ReplyTests.git
    stop_listeners = test_reply.ReplyTests.stop_listeners
    directory = test_reply.ReplyTests.directory
    snapshot = test_reply.ReplyTests.snapshot
    endpoint = test_reply.ReplyTests.endpoint
    wait_stopped = test_reply.ReplyTests.wait_stopped

    def api(self, command, *args, expected=0):
        result = subprocess.run([sys.executable, "-B", str(self.checkout / "status-card/reply.py"), command,
                                 "--task", "test-change", "--execution", "local", *args],
                                cwd=self.checkout, env=self.env, capture_output=True, text=True, timeout=20)
        for path in self.state.glob("*/tasks/*/endpoint.json"):
            self.listeners.add(json.loads(path.read_text())["pid"])
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def details(self, candidate=None, stage="Plan", **updates):
        if candidate is None:
            code = "import sys;from pathlib import Path;sys.path.insert(0,'status-card');import maintainer;print(maintainer.candidate(Path('.')))"
            candidate = subprocess.check_output([sys.executable, "-B", "-c", code], cwd=self.checkout,
                                                env=self.env, text=True).strip()
        value = complete(candidate, stage)
        value.update(updates)
        path = self.root / "details.json"
        path.write_text(json.dumps(value))
        return path

    def request(self, path="status.json", headers=None, target=None, method="GET"):
        port = self.endpoint()["port"]
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.putrequest(method, target or "/task/test-change/" + path, skip_host=True)
            for name, value in headers if headers is not None else [("Host", f"127.0.0.1:{port}")]:
                connection.putheader(name, value)
            connection.endheaders()
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_active_publication_requires_complete_status(self):
        incomplete = self.api("prepare", "--title", "Title only", expected=1)
        self.assertEqual(incomplete["status"], "incomplete")
        self.assertEqual(incomplete["publication"], "verified")
        self.assertFalse(incomplete["completeness"]["ready"])
        self.assertIn("check_plan", incomplete["guidance"])
        status, body, _ = self.request()
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["completeness"], incomplete["completeness"])
        full = self.details()
        ready = self.api("prepare", "--details", str(full))
        self.assertEqual(ready["footer"], incomplete["footer"])
        snapshot = self.snapshot()
        self.assertEqual(snapshot["verdict"], "Pending")
        self.assertEqual(len(snapshot["stages"]), 9)
        self.assertEqual(snapshot["checks"][0]["state"], "pending")
        self.assertEqual(snapshot["checks"][0]["counts"], {})
        self.assertEqual(self.request()[0], 200)
        # Private-file damage and forged ready flags cannot bypass normalization.
        good = (self.directory() / "status.json").read_bytes()
        variants = [{"stages": {}}, {"stages": {"Plan": "current"}}, {"check_plan": []},
                    {"checks": []}, {"links_unavailable": {}},
                    {"stages": {name: "pending" for name in snapshot["stages"]}},
                    {"checks": [{**snapshot["checks"][0], "state": "unavailable"}]},
                    {"links": [{"kind": "pr", "label": "PR", "url": "https://example.com/pr/1"}]}]
        for update in variants:
            with self.subTest(update=update):
                damaged = {**snapshot, **update, "completeness": {"ready": True}}
                damaged.pop("stages_declared", None)
                (self.directory() / "status.json").write_text(json.dumps(damaged))
                self.assertEqual(self.request()[0], 503)
        (self.directory() / "status.json").write_bytes(good)
        no_checks = self.details(check_plan=[], checks=[], checks_unavailable="No automated checks apply to this observation.")
        self.assertEqual(self.api("prepare", "--details", str(no_checks))["status"], "published")

    def test_check_plan_can_leave_unavailable_state(self):
        first = self.api("prepare", "--details", str(self.details(
            check_plan=[], checks=[], checks_unavailable="No checks apply yet.")))
        for changed in (False, True):
            with self.subTest(candidate_changed=changed):
                if changed:
                    self.api("prepare", "--details", str(self.details(
                        check_plan=[], checks=[], checks_unavailable="No checks apply yet.")))
                    self.readme.write_text("Candidate with newly applicable checks\n")
                    endpoint = self.endpoint()
                    os.kill(endpoint["pid"], signal.SIGTERM)
                    self.wait_stopped(endpoint["port"])
                result = self.api("prepare", "--details", str(self.details()))
                self.assertEqual(result["footer"], first["footer"])
                self.assertEqual(result["status"], "published")
                self.assertNotIn("checks_unavailable", self.snapshot())
                self.assertEqual(self.snapshot()["checks"][0]["state"], "pending")
                self.assertEqual(self.snapshot()["verdict"], "Pending")

    def test_removed_stage_cannot_reuse_declaration(self):
        self.api("prepare", "--details", str(self.details()))
        snapshot = self.snapshot()
        snapshot["stages"].pop("PR & Merge")
        # Retained declaration metadata must not hide an actually missing stage.
        (self.directory() / "status.json").write_text(json.dumps(snapshot))
        self.assertEqual(self.request()[0], 503)

    def test_candidate_repair_and_restart_never_restore_stale_results(self):
        path = self.details(stage="Final Verdict")
        first = self.api("prepare", "--details", str(path))
        self.api("prepare", "--verdict", "APPROVE", "--verdict-candidate", first["candidate"])
        self.assertEqual(self.snapshot()["verdict"], "APPROVE")
        details = json.loads(path.read_text())
        details["checks"][0].update(state="failed", counts={"failed": 1})
        path.write_text(json.dumps(details))
        self.api("prepare", "--details", str(path))
        self.assertEqual(self.snapshot()["verdict"], "Pending")
        self.assertEqual(self.snapshot()["checks"][0]["state"], "failed")
        endpoint = self.endpoint()
        os.kill(endpoint["pid"], signal.SIGTERM)
        self.wait_stopped(endpoint["port"])
        self.assertEqual(self.api("prepare")["footer"], first["footer"])
        self.assertEqual(self.snapshot()["verdict"], "Pending")
        self.assertEqual(self.snapshot()["checks"][0]["state"], "failed")
        self.readme.write_text("Edited candidate\n")
        self.assertEqual(self.api("prepare", expected=1)["status"], "incomplete")
        stale = self.snapshot()
        self.assertNotEqual(stale["candidate"], first["candidate"])
        self.assertTrue(stale["checks"][0]["stale"])
        self.assertEqual(stale["verdict"], "Pending")
        self.assertNotIn("stages", stale)
        self.api("prepare", "--details", str(self.details(stage="Implement")))
        self.assertEqual(self.snapshot()["checks"][0]["state"], "pending")
        self.assertEqual(self.snapshot()["verdict"], "Pending")
        self.assertEqual(self.request()[0], 200)

    def test_reply_and_native_stop_require_complete_snapshot(self):
        self.env["CODEX_THREAD_ID"] = "completeness-controller"
        def hook(event, reply=""):
            payload = {"hook_event_name": event, "cwd": str(self.checkout), "session_id": self.env["CODEX_THREAD_ID"],
                       "turn_id": "same-turn", "last_assistant_message": reply}
            return json.loads(subprocess.check_output([sys.executable, "-B", "status-card/maintainer.py", "hook"],
                              input=json.dumps(payload), cwd=self.checkout, env=self.env, text=True, timeout=10))
        self.assertEqual(hook("UserPromptSubmit"), {})
        incomplete = self.api("prepare", expected=1)
        self.draft.write_text("Update.\n\n" + incomplete["footer"])
        result = self.api("check", "--reply-file", str(self.draft), expected=1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(hook("Stop", self.draft.read_text())["decision"], "block")
        self.assertIn("complete --details", hook("Stop", self.draft.read_text())["reason"])
        ready = self.api("prepare", "--details", str(self.details()))
        self.assertEqual(ready["footer"], incomplete["footer"])
        self.assertEqual(self.api("check", "--reply-file", str(self.draft))["status"], "published")
        self.assertEqual(hook("Stop", self.draft.read_text()), {})
        self.assertEqual(ready["completeness"], self.snapshot()["completeness"])
        self.assertEqual(ready["browser_rendering"], "unobserved")

    def test_host_and_origin_policy_preserves_loopback_forwarding(self):
        self.api("prepare", "--details", str(self.details()))
        for target in ("/task/test-change/status.json", "/task/test-change/", "/task.js", "/card.css"):
            for host in ("127.0.0.1:31337", "localhost:31337", "[::1]:31337", "localhost"):
                status, _, headers = self.request(target=target, headers=[("Host", host), ("Origin", "http://localhost:31337")])
                self.assertEqual(status, 200, (target, host))
                self.assertNotIn("Access-Control-Allow-Origin", headers)
            for headers in ([], [("Host", "foreign.example")], [("Host", "user@localhost")],
                            [("Host", "localhost:0")], [("Host", "localhost:bad")],
                            [("Host", "localhost:99999")], [("Host", "localhost/ignored")],
                            [("Host", "localhost"), ("Host", "127.0.0.1")],
                            [("Host", "foreign.example"), ("X-Forwarded-Host", "localhost")],
                            [("Host", "localhost"), ("Origin", "http://foreign.example")],
                            [("Host", "localhost"), ("Origin", "null")],
                            [("Host", "localhost"), ("Origin", "http://localhost/")],
                            [("Host", "localhost"), ("Origin", "http://localhost"), ("Origin", "http://localhost")]):
                with self.subTest(target=target, headers=headers):
                    status, body, response_headers = self.request(target=target, headers=headers)
                    self.assertEqual(status, 403)
                    self.assertNotIn(b'"candidate"', body)
                    self.assertNotIn("Access-Control-Allow-Origin", response_headers)
        for target in ("http://localhost/task/test-change/status.json", "//localhost/task/test-change/status.json"):
            self.assertEqual(self.request(target=target)[0], 403)
        self.assertEqual(self.request(method="HEAD")[1], b"")
        self.assertEqual(self.request(method="POST")[0], 405)
        self.assertEqual(self.request(target="/private/status.json")[0], 404)

    def test_browser_polling_renders_completeness_and_stale_states(self):
        self.api("prepare", "--details", str(self.details()))
        accepted = json.loads(self.request()[1])
        saved = (self.directory() / "status.json").read_bytes()
        damaged = self.snapshot()
        damaged.pop("checks")
        (self.directory() / "status.json").write_text(json.dumps(damaged))
        status, body, _ = self.request()
        self.assertEqual(status, 503)
        (self.directory() / "status.json").write_bytes(saved)
        minimal = self.low_level()
        variants = [{"ok": True, "data": accepted}, {"ok": False, "data": json.loads(body)},
                    {"ok": True, "data": minimal}, {"ok": True, "data": {**accepted, "task": "wrong"}},
                    {"disconnect": True}, {"ok": True, "data": {**accepted, "candidate": "other",
                     "checks": [{**accepted["checks"][0], "stale": True}], "verdict": "APPROVE",
                     "verdict_candidate": accepted["candidate"]}}]
        fixture = self.root / "browser-input.json"
        fixture.write_text(json.dumps(variants))
        node = os.environ.get("FLIGHTCHECK_NODE") or shutil.which("node")
        if not node:
            self.skipTest("Node is required for the actual task.js DOM/polling contract")
        result = subprocess.run([node, str(Path(__file__).with_name("card_dom.cjs")),
                                 str(self.checkout / "status-card/task.js"), str(fixture)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["observations"], 6)

    def low_level(self):
        snapshot = self.root / "minimal.json"
        subprocess.run([sys.executable, "-B", "status-card/task_status.py", "--file", str(snapshot),
                        "--task", "test-change", "--title", "Minimal fixture", "--candidate", "synthetic",
                        "--verdict", "APPROVE", "--verdict-candidate", "synthetic"],
                       cwd=self.checkout, env=self.env, check=True, capture_output=True, text=True)
        return json.loads(snapshot.read_text())

    def test_low_level_minimal_mode_is_explicit_and_not_flight_ready(self):
        snapshot = self.low_level()
        self.assertEqual(snapshot["snapshot"], "minimal")
        self.assertEqual(snapshot["mode"], "minimal")
        self.assertEqual(snapshot["completeness"]["state"], "minimal")
        self.assertFalse(snapshot["completeness"]["ready"])
        self.assertEqual(snapshot["verdict"], "Pending")
        self.assertNotIn("checks", snapshot)
        process = subprocess.Popen([sys.executable, "-B", "status-card/serve.py", "--port", "0",
                                    "--task-status", str(self.root / "minimal.json")], cwd=self.checkout,
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            route = urlsplit(process.stdout.readline().split()[-1])
            connection = HTTPConnection(route.hostname, route.port, timeout=3)
            try:
                connection.request("GET", route.path + "status.json")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["snapshot"], "minimal")
            finally:
                connection.close()
        finally:
            process.terminate()
            process.wait(timeout=3)
            process.stdout.close()
