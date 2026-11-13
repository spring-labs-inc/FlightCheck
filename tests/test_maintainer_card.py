"""Exercise maintainer footer handling and task-card publication."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

from card_fixture import initialized_details

ROOT = Path(__file__).resolve().parents[1]


class MaintainerCardTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        self.checkout = root / "maintainer checkout"
        self.checkout.mkdir()
        self.readme = self.checkout / "README.md"
        self.readme.write_text("Original\n")
        shutil.copytree(ROOT / "status-card", self.checkout / "status-card")
        shutil.copyfile(ROOT / "AGENTS.md", self.checkout / "AGENTS.md")
        self.state = root / "state"
        self.session = "test-maintainer-session"
        self.env = dict(os.environ, FLIGHTCHECK_STATE_DIR=str(self.state), CODEX_THREAD_ID=self.session)
        self.run_git("init", "-q")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "Synthetic starting point")

    def run_git(self, *args):
        subprocess.run(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
             "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
            check=True, cwd=self.checkout, env=self.env, capture_output=True, timeout=5,
        )

    def hook(self, event, turn, reply=None, retried=False):
        subdir = self.checkout / "status-card"
        payload = {"hook_event_name": event, "cwd": str(subdir), "session_id": self.session,
                   "turn_id": turn, "last_assistant_message": reply, "stop_hook_active": retried}
        return json.loads(subprocess.check_output(
            [sys.executable, "-B", str(self.checkout / "status-card/maintainer.py"), "hook"],
            input=json.dumps(payload), text=True,
            cwd=subdir, env=self.env, timeout=8,
        ))

    def card(self, *args, checkout=None):
        args = initialized_details(checkout or self.checkout, self.state.parent / "fixture-details.json", args,
                                   "Final Verdict" if "--verdict" in args else "Plan")
        return subprocess.check_output(
            [sys.executable, "-B", "status-card/maintainer.py", "card",
             "--task", "test-change", "--title", "Synthetic implementation", *args],
            cwd=checkout or self.checkout, env=self.env, text=True, timeout=8,
        ).strip()

    def endpoint(self):
        endpoint, = self.state.glob("*/tasks/test-change/endpoint.json")
        return json.loads(endpoint.read_text())

    def stop_listener(self, pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def request(self, footer, suffix=""):
        route = urlsplit(footer.rsplit("(", 1)[1].rstrip(")"))
        connection = HTTPConnection(route.hostname, route.port, timeout=1)
        try:
            connection.request("GET", route.path + suffix)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            return response.read()
        finally:
            connection.close()

    def test_turn_requires_a_current_clickable_footer_only_for_implementation(self):
        self.readme.write_text("Pre-existing change\n")
        self.assertEqual(self.hook("UserPromptSubmit", "question"), {})
        self.assertEqual(self.hook("Stop", "question", "A read-only reply."), {})
        self.assertFalse(list(self.state.glob("*/tasks/*")))

        self.hook("UserPromptSubmit", "implementation")
        self.readme.write_text("Change made in this turn\n")
        self.assertEqual(self.hook("Stop", "implementation", "Edited.")["decision"], "block")
        footer = self.card()
        self.addCleanup(self.stop_listener, self.endpoint()["pid"])
        self.assertIn(b"<html", self.request(footer))
        self.assertEqual(json.loads(self.request(footer, "status.json"))["task"], "test-change")
        self.assertEqual(self.hook("Stop", "implementation", "Edited.\n\n" + footer), {})
        self.assertEqual(self.hook("Stop", "implementation", footer + "\n\nVerdict: Pending")["decision"], "block")
        self.assertEqual(self.hook("Stop", "implementation", "```\n\n" + footer)["decision"], "block")
        self.assertIn("systemMessage", self.hook("Stop", "implementation", "Missing again.", retried=True))

        self.hook("UserPromptSubmit", "resume")
        self.assertEqual(self.card(), footer)
        self.assertEqual(self.hook("Stop", "resume", "Awaiting approval.")["decision"], "block")
        self.assertEqual(self.hook("Stop", "resume", "Awaiting approval.\n\n" + footer), {})
        self.readme.write_text("Another edit\n")
        self.assertEqual(self.hook("Stop", "resume", footer)["decision"], "block")
        self.assertEqual(self.card(), footer)
        self.assertEqual(self.hook("Stop", "resume", footer), {})

        self.hook("UserPromptSubmit", "later-question")
        self.assertEqual(self.hook("Stop", "later-question", "Another read-only reply."), {})

    def test_resume_restores_a_stopped_listener_at_the_same_url(self):
        footer = self.card("--summary", "Keep this summary on resume.")
        pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, pid)
        self.stop_listener(pid)
        route = urlsplit(footer.rsplit("(", 1)[1].rstrip(")"))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            connection = HTTPConnection(route.hostname, route.port, timeout=0.1)
            try:
                connection.connect()
            except ConnectionRefusedError:
                break
            finally:
                connection.close()
            time.sleep(0.02)
        else:
            self.fail("Stopped listener still accepts connections")

        self.assertEqual(self.card(), footer)
        restarted_pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, restarted_pid)
        self.assertNotEqual(restarted_pid, pid)
        self.assertEqual(json.loads(self.request(footer, "status.json"))["summary"],
                         "Keep this summary on resume.")

    def test_checkout_label_tracks_primary_branch_linked_worktree_and_detached_head(self):
        self.run_git("switch", "-c", "codex/primary-label")
        details = self.state.parent / "legacy-details.json"
        details.write_text(json.dumps({"worktree": "old label"}))
        footer = self.card("--details", str(details))
        self.addCleanup(self.stop_listener, self.endpoint()["pid"])

        primary = json.loads(self.request(footer, "status.json"))
        self.assertEqual(primary["branch"], "codex/primary-label")
        self.assertNotIn("worktree", primary)

        linked = self.checkout.parent / "linked checkout"
        self.run_git("worktree", "add", "-b", "codex/linked-branch", str(linked))
        self.assertEqual(self.card(checkout=linked), footer)
        worktree = json.loads(self.request(footer, "status.json"))
        self.assertEqual(worktree["worktree"], "linked checkout")
        self.assertNotIn("branch", worktree)

        self.run_git("switch", "--detach")
        self.assertEqual(self.card(), footer)
        detached = json.loads(self.request(footer, "status.json"))
        self.assertNotIn("branch", detached)
        self.assertNotIn("worktree", detached)

    def test_resume_replaces_an_older_listener_that_drops_branch_metadata(self):
        self.run_git("switch", "-c", "codex/upgrade-label")
        server = self.checkout / "status-card/serve.py"
        server_source = server.read_text()
        legacy_source = server.with_name("legacy_serve.py")
        legacy_source.write_text(server_source)
        server.write_text(
            "import legacy_serve\n"
            "read_task = legacy_serve.read_task\n"
            "def legacy_read_task(path):\n"
            "    snapshot = read_task(path)\n"
            "    snapshot.pop('branch', None)\n"
            "    return snapshot\n"
            "legacy_serve.read_task = legacy_read_task\n"
            "legacy_serve.main()\n"
        )
        self.run_git("switch", "--detach")
        footer = self.card()
        legacy_pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, legacy_pid)
        self.assertNotIn("branch", json.loads(self.request(footer, "status.json")))

        server.write_text(server_source)
        legacy_source.unlink()
        self.run_git("switch", "codex/upgrade-label")
        self.assertEqual(self.card(), footer)
        upgraded_pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, upgraded_pid)
        self.assertNotEqual(upgraded_pid, legacy_pid)
        self.assertEqual(json.loads(self.request(footer, "status.json"))["branch"], "codex/upgrade-label")
        self.assertEqual(self.card(), footer)
        self.assertEqual(self.endpoint()["pid"], upgraded_pid)

    def test_resume_replaces_an_older_listener_that_drops_activity_metadata(self):
        server = self.checkout / "status-card/serve.py"
        source = server.read_text()
        legacy_source = server.with_name("legacy_serve.py")
        legacy_source.write_text(source)
        server.write_text(
            "import legacy_serve\n"
            "read_task = legacy_serve.read_task\n"
            "def legacy_read_task(path):\n"
            "    snapshot = read_task(path)\n"
            "    if snapshot.get('stages', {}).get('Implement') == 'current':\n"
            "        snapshot.pop('stage_updated_at', None)\n"
            "    return snapshot\n"
            "legacy_serve.read_task = legacy_read_task\n"
            "legacy_serve.main()\n"
        )
        footer = self.card()
        legacy_pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, legacy_pid)
        server.write_text(source)
        legacy_source.unlink()
        details = self.state.parent / "activity-details.json"
        details.write_text(json.dumps({"stages": {"Implement": "current"}}))
        self.assertEqual(self.card("--details", str(details)), footer)
        upgraded_pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, upgraded_pid)
        self.assertNotEqual(upgraded_pid, legacy_pid)
        snapshot = json.loads(self.request(footer, "status.json"))
        self.assertIn("Implement", snapshot["stage_updated_at"])

    def test_resume_replaces_an_older_listener_that_reorders_stages(self):
        server = self.checkout / "status-card/serve.py"
        source = server.read_text()
        legacy_source = server.with_name("legacy_serve.py")
        legacy_source.write_text(source)
        server.write_text(
            "import legacy_serve\n"
            "read_task = legacy_serve.read_task\n"
            "def legacy_read_task(path):\n"
            "    snapshot = read_task(path)\n"
            "    if snapshot.get('stages', {}).get('Implement') == 'current':\n"
            "        snapshot['stages'] = dict(reversed(list(snapshot['stages'].items())))\n"
            "    return snapshot\n"
            "legacy_serve.read_task = legacy_read_task\n"
            "legacy_serve.main()\n"
        )
        footer = self.card()
        legacy_pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, legacy_pid)
        server.write_text(source)
        legacy_source.unlink()
        details = self.state.parent / "stage-details.json"
        details.write_text(json.dumps({"stages": {"Plan": "completed", "Implement": "current"}}))
        self.assertEqual(self.card("--details", str(details)), footer)
        upgraded_pid = self.endpoint()["pid"]
        self.addCleanup(self.stop_listener, upgraded_pid)
        self.assertNotEqual(upgraded_pid, legacy_pid)
        snapshot = json.loads(self.request(footer, "status.json"))
        self.assertEqual(list(snapshot["stages"])[:2], ["Plan", "Implement"])

    def test_same_candidate_repair_clears_approval_and_does_not_restore_it_on_advance(self):
        details = self.state.parent / "repair-details.json"
        details.write_text(json.dumps({"stages": {"Final Verdict": "completed", "PR & Merge": "current"}}))
        footer = self.card("--details", str(details))
        self.addCleanup(self.stop_listener, self.endpoint()["pid"])
        original = json.loads(self.request(footer, "status.json"))
        self.assertEqual(self.card("--details", str(details), "--verdict", "APPROVE",
                                   "--verdict-candidate", original["candidate"]), footer)
        self.assertEqual(json.loads(self.request(footer, "status.json"))["verdict"], "APPROVE")
        details.write_text(json.dumps({"stages": {"Plan": "current", "Final Verdict": "completed"}}))
        self.assertEqual(self.card("--details", str(details)), footer)
        repaired = json.loads(self.request(footer, "status.json"))
        self.assertEqual(repaired["candidate"], original["candidate"])
        self.assertEqual(repaired["verdict"], "Pending")
        self.assertIsNone(repaired["verdict_candidate"])
        self.assertEqual(repaired["stages"]["Final Verdict"], "pending")
        details.write_text(json.dumps({"stages": {"Final Verdict": "completed", "PR & Merge": "current"}}))
        self.assertEqual(self.card("--details", str(details)), footer)
        self.assertEqual(json.loads(self.request(footer, "status.json"))["verdict"], "Pending")

    def test_adoption_template_keeps_explicit_selection(self):
        example = ROOT / "examples/existing-project"
        instructions = (example / "AGENTS.md").read_text()
        self.assertIn("when the owner explicitly selects", instructions)
        self.assertIn("`$develop-change`", instructions)
        self.assertEqual(json.loads((example / ".codex/hooks.json").read_text())["hooks"], {})
