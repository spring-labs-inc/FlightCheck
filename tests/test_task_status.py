"""Verify the publisher, task-specific HTTP routes, and pilot isolation."""

import json
import subprocess
import sys
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

CARD = Path(__file__).resolve().parents[1] / "status-card"


class TaskStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.snapshot = Path(temp.name) / "status.json"

    def publish(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(CARD / "task_status.py"),
             "--file", str(self.snapshot), "--task", "test-task", "--title", "Synthetic task", *args],
            check=True, text=True, capture_output=True, timeout=5,
        ).stdout.strip()

    def start(self, *args):
        process = subprocess.Popen(
            [sys.executable, "-B", str(CARD / "serve.py"), "--port", "0", *args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.addCleanup(process.stdout.close)

        def stop():
            process.terminate()
            process.wait(timeout=5)

        self.addCleanup(stop)
        startup = process.stdout.readline()
        self.assertTrue(startup.startswith("SpringDev status card at http://127.0.0.1:"), startup)
        return startup.split()[-1]

    def request(self, url, method="GET"):
        target = urlsplit(url)
        connection = HTTPConnection(target.hostname, target.port, timeout=5)
        try:
            connection.request(method, target.path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_stable_task_route_publishes_only_current_verdict(self):
        self.assertEqual(self.publish(), "")
        url = self.start("--task-status", str(self.snapshot))
        self.assertTrue(url.endswith("/task/test-task/"))
        self.assertEqual(self.request(url)[0], 200)
        status_url = url + "status.json"

        def current():
            status, body = self.request(status_url)
            self.assertEqual(status, 200)
            return json.loads(body)

        status_line = f"SpringDev: [&lt; status /&gt;]({url})"
        self.assertEqual(self.publish("--url", url, "--chat-phase", "start"), status_line)
        self.assertEqual(current()["verdict"], "Pending")
        candidate = ("--candidate", "first", "--verdict", "APPROVE_WITH_NITS",
                     "--verdict-candidate", "first", "--url", url)
        self.assertEqual(self.publish(*candidate), "")
        self.assertEqual(current()["verdict"], "APPROVE_WITH_NITS")
        self.assertEqual(
            self.publish(*candidate, "--chat-phase", "end"),
            f"{status_line}\n\nVerdict: APPROVE_WITH_NITS",
        )
        self.assertEqual(
            self.publish("--candidate", "second", "--verdict", "APPROVE_WITH_NITS",
                         "--verdict-candidate", "first", "--url", url, "--chat-phase", "end"),
            status_line,
        )
        self.assertEqual(current()["candidate"], "second")
        self.assertIsNone(current()["verdict_candidate"])
        self.assertEqual(current()["verdict"], "Pending")
        self.assertEqual(self.request(status_url, "POST")[0], 405)
        self.assertEqual(self.request(url.replace("test-task", "other-task"))[0], 404)
        self.snapshot.unlink()
        self.assertEqual(self.request(status_url)[0], 503)

    def test_default_listener_serves_only_the_historical_pilot(self):
        url = self.start()
        status, body = self.request(url + "status.json")
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot["snapshot"], "historical")
        self.assertEqual(snapshot["reviews"]["evidence"], "APPROVE_WITH_NITS")
        self.assertEqual(len(snapshot["gates"]), 8)
        self.assertEqual(self.request(url + "task/test-task/")[0], 404)

    def test_desktop_tab_decisions_use_the_task_route(self):
        visible = {"id": "card", "url": "http://localhost:58213/task/test-task/", "visible": True}
        hidden = {**visible, "visible": False}
        unknown = {key: value for key, value in visible.items() if key != "visible"}
        other = {"id": "other", "url": "http://127.0.0.1:8767/task/other-task/", "visible": True}
        unrelated = {"id": "site", "url": "https://example.com/task/test-task/", "visible": True}
        fallback = {"action": "fallback"}
        cases = [
            ([visible, other], True, True, {"action": "keep"}),
            ([hidden, other], True, True, {"action": "reveal", "tab_id": "card"}),
            ([hidden, visible], True, True, {"action": "keep"}),
            ([unrelated, other], True, True, {"action": "open"}),
            ([hidden, other], False, True, fallback),
            ([unknown, other], True, True, fallback),
            ([{"id": "loading"}, other], True, True, fallback),
            ([other], True, False, fallback),
            (None, True, True, fallback),
        ]
        for tabs, can_reveal, can_open, expected in cases:
            with self.subTest(tabs=tabs, can_reveal=can_reveal, can_open=can_open):
                result = subprocess.run(
                    [sys.executable, "-B", str(CARD / "task_tab.py"), "--task", "test-task"],
                    input=json.dumps({"tabs": tabs, "can_reveal": can_reveal, "can_open": can_open}),
                    check=True, text=True, capture_output=True, timeout=5,
                )
                self.assertEqual(json.loads(result.stdout), expected)


if __name__ == "__main__":
    unittest.main()
