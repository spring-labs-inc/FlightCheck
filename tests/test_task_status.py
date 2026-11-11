"""Verify the publisher, task-specific HTTP routes, and example isolation."""

import json
import re
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
        self.assertTrue(startup.startswith("FlightCheck status card at http://127.0.0.1:"), startup)
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

        status_line = f"FlightCheck: [&lt; status /&gt;]({url})"
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

    def test_default_listener_serves_only_the_synthetic_example(self):
        url = self.start()
        status, body = self.request(url + "status.json")
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot["snapshot"], "historical")
        self.assertEqual(snapshot["candidate"], "example-02")
        self.assertEqual(snapshot["reviews"]["evidence"], "APPROVE_WITH_NITS")
        self.assertEqual(len(snapshot["gates"]), 8)
        self.assertEqual(self.request(url + "task/test-task/")[0], 404)

    def test_workflow_stage_map_follows_explicit_progress_and_candidate(self):
        details = self.snapshot.with_name("details.json")
        stages = {"Authoritative Gates": "current", "Plan": "completed", "Interactive UI Approval": "skipped"}
        details.write_text(json.dumps({"stages": stages, "worktree": "review-worktree"}))
        self.publish("--candidate", "first", "--details", str(details))
        url = self.start("--task-status", str(self.snapshot)) + "status.json"

        def current():
            status, body = self.request(url)
            self.assertEqual(status, 200)
            return json.loads(body)

        published = current()["stages"]
        self.assertEqual(len(published), 9)
        self.assertEqual(next(iter(published)), "Plan")
        self.assertEqual(published["Interactive UI Approval"], "skipped")
        self.assertEqual(published["Authoritative Gates"], "current")
        self.assertEqual(published["PR & Merge"], "pending")
        self.publish("--candidate", "first")
        self.assertEqual(current()["stages"], published)

        details.write_text(json.dumps({"stages": {**stages, "Implement": "current"}}))
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish("--candidate", "first", "--details", str(details))
        self.assertEqual(current()["stages"], published)
        self.publish("--candidate", "second")
        self.assertNotIn("stages", current())
        self.assertEqual(current()["worktree"], "review-worktree")

    def test_live_details_survive_resume_and_keep_older_evidence_stale(self):
        details = self.snapshot.with_name("details.json")
        observed = "2026-01-01T12:00:00Z"
        check = {"name": "Project tests", "candidate": "first", "state": "passed",
                 "counts": {"passed": 37}, "observed_at": observed, "private_path": "/private/log"}
        event = {"id": "repair-1", "kind": "repair", "candidate": "second",
                 "observed_at": observed, "summary": "Repaired failing input."}
        links = [{"kind": kind, "label": kind, "url": f"https://example.com/{kind}/1"}
                 for kind in ("epic", "issue", "pr")]
        ci = {"name": "Provider checks", "kind": "pr", "candidate": "first",
              "commit": "abcdef123", "attempt": 1, "state": "passed", "observed_at": observed,
              "url": "https://example.com/runs/1"}
        details.write_text(json.dumps({"links": links, "checks": [check], "ci": [ci]}))
        self.publish("--candidate", "first", "--details", str(details))
        url = self.start("--task-status", str(self.snapshot)) + "status.json"

        def current():
            status, body = self.request(url)
            self.assertEqual(status, 200)
            return json.loads(body)

        self.assertEqual(current()["links"], links)
        self.assertEqual(current()["ci"][0]["commit"], "abcdef123")
        self.assertNotIn("private_path", current()["checks"][0])
        details.write_text(json.dumps({"events": [event]}))
        for _ in range(2):
            self.publish("--candidate", "second", "--details", str(details))
        self.assertEqual(len(current()["history"]), 1)
        self.assertTrue(current()["checks"][0]["stale"])
        self.assertTrue(current()["ci"][0]["stale"])

        self.publish("--candidate", "first")
        self.assertTrue(current()["checks"][0]["stale"])
        failed = {**check, "state": "failed", "counts": {"failed": 1}}
        details.write_text(json.dumps({"checks": [failed], "ci": []}))
        self.publish("--candidate", "first", "--details", str(details))
        self.assertEqual(current()["checks"][0]["state"], "failed")
        self.assertFalse(current()["checks"][0]["stale"])
        self.assertEqual(current()["ci"], [])
        self.assertEqual(current()["history"][0]["id"], event["id"])

        for rejected in (
            {"links": [{"kind": "issue", "label": "Unsafe", "url": "javascript:alert(1)"}]},
            {"events": [{**event, "summary": "Replaced original observation."}]},
        ):
            previous = self.snapshot.read_bytes()
            details.write_text(json.dumps(rejected))
            with self.assertRaises(subprocess.CalledProcessError):
                self.publish("--candidate", "first", "--details", str(details))
            self.assertEqual(self.snapshot.read_bytes(), previous)

    def test_work_links_sort_by_recent_activity_across_types(self):
        details = self.snapshot.with_name("details.json")
        items = [
            ("issue", "Undated issue", None),
            ("epic", "Older epic", "2026-01-01T10:00:00Z"),
            ("pr", "Newest PR", "2026-01-01T09:00:00-05:00"),
            ("issue", "Newer issue", "2026-01-01T12:00:00Z"),
            ("epic", "Newer epic", "2026-01-01T12:00:00Z"),
            ("pr", "Older PR", "2026-01-01T13:00:00Z"),
            ("pr", "Undated PR", None),
        ]
        links = [{"kind": kind, "label": label, "url": f"https://example.com/items/{index}",
                  "created_at": created_at} for index, (kind, label, created_at) in enumerate(items)]
        links[1].update(title="Status card rollout", description="Coordinate the status card changes.")
        details.write_text(json.dumps({"links": links}))
        self.publish("--details", str(details))
        url = self.start("--task-status", str(self.snapshot)) + "status.json"
        status, body = self.request(url)
        self.assertEqual(status, 200)
        published = json.loads(body)["links"]
        self.assertEqual([link["label"] for link in published],
                         ["Newest PR", "Older PR", "Newer issue", "Newer epic",
                          "Older epic", "Undated issue", "Undated PR"])
        self.assertEqual(published[4]["title"], "Status card rollout")
        self.assertEqual(published[4]["description"], "Coordinate the status card changes.")

    def test_check_ci_and_legacy_history_lists_sort_by_activity(self):
        details = self.snapshot.with_name("details.json")
        times = ["2026-01-01T12:00:00Z", "2026-01-01T09:00:00-05:00", "2026-01-01T14:00:00Z"]
        checks = [{"name": f"Check {index}", "candidate": "first", "state": "passed", "observed_at": value}
                  for index, value in enumerate(times)]
        ci = [{**row, "name": f"CI {index}", "kind": "pr", "commit": "example"}
              for index, row in enumerate(checks)]
        events = [{"id": str(index), "kind": "rerun", "candidate": "first", "summary": f"Event {index}",
                   "observed_at": value} for index, value in enumerate(times)]
        details.write_text(json.dumps({"checks": checks, "ci": ci, "events": events}))
        self.publish("--candidate", "first", "--details", str(details))
        current = json.loads(self.snapshot.read_text())
        self.assertEqual([row["name"] for row in current["checks"]], ["Check 1", "Check 2", "Check 0"])
        self.assertEqual([row["name"] for row in current["ci"]], ["CI 1", "CI 2", "CI 0"])
        self.assertEqual([row["id"] for row in current["history"]], ["1", "2", "0"])
        current["history"].reverse()
        self.snapshot.write_text(json.dumps(current))
        self.publish("--candidate", "first")
        self.assertEqual([row["id"] for row in json.loads(self.snapshot.read_text())["history"]], ["2", "1", "0"])

    def test_modified_rows_move_first_and_unchanged_resumes_keep_their_times(self):
        details = self.snapshot.with_name("details.json")
        checks = [{"name": name, "candidate": "first", "state": "passed", "observed_at": observed}
                  for name, observed in (("Older", "2020-01-01T10:00:00Z"), ("Newer", "2020-01-01T11:00:00Z"))]
        links = [{"kind": "issue", "label": row["name"], "url": f"https://example.com/{index}",
                  "created_at": row["observed_at"]} for index, row in enumerate(checks)]
        ci = [{**row, "kind": "pr", "commit": "example"} for row in checks]
        details.write_text(json.dumps({"checks": checks, "links": links, "ci": ci}))
        self.publish("--candidate", "first", "--details", str(details))
        checks[0]["state"] = "failed"
        links[0]["description"] = "Latest update"
        ci[0]["state"] = "running"
        details.write_text(json.dumps({"checks": checks, "links": links, "ci": ci}))
        self.publish("--candidate", "first", "--details", str(details))
        modified = json.loads(self.snapshot.read_text())
        for field in ("checks", "ci"):
            self.assertEqual(modified[field][0]["name"], "Older")
            self.assertIn("updated_at", modified[field][0])
        self.assertEqual(modified["links"][0]["label"], "Older")
        self.assertIn("updated_at", modified["links"][0])
        self.publish("--candidate", "first", "--details", str(details))
        resumed = json.loads(self.snapshot.read_text())
        for field in ("checks", "ci", "links"):
            self.assertEqual(resumed[field], modified[field])

    def test_changed_records_with_older_observations_get_a_new_activity_time(self):
        details = self.snapshot.with_name("details.json")
        check = {"name": "Revised check", "candidate": "first", "state": "passed",
                 "observed_at": "2020-01-01T10:00:00Z"}
        ci = {**check, "kind": "pr", "commit": "example"}
        details.write_text(json.dumps({"checks": [check], "ci": [ci]}))
        self.publish("--candidate", "first", "--details", str(details))
        check.update(state="failed", observed_at="2020-01-01T09:00:00Z")
        ci.update(state="failed", observed_at="2020-01-01T09:00:00Z")
        details.write_text(json.dumps({"checks": [check], "ci": [ci]}))
        self.publish("--candidate", "first", "--details", str(details))
        changed = json.loads(self.snapshot.read_text())
        for field in ("checks", "ci"):
            self.assertGreater(changed[field][0]["updated_at"], changed[field][0]["observed_at"])
        self.publish("--candidate", "first", "--details", str(details))
        resumed = json.loads(self.snapshot.read_text())
        for field in ("checks", "ci"):
            self.assertEqual(resumed[field], changed[field])

    def test_explicit_stale_updates_move_checks_and_ci_to_the_top(self):
        details = self.snapshot.with_name("details.json")
        checks = [{"name": name, "candidate": "first", "state": "passed", "observed_at": observed}
                  for name, observed in (("Invalidated", "2020-01-01T10:00:00Z"),
                                         ("Unchanged", "2020-01-01T11:00:00Z"))]
        ci = [{**row, "kind": "pr", "commit": "example"} for row in checks]
        details.write_text(json.dumps({"checks": checks, "ci": ci}))
        self.publish("--candidate", "first", "--details", str(details))
        checks[0]["stale"] = True
        ci[0]["stale"] = True
        details.write_text(json.dumps({"checks": checks, "ci": ci}))
        self.publish("--candidate", "first", "--details", str(details))
        changed = json.loads(self.snapshot.read_text())
        for field in ("checks", "ci"):
            self.assertEqual(changed[field][0]["name"], "Invalidated")
            self.assertTrue(changed[field][0]["stale"])
            self.assertIn("updated_at", changed[field][0])
        self.publish("--candidate", "first", "--details", str(details))
        resumed = json.loads(self.snapshot.read_text())
        for field in ("checks", "ci"):
            self.assertEqual(resumed[field], changed[field])

    def test_stages_follow_the_readme_and_clear_later_completions_on_rewind(self):
        readme = (CARD.parent / "README.md").read_text()
        readme_stages = re.findall(r"^[ \t]*(\d{2}) ([A-Z][A-Z &]+?)[ \t]*$", readme, re.MULTILINE)
        self.assertEqual([int(number) for number, _ in readme_stages], list(range(1, 10)))
        expected = [name for _, name in readme_stages]
        details = self.snapshot.with_name("details.json")
        stage_states = {"Plan": "completed", "Implement": "completed", "Authoritative Gates": "current"}
        times = {"Plan": "2020-01-01T10:00:00Z", "Implement": "2020-01-01T11:00:00Z",
                 "Authoritative Gates": "2020-01-01T12:00:00Z"}
        details.write_text(json.dumps({"stages": stage_states, "stage_updated_at": times}))
        self.publish("--candidate", "first", "--details", str(details))
        initial = json.loads(self.snapshot.read_text())
        self.assertEqual([name.upper() for name in initial["stages"]], expected)
        stage_states.update({"Plan": "current", "Authoritative Gates": "completed"})
        details.write_text(json.dumps({"stages": stage_states}))
        self.publish("--candidate", "first", "--details", str(details))
        changed = json.loads(self.snapshot.read_text())
        self.assertEqual(next(iter(changed["stages"])), "Plan")
        self.assertEqual([name.upper() for name in changed["stages"]], expected)
        self.assertTrue(all(state == "pending" for name, state in changed["stages"].items() if name != "Plan"))
        self.assertGreater(changed["stage_updated_at"]["Implement"], initial["stage_updated_at"]["Implement"])
        self.publish("--candidate", "first", "--details", str(details))
        self.assertEqual(json.loads(self.snapshot.read_text())["stage_updated_at"], changed["stage_updated_at"])
        self.publish("--candidate", "second")
        self.assertNotIn("stages", json.loads(self.snapshot.read_text()))
        self.assertNotIn("stage_updated_at", json.loads(self.snapshot.read_text()))

    def test_old_snapshots_preserve_stage_definitions_and_hide_future_completions(self):
        readme = (CARD.parent / "README.md").read_text()
        expected = [name for _, name in re.findall(r"^[ \t]*(\d{2}) ([A-Z][A-Z &]+?)[ \t]*$", readme, re.MULTILINE)]
        self.publish("--candidate", "first")
        snapshot = json.loads(self.snapshot.read_text())
        snapshot.update(stages={"PR & Merge": "completed", "Final Verdict": "completed",
                                "Implement": "current", "Plan": "completed",
                                "Interactive UI Approval": "skipped"},
                        stage_updated_at={"PR & Merge": "2030-01-01T12:00:00Z"})
        self.snapshot.write_text(json.dumps(snapshot))
        url = self.start("--task-status", str(self.snapshot)) + "status.json"
        status, body = self.request(url)
        self.assertEqual(status, 200)
        stages = json.loads(body)["stages"]
        self.assertEqual([name.upper() for name in stages], expected)
        self.assertEqual(stages["Implement"], "current")
        self.assertEqual(stages["Final Verdict"], "pending")
        self.assertEqual(stages["PR & Merge"], "pending")
        self.assertEqual(stages["Interactive UI Approval"], "skipped")
        details = self.snapshot.with_name("details.json")
        details.write_text(json.dumps({"stages": {"Invented stage": "current"}}))
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish("--candidate", "first", "--details", str(details))

    def test_issue_stages_are_bound_to_the_associated_flights_current_candidate(self):
        details = self.snapshot.with_name("details.json")
        links = [
            {"kind": "issue", "label": "#1", "url": "https://example.com/issues/1", "flight": "test-task"},
            {"kind": "issue", "label": "#2", "url": "https://example.com/issues/2", "flight": "test-task"},
            {"kind": "issue", "label": "#3", "url": "https://example.com/issues/3", "flight": "other"},
            {"kind": "issue", "label": "#4", "url": "https://example.com/issues/4"},
        ]
        flights = {
            "other": {"candidate": "other-1", "stage_candidate": "other-1", "stage": "Implement"},
            "test-task": {"candidate": "first", "stage_candidate": "first", "stage": "Plan"},
        }
        stages = {"Authoritative Gates": "current"}
        details.write_text(json.dumps({"links": links, "tracked_flights": flights, "stages": stages}))
        self.publish("--candidate", "first", "--details", str(details))
        url = self.start("--task-status", str(self.snapshot)) + "status.json"

        def current():
            status, body = self.request(url)
            self.assertEqual(status, 200)
            return json.loads(body)

        initial = current()
        self.assertEqual(initial["links"], links)
        self.assertNotIn("tracked_flights", initial)
        self.assertEqual(initial["issue_stages"], {
            "test-task": {"stage": "Authoritative Gates", "shared": True},
            "other": {"stage": "Implement", "shared": False},
        })

        flights["other"]["candidate"] = "other-2"
        details.write_text(json.dumps({"tracked_flights": flights}))
        self.publish("--candidate", "first", "--details", str(details))
        self.assertEqual(current()["stages"], initial["stages"])
        self.assertEqual(current()["issue_stages"], {"test-task": initial["issue_stages"]["test-task"]})

        self.publish("--candidate", "second")
        self.assertNotIn("stages", current())
        self.assertEqual(current()["issue_stages"], {})

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
