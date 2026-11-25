"""Native preservation and completion witnesses for required flight disposition."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

from lifecycle_cases import LifecycleCases, PRODUCT


class FlightLifecycleTests(LifecycleCases, unittest.TestCase):
    def test_launch(self):
        with self.world():
            (self.source / "owner-untracked.txt").write_text("preserve unfinished checkout work\n")
            unrelated = self.worktree(self.area / "unrelated", "looks-like-flight81")
            (unrelated / "existing.txt").write_text("unrelated unfinished work\n")
            before = self.snapshot([self.root, self.source, unrelated, self.registry.directory])
            with patch.object(self.life.launch_detection, "detect", wraps=self.life.launch_detection.detect) as called:
                resumed = self.life.launch(self.root, self.registry, "fixture/repo", issues=[81], current_flight="fixture")
                separate = self.life.launch(self.root, self.registry, "fixture/repo", issues=[999])
            self.assertEqual(called.call_count, 2, "Normal lifecycle launch must use delivered lightweight detection")
            self.assertEqual(resumed["related"][0]["decision"]["action"], "resume")
            observation = resumed["related"][0]["checkouts"][0]
            self.assertEqual(observation["state"]["untracked"], ["owner-untracked.txt"])
            self.assertIn("unpushed", observation["branch_state"])
            self.assertFalse(separate["decision_required"])
            self.assertEqual(separate["related"], [])
            self.assertTrue(any(row["state"].get("dirty") for row in separate["other_worktrees"]))
            self.assertEqual(self.snapshot([self.root, self.source, unrelated, self.registry.directory]), before)
            self.assertIn("Not queried", resumed["coverage"]["remote"])

    def test_authority(self):
        with self.world(grant=False):
            before = self.snapshot()
            with self.assertRaises(ValueError):
                self.life.register_cleanup(self.root, self.registry, "fixture", inventory=self.inventory(),
                                           reference=self.owner_reference)
            self.assertEqual(self.snapshot(), before)
            self.blocked(self.plan())
            self.assertTrue(self.source.exists())
            self.assertEqual(self.remote_tip(), self.head)
        for changed in ("reference", "extra-path", "wrong-flight", "drop-protocol"):
            with self.subTest(authority=changed), self.world():
                original = self.registry.get("fixture")
                before = self.snapshot()
                if changed == "reference":
                    with self.assertRaises(ValueError):
                        self.life.register_cleanup(self.root, self.registry, "fixture", inventory=self.inventory(), reference="")
                elif changed == "extra-path":
                    extra = self.area / "ungranted"
                    inventory = self.inventory() + [{"kind": "worktree", "identity": str(extra)}]
                    with self.assertRaises(ValueError):
                        self.life.register_cleanup(self.root, self.registry, "fixture", inventory=inventory,
                                                   reference=self.owner_reference)
                elif changed == "wrong-flight":
                    with self.assertRaises(ValueError):
                        self.life.plan(self.root, self.registry, "name-resembles-fixture", delivery=self.delivery, policy=self.policy)
                else:
                    self.assertEqual(original["cleanup"]["protocol"], "required-v1")
                    dropped = copy.deepcopy(original)
                    dropped.pop("cleanup")
                    with self.assertRaises(ValueError):
                        self.registry.save(dropped, expected_revision=self.registry.read()["revision"])
                self.assertEqual(self.registry.get("fixture"), original)
                self.assertEqual(self.snapshot(), before)

    def test_integration(self):
        # C1: actual squash preserves bytes, executable mode AND deletion at M;
        # later target edits are not a reason to lose valid historic integration.
        for mode in ("merge", "squash", "rebase"):
            with self.subTest(mode=mode), self.world(mode):
                self.assertNotEqual(self.git(self.root, "rev-parse", self.head + "^{tree}"),
                                    self.git(self.root, "rev-parse", self.merge + "^{tree}"))
                (self.root / "tool.sh").write_text("#!/bin/sh\nprintf 'later target edit\\n'\n")
                self.git(self.root, "add", "tool.sh")
                self.git(self.root, "commit", "-qm", "Later target work after integration")
                result = self.life.integration_status(self.root, self.head, "trunk", delivery=self.delivery)
                self.assertIs(result["verified"], True, result)
                self.assertEqual(result["merge_commit"], self.merge)
                self.assertEqual(result["source_head"], self.head)
                self.assertNotEqual(result["target_tip"], self.merge)
                self.assertIn("tool.sh", json.dumps(result["changed_paths"]))
                self.assertIn("obsolete.txt", json.dumps(result["changed_paths"]))
        for defect in ("mode", "deletion", "mode-and-deletion", "bytes", "unmerged", "wrong-head", "wrong-target", "wrong-repository"):
            with self.subTest(integration_defect=defect), self.world("squash"):
                delivery = copy.deepcopy(self.delivery)
                if defect in ("mode", "deletion", "mode-and-deletion", "bytes"):
                    if defect in ("mode", "mode-and-deletion"):
                        (self.root / "tool.sh").chmod(0o644)
                    if defect in ("deletion", "mode-and-deletion"):
                        (self.root / "obsolete.txt").write_text("source deletion was lost\n")
                    if defect == "bytes":
                        (self.root / "tool.sh").write_text("source bytes were lost\n")
                    self.git(self.root, "add", "-A")
                    self.git(self.root, "commit", "-qm", "Bad integration content")
                    delivery["merge_commit"] = self.git(self.root, "rev-parse", "HEAD")
                    (self.root / "tool.sh").write_text("later target edit unrelated to proof point\n")
                    self.git(self.root, "add", ".")
                    self.git(self.root, "commit", "-qm", "Later target after bad integration")
                elif defect == "unmerged":
                    delivery["merged"] = False
                elif defect == "wrong-head":
                    delivery["head"] = self.base
                elif defect == "wrong-target":
                    delivery["target"] = self.topic
                else:
                    delivery["repository"] = "somebody/else"
                if defect == "wrong-repository":
                    # The planner supplies the repository-qualified ownership
                    # context; the standalone assessor's injected provider
                    # boundary has no separate expected repository parameter.
                    result = self.life.plan(self.root, self.registry, "fixture", delivery=delivery, policy=self.policy,
                                            client_state=self.client_state, preservation=self.saved_assets)
                    self.blocked(result)
                else:
                    result = self.life.integration_status(self.root, self.head, "trunk", delivery=delivery)
                    self.assertIs(result["verified"], False, result)
                    self.assertTrue(result["blockers"], result)

    def test_preservation(self):
        for obstacle in ("tracked", "staged", "untracked", "ignored", "ignored-changed", "locked", "protected", "main", "active-other", "unintegrated"):
            with self.subTest(preserve=obstacle), self.world():
                policy = copy.deepcopy(self.policy)
                if obstacle in ("tracked", "staged"):
                    (self.source / "existing.txt").write_text("unfinished owner edit\n")
                    if obstacle == "staged":
                        self.git(self.source, "add", "existing.txt")
                elif obstacle == "untracked":
                    (self.source / "owner\nnotes.txt").write_text("untracked owner work\n")
                elif obstacle == "ignored":
                    (self.source / ".env").write_text("PRIVATE_OWNER_BYTES_DO_NOT_READ_OR_REMOVE\n")
                elif obstacle == "ignored-changed":
                    with (self.source / ".flightcheck/project.json").open("a") as output:
                        output.write("\n")
                elif obstacle == "locked":
                    self.git(self.root, "worktree", "lock", str(self.source), "--reason", "Other live client")
                elif obstacle == "protected":
                    policy["protected_branches"].append(self.topic)
                elif obstacle == "main":
                    # A contradictory owner declaration cannot turn the actual
                    # repository main checkout into a disposable worktree.
                    v = self.registry.get("fixture")
                    v["checkout"]["path"] = str(self.root)
                    v["checkout"]["branch"] = "trunk"
                    v["checkout"]["commit"] = self.merge
                    self.registry.save(v, expected_revision=self.registry.read()["revision"])
                elif obstacle == "active-other":
                    other = self.area / "other-active"
                    self.git(self.root, "worktree", "add", "--force", str(other), self.topic)
                    self.configure(other)
                    v = self.record(other, flight="another-active-flight")
                    v["issues"] = [999]
                    v["client"] = {"name": "claude", "sessions": ["other-live-session"]}
                    self.registry.save(v, expected_revision=self.registry.read()["revision"])
                else:
                    self.commit(self.source, "postmerge-work.txt")
                before = self.snapshot()
                report = self.life.plan(self.root, self.registry, "fixture", delivery=self.delivery, policy=policy,
                                        client_state=self.client_state, preservation=self.saved_assets)
                self.blocked(report)
                invoked = []
                applied = self.life.apply(self.root, self.registry, "fixture", report,
                                          artifact_id=self.row(report, "worktree")["id"], native_cleanup=lambda request: invoked.append(request),
                                          delivery=self.delivery, policy=policy, client_state=self.client_state,
                                          preservation=self.saved_assets)
                self.blocked(applied)
                self.assertEqual(invoked, [])
                self.assertTrue(self.source.exists())
                self.assertEqual(self.remote_tip(), self.head)
                self.assertEqual(self.snapshot(), before)

    def test_native(self):
        with self.world():
            plan = self.plan()
            native_id = self.row(plan, "worktree")["id"]
            pending = self.apply(plan, artifact_id=native_id)
            self.assertFalse(pending["complete"])
            self.assertTrue(self.source.exists())
            requests = []
            def wrong_client(request):
                requests.append(copy.deepcopy(request))
                return {"client": "claude", "path": str(self.source), "operation_id": request["operation_id"], "success": True}
            rejected = self.apply(plan, artifact_id=native_id, native_cleanup=wrong_client)
            self.blocked(rejected)
            self.assertEqual(len(requests), 1)
            self.assertTrue(self.source.exists())
            self.assertTrue(any(item["path"] == str(self.source) for item in self.launch._worktrees(self.root)))
            matched_success = dict(requests[0], client=self.client_state["client"], success=True)
            no_absence = self.life.acknowledge_native(self.root, self.registry, "fixture", plan, native_id, matched_success)
            self.blocked(no_absence)
            self.assertFalse(no_absence["ready"], "Matching client success still requires actual path/admin absence")
            self.assertTrue(self.source.exists())
            prior = self.registry.get("fixture")
            self.assertIn(requests[0]["operation_id"], json.dumps(prior))
            self.assertIn("claude", json.dumps(prior), "Rejected native outcome must survive interruption")
            extra = self.worktree(self.area / "flight81-extra", "flight81-extra")
            (extra / "owner.txt").write_text("ungranted extra checkout\n")
            resumed = self.apply(plan, artifact_id=native_id)
            self.assertFalse(resumed["complete"])
            self.assertEqual(resumed["plan_sha256"], plan["plan_sha256"])
            self.assertFalse(any(str(extra) in json.dumps(row["identity"]) for row in resumed["artifacts"]))
            self.assertEqual(self.registry.get("fixture")["grants"], prior["grants"])
            self.assertEqual((extra / "owner.txt").read_text(), "ungranted extra checkout\n")
            with self.assertRaises(ValueError):
                self.guard.release(self.registry, "fixture", "Cannot close unresolved native cleanup", policy=self.policy)
            self.assertNotEqual(self.registry.get("fixture")["lifecycle"]["state"], "closed")
        with self.world():
            before = self.snapshot()
            no_safe_leave = self.life.plan(self.root, self.registry, "fixture", delivery=self.delivery,
                                           policy=self.policy, preservation=self.saved_assets)
            self.blocked(no_safe_leave)
            self.assertTrue(self.row(no_safe_leave, "worktree")["blockers"])
            self.assertEqual(self.snapshot(), before, "Headless/unknown native availability cannot trigger fallback removal")
            plan = self.plan()
            done = self.apply(plan, artifact_id=self.row(plan, "worktree")["id"], native_cleanup=self.remove_native)
            self.assertFalse(self.source.exists())
            self.assertFalse(any(item["path"] == str(self.source) for item in self.launch._worktrees(self.root)))
            self.assertIn(self.row(done, "worktree")["state"], ("removed", "already_absent"))
            self.assertTrue(any(row.get("state") == "removed" for row in self.registry.get("fixture")["cleanup"]["operations"]))

    def test_remote(self):
        with self.world():
            plan = self.plan()
            self.apply(plan, artifact_id=self.row(plan, "worktree")["id"], native_cleanup=self.remove_native)
            h1 = self.advance_remote()
            actor = self.area / "local-actor"
            self.git(self.root, "worktree", "add", "--detach", str(actor), self.head)
            self.configure(actor)
            h2 = self.commit(actor, "additional-local-work.txt")
            self.git(self.root, "worktree", "remove", str(actor))
            self.git(self.root, "update-ref", "refs/heads/" + self.topic, h2, self.head)
            self.assertEqual(self.git(self.root, "rev-parse", "refs/remotes/origin/" + self.topic), self.head)
            for kind in ("local_branch", "remote_branch"):
                result = self.apply(plan, artifact_id=self.row(plan, kind)["id"])
                self.blocked(result)
            self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), h2)
            self.assertEqual(self.remote_tip(), h1)
            self.assertEqual(self.git(self.root, "rev-parse", "refs/remotes/origin/" + self.topic), self.head)
        with self.world():
            plan = self.plan()
            self.apply(plan, artifact_id=self.row(plan, "worktree")["id"], native_cleanup=self.remove_native)
            original = self.life.subprocess.run
            changed = []
            def advance_at_connection(argv, *args, **kwargs):
                if "push" in argv and not changed:
                    # The mutation occurs before Git's new connection and
                    # advertisement, where an explicit old-OID lease matters.
                    with patch.object(self.life.subprocess, "run", original):
                        changed.append(self.advance_remote())
                return original(argv, *args, **kwargs)
            with patch.object(self.life.subprocess, "run", side_effect=advance_at_connection):
                result = self.apply(plan, artifact_id=self.row(plan, "remote_branch")["id"])
            self.assertEqual(len(changed), 1)
            self.blocked(result)
            self.assertEqual(self.remote_tip(), changed[0])
        with self.world():
            plan = self.plan()
            self.apply(plan, artifact_id=self.row(plan, "worktree")["id"], native_cleanup=self.remove_native)
            # Cached tracking absence is not actual remote deletion.
            self.git(self.root, "update-ref", "-d", "refs/remotes/origin/" + self.topic)
            self.assertEqual(self.remote_tip(), self.head)
            result = self.apply(plan, artifact_id=self.row(plan, "remote_branch")["id"])
            self.assertIsNone(self.remote_tip())
            self.assertIn(self.row(result, "remote_branch")["state"], ("removed", "already_absent"))

    def test_recovery(self):
        with self.world():
            plan = self.plan()
            self.apply(plan, artifact_id=self.row(plan, "worktree")["id"], native_cleanup=self.remove_native)
            first = self.apply(plan, artifact_id=self.row(plan, "remote_branch")["id"])
            self.assertIsNone(self.remote_tip())
            self.assertIn(self.row(first, "remote_branch")["state"], ("removed", "already_absent"))
            before = self.registry.get("fixture")
            repeated = self.apply(plan, artifact_id=self.row(plan, "remote_branch")["id"])
            self.assertIn(self.row(repeated, "remote_branch")["state"], ("removed", "already_absent"))
            self.assertEqual(repeated["plan_sha256"], plan["plan_sha256"])
            self.assertEqual(self.registry.get("fixture")["grants"], before["grants"])
            self.git(self.root, "push", "--quiet", "origin", self.head + ":refs/heads/" + self.topic)
            reappeared = self.apply(plan, artifact_id=self.row(plan, "remote_branch")["id"])
            self.blocked(reappeared)
            self.assertEqual(self.remote_tip(), self.head, "A recorded removed artifact reappearing is not a fresh deletion lease")
        with self.world():
            plan = self.plan()
            original = self.life.subprocess.run
            once = []
            class Interrupted(BaseException):
                pass
            def disconnect_after_delete(argv, *args, **kwargs):
                result = original(argv, *args, **kwargs)
                if "push" in argv and not once and result.returncode == 0:
                    once.append(True)
                    raise Interrupted("Process stopped after actual remote deletion and before outcome journal")
                return result
            with patch.object(self.life.subprocess, "run", side_effect=disconnect_after_delete):
                with self.assertRaises(Interrupted):
                    self.apply(plan, artifact_id=self.row(plan, "remote_branch")["id"])
            self.assertIsNone(self.remote_tip())
            resumed = self.apply(plan, artifact_id=self.row(plan, "remote_branch")["id"])
            self.assertIn(self.row(resumed, "remote_branch")["state"], ("removed", "already_absent"))
            self.assertEqual(resumed["plan_sha256"], plan["plan_sha256"])

    def test_closeout(self):
        with self.world():
            plan = self.plan()
            status = self.life.closure_status(self.root, self.registry, "fixture", delivery=self.delivery, policy=self.policy)
            self.assertFalse(status["complete"], "Merged PR alone cannot complete PR & Merge")
            with self.assertRaises(ValueError):
                self.guard.release(self.registry, "fixture", "Must retain required cleanup gate", policy=self.policy)
            done = self.apply(plan, native_cleanup=self.remove_native)
            self.assertIs(done["complete"], True, done)
            self.assertFalse(self.source.exists())
            self.assertIsNone(self.remote_tip())
            self.run_git(self.root, "rev-parse", "--verify", "refs/heads/" + self.topic, expected=128)
            status = self.life.closure_status(self.root, self.registry, "fixture", delivery=self.delivery, policy=self.policy)
            self.assertIs(status["complete"], True, status)
            self.guard.release(self.registry, "fixture", "Observed all authorized cleanup completed",
                               policy=self.policy, control_checkout=self.root)
            self.assertEqual(self.registry.get("fixture")["lifecycle"]["state"], "closed")
            self.assertTrue(self.root.exists(), "Repository main checkout remains preserved")
            self.assertEqual(self.git(self.root, "branch", "--show-current"), "trunk")
        with self.world(integrated=False):
            plan = self.plan()
            invoked = []
            result = self.apply(plan, native_cleanup=lambda request: invoked.append(request))
            self.blocked(result)
            self.assertEqual(invoked, [])
            self.assertTrue(self.source.exists())
            self.assertEqual(self.remote_tip(), self.head)
            with self.assertRaises(ValueError):
                self.guard.release(self.registry, "fixture", "Unmerged flight stays unfinished", policy=self.policy)

    def test_canonical_integration_replacements(self):
        # The provider OID stays I_bad. A local same-parent replacement may
        # change Git's interpreted tree, but cannot establish canonical proof.
        with self.world("squash"):
            self.env.pop("GIT_NO_REPLACE_OBJECTS", None)
            good = self.merge
            parent = self.git(self.root, "--no-replace-objects", "rev-parse", good + "^")
            self.commit(self.root, "later-good-target.txt")
            with patch.dict(os.environ):
                os.environ.pop("GIT_NO_REPLACE_OBJECTS", None)
                good_proof = self.life.integration_status(self.root, self.head, "trunk", delivery=self.delivery)
            self.assertIs(good_proof["verified"], True, good_proof)
            self.assertNotEqual(good_proof["target_tip"], good)
            bad_tree = self.git(self.root, "--no-replace-objects", "rev-parse", parent + "^{tree}")
            good_tree = self.git(self.root, "--no-replace-objects", "rev-parse", good + "^{tree}")
            bad = self.git(self.root, "commit-tree", bad_tree, "-p", parent, "-m", "Canonical lost source changes")
            replacement = self.git(self.root, "commit-tree", good_tree, "-p", parent, "-m", "Local preserving replacement")
            self.git(self.root, "reset", "--hard", bad)
            later = self.commit(self.root, "later-bad-target.txt")
            self.git(self.root, "push", "--quiet", "--force", "origin", "trunk:refs/heads/trunk")
            self.git(self.root, "replace", bad, replacement)
            self.assertEqual(self.remote_tip("refs/heads/trunk"), later)
            self.assertEqual(self.remote_tip(), self.head)
            self.assertEqual(self.git(self.root, "rev-parse", bad + "^{commit}"), bad)
            self.assertEqual(self.git(self.root, "--no-replace-objects", "show", "-s", "--format=%P", bad), parent)
            self.assertEqual(self.git(self.root, "--no-replace-objects", "show", "-s", "--format=%P", replacement), parent)
            canonical_tool = self.git(self.root, "--no-replace-objects", "ls-tree", bad, "tool.sh")
            canonical_old = self.git(self.root, "--no-replace-objects", "ls-tree", self.base, "tool.sh")
            source_tool = self.git(self.root, "--no-replace-objects", "ls-tree", self.head, "tool.sh")
            self.assertEqual(canonical_tool, canonical_old)
            self.assertTrue(canonical_tool.startswith("100644 "))
            self.assertTrue(source_tool.startswith("100755 "))
            self.assertNotEqual(canonical_tool.split()[2], source_tool.split()[2], "Canonical source bytes are lost")
            self.assertTrue(self.git(self.root, "--no-replace-objects", "ls-tree", bad, "obsolete.txt"))
            self.assertEqual(self.git(self.root, "--no-replace-objects", "ls-tree", self.head, "obsolete.txt"), "")
            self.assertEqual(self.git(self.root, "ls-tree", bad, "tool.sh"), source_tool,
                             "Unsuppressed native Git must actually read the preserving replacement")
            self.assertEqual(self.git(self.root, "ls-tree", bad, "obsolete.txt"), "")
            self.delivery["merge_commit"] = bad
            record = self.registry.get("fixture")
            record["delivery"]["head"] = self.head
            self.registry.save(record, expected_revision=self.registry.read()["revision"])
            provider = json.loads(self.provider_control.read_text())
            provider["pull"] = {"merged": True, "merge_commit_sha": bad,
                                "head": {"sha": self.head, "ref": self.topic, "repo": {"full_name": "fixture/repo"}},
                                "base": {"ref": "trunk", "repo": {"full_name": "fixture/repo"}}}
            self.provider_control.write_text(json.dumps(provider))
            gh = self.area / "tools/gh"
            text = gh.read_text()
            needle = " else:raise SystemExit('Unexpected provider request: '+e)"
            self.assertIn(needle, text)
            gh.write_text(text.replace(needle, " elif e=='repos/fixture/repo/pulls/181':v=c['pull']\n" + needle))
            def canonical_blocked(proof):
                self.assertIs(proof["verified"], False, proof)
                self.assertEqual(proof["merge_commit"], bad)
                self.assertEqual(proof["target_tip"], later)
                failures = {row["path"] for row in proof["changed_paths"] if not row["verified"]}
                self.assertTrue({"tool.sh", "obsolete.txt"}.issubset(failures), proof)
                self.assertTrue(any("bytes/mode/deletion" in reason for reason in proof["blockers"]), proof)
            before = self.snapshot()
            with patch.dict(os.environ):
                os.environ.pop("GIT_NO_REPLACE_OBJECTS", None)
                direct = self.life.integration_status(self.root, self.head, "trunk", delivery=self.delivery)
                canonical_blocked(direct)
                plan = self.plan()
                self.blocked(plan)
                canonical_blocked(plan["integration"])
                invoked = []
                applied = self.apply(plan, native_cleanup=lambda request: invoked.append(request))
                self.blocked(applied)
                canonical_blocked(applied["integration"])
                self.assertEqual(invoked, [], "Bad canonical proof must prevent even the native cleanup callback")
                status = self.life.closure_status(self.root, self.registry, "fixture", delivery=self.delivery,
                                                 policy=self.policy, client_state=self.client_state,
                                                 preservation=self.saved_assets)
                self.blocked(status)
                canonical_blocked(status["integration"])
                with self.assertRaisesRegex(ValueError, "bytes/mode/deletion"):
                    self.guard.release(self.registry, "fixture", "Cannot close replacement-influenced integration",
                                       policy=self.policy, control_checkout=self.root)
                # Audit already supplies its own canonical-object environment.
                report = self.audit()
                source = next(row for row in report["artifacts"] if row["kind"] == "worktree"
                              and row["identity"]["path"] == str(self.source))
                canonical_blocked(source["integration"])
            self.assertEqual(self.snapshot(), before)
            driver = self.area / "canonical-lifecycle-entry.py"
            driver.write_text('''import contextlib,runpy,sys
from pathlib import Path
product=Path(sys.argv[1]);route=sys.argv[2];arguments=sys.argv[3:]
if route=='source':
 sys.argv=[str(product/'setup/install.py'),'lifecycle',*arguments]
 runpy.run_path(sys.argv[0],run_name='__main__')
else:
 sys.path.insert(0,str(product/'src'))
 from flightcheck_cli import cli
 @contextlib.contextmanager
 def source_installer():
  yield cli.load_installer(product/'setup/install.py'),None,None,None
 cli.installer=source_installer
 raise SystemExit(cli.main(['lifecycle',*arguments]))
''')
            client = self.area / "canonical-client.json"
            client.write_text(json.dumps(self.client_state))
            assets = self.area / "canonical-assets.json"
            assets.write_text(json.dumps(self.saved_assets))
            plan_file = self.area / "canonical-blocked-plan.json"
            plan_file.write_text(json.dumps(plan))
            for route in ("source", "packaged"):
                for operation in ("plan", "apply", "status"):
                    arguments = [operation, "--checkout", str(self.root), "--registry", str(self.registry.directory),
                                 "--flight", "fixture", "--client-state", str(client), "--preservation", str(assets)]
                    if operation == "apply":
                        arguments += ["--plan", str(plan_file)]
                    result = subprocess.run([sys.executable, "-B", str(driver), str(PRODUCT), route, *arguments],
                                            cwd=self.root, env=dict(self.env),
                                            capture_output=True, text=True, timeout=40)
                    self.assertEqual(result.returncode, 2, route + ": " + result.stdout + result.stderr)
                    outcome = json.loads(result.stdout)
                    self.blocked(outcome)
                    canonical_blocked(outcome["integration"])
                    self.assertEqual(self.snapshot(), before, route + " " + operation)
            self.assertTrue(self.source.exists())
            self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), self.head)
            self.assertEqual(self.remote_tip(), self.head)
            self.assertNotEqual(self.registry.get("fixture")["lifecycle"]["state"], "closed")



if __name__ == "__main__":
    unittest.main()
