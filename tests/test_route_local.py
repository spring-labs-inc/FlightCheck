"""Local execution does not verify a different native browser endpoint."""

import json
import subprocess
import sys
import time
import unittest

import test_route_discovery as fixture


class LocalRouteTests(unittest.TestCase):
    project = fixture.RouteDiscoveryTests.project
    tab = fixture.RouteDiscoveryTests.tab
    observed = fixture.RouteDiscoveryTests.observed

    def prepare(self, case, extra=()):
        root, checkout, env = case
        details = root / "first-details.json"
        if not details.exists():
            stages = ["Plan", "Implement", "Cheap Tests", "Interactive UI Approval", "Independent Code Review",
                      "Authoritative Gates", "Skeptical Evidence Review", "Final Verdict", "PR & Merge"]
            details.write_text(json.dumps({
                "stages": {name: "current" if name == "Plan" else "pending" for name in stages},
                "check_plan": [], "checks": [], "checks_unavailable": "Synthetic fixture.",
                "links_unavailable": {"issue": "Synthetic fixture.", "pr": "No delivery."}}))
        result = subprocess.run([sys.executable, "-B", "status-card/reply.py", "prepare", "--task", "first",
                                 "--session", "controller", "--execution", "local", "--details", str(details), *extra],
                                cwd=checkout, env=env, capture_output=True, text=True, timeout=20)
        return result.returncode, json.loads(result.stdout)

    def check(self, case, footer):
        root, checkout, env = case
        draft = root / "draft.txt"; draft.write_text(footer)
        result = subprocess.run([sys.executable, "-B", "status-card/reply.py", "check", "--task", "first",
                                 "--session", "controller", "--execution", "local", "--reply-file", str(draft)],
                                cwd=checkout, env=env, capture_output=True, text=True, timeout=20)
        return result.returncode, json.loads(result.stdout)

    def hook(self, case, kind, message=""):
        _, checkout, env = case
        return json.loads(subprocess.check_output(
            [sys.executable, "-B", "status-card/maintainer.py", "hook"],
            input=json.dumps({"hook_event_name": kind, "cwd": str(checkout), "session_id": "controller",
                              "turn_id": "local-native", "last_assistant_message": message}),
            cwd=checkout, env=env, text=True, timeout=20))

    def local_case(self):
        case = self.project()
        for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "CODESPACES", "REMOTE_CONTAINERS"):
            case[2].pop(key, None)
        self.assertEqual(self.hook(case, "UserPromptSubmit"), {})
        return case

    def test_local_native_route_freshness_witness(self):
        for invalidation in ("expired", "candidate", "negative"):
            with self.subTest(invalidation=invalidation):
                case = self.local_case()
                code, initial = self.prepare(case); self.assertEqual(code, 0, initial)
                path, value, directory = self.observed(case, initial)
                self.assertNotEqual(value["tabs"][0]["url"], initial["host_url"])
                code, exact = self.prepare(case, ["--browser-observation", str(path), "--reconcile-route"])
                self.assertEqual(code, 0, exact)
                self.assertEqual(exact["user_url"], value["tabs"][0]["url"])
                self.assertEqual(self.check(case, exact["footer"])[0], 0)
                self.assertEqual(self.hook(case, "Stop", exact["footer"]), {})
                if invalidation == "expired":
                    record = json.loads((directory / "reply-route.json").read_text())
                    record["route_verification"]["observed_at"] = time.time() - 31
                    (directory / "reply-route.json").write_text(json.dumps(record))
                elif invalidation == "candidate":
                    (case[1] / "changed.txt").write_text("Current worker source is newer than native observation.\n")
                else:
                    value.update(observed_at=time.time(), tabs=[])
                    path.write_text(json.dumps(value))
                    negative_code, negative = self.prepare(case, ["--browser-observation", str(path)])
                    with self.subTest(surface="negative-observation"):
                        self.assertEqual(negative_code, 1, negative)
                        self.assertNotIn("http", negative["footer"])
                # Gather all public boundaries before assertions or recovery.
                prepared_code, pending = self.prepare(case)
                checked_code, checked = self.check(case, exact["footer"])
                stopped = self.hook(case, "Stop", exact["footer"])
                for surface, code, result in (("no-url-prepare", prepared_code, pending),
                                              ("public-check", checked_code, checked)):
                    with self.subTest(surface=surface):
                        self.assertEqual(code, 1, result)
                        self.assertNotIn("http", result["footer"])
                with self.subTest(surface="native-stop"):
                    self.assertEqual(stopped.get("decision"), "block", stopped)
                self.assertEqual(pending["user_url"], exact["user_url"])
                self.assertIsNotNone(fixture.load("reply").maintainer.current_card(
                    "first", json.loads((directory / "endpoint.json").read_text())["port"], pending["candidate"]))
                path, _, _ = self.observed(case, pending)
                code, recovered = self.prepare(case, ["--browser-observation", str(path)])
                self.assertEqual(code, 0, recovered)
                self.assertEqual(self.check(case, recovered["footer"])[0], 0)
                self.assertEqual(self.hook(case, "Stop", recovered["footer"]), {})

    def test_direct_local_listener_remains_usable(self):
        case = self.local_case()
        for change in (False, True):
            if change:
                (case[1] / "changed.txt").write_text("Direct local publication follows its own current listener.\n")
            code, ready = self.prepare(case)
            self.assertEqual(code, 0, ready)
            self.assertEqual(ready["user_url"], ready["host_url"])
            self.assertEqual(self.check(case, ready["footer"])[0], 0)
            self.assertEqual(self.hook(case, "Stop", ready["footer"]), {})


if __name__ == "__main__":
    unittest.main()
