"""Complete repository metadata audit with strict no-mutation witnesses."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import subprocess
from unittest.mock import patch
import unittest

from lifecycle_cases import LifecycleCases


class RepositoryAuditTests(LifecycleCases, unittest.TestCase):
    def artifact(self, report, kind, *, path=None, ref=None):
        matches = [row for row in report["artifacts"] if row["kind"] == kind
                   and (path is None or row["identity"].get("path") == str(path))
                   and (ref is None or row["identity"].get("ref") == ref)]
        self.assertEqual(len(matches), 1, {"kind": kind, "path": str(path), "ref": ref, "matches": matches})
        return matches[0]

    def assert_report(self, report):
        self.assertIs(report["read_only"], True)
        self.assertIs(report["cleanup_authorized"], False)
        self.assertTrue(report["artifacts"])
        self.assertEqual(len(report["recommendations"]), len(report["artifacts"]))
        for row in report["artifacts"]:
            self.assertIs(row["cleanup_authorized"], False)
            recommendation = row["recommendation"]
            self.assertIn(recommendation["classification"], ("preserve", "investigate", "cleanup_candidate"))
            self.assertTrue(recommendation["action"])
            self.assertTrue(recommendation["reason"])
            self.assertTrue(recommendation["prerequisites"])
            self.assertIs(recommendation["cleanup_authorized"], False)

    def test_inventory(self):
        with self.world():
            audit = self.feature("repository_audit")
            manual = self.worktree(self.area / "manual-unowned", "manual-unowned")
            (manual / "owner-untracked.txt").write_text("manual owner work\n")
            (manual / "existing.txt").write_text("dirty manual checkout\n")
            self.git(self.root, "worktree", "lock", str(manual), "--reason", "Manual live client")
            historic = self.area / "historic-clean"
            self.git(self.root, "worktree", "add", "-q", "-b", "historic-topic", str(historic), self.head)
            old = copy.deepcopy(self.registry.get("fixture"))
            old.update(flight="historic-flight", task="historic-task", card="historic-card", issues=[999], pull_requests=[182])
            old.pop("cleanup", None)
            old.pop("checkout_guard", None)
            old["checkout"].update(path=str(historic), branch="historic-topic", commit=self.head)
            old["children"] = []
            old["grants"] = {"cleanup": [], "delivery": []}
            old["lifecycle"] = {"state": "closed", "disposition": "Historical ownership only; no cleanup grant"}
            old["delivery"] = {"target": "trunk"}
            self.registry.save(old, expected_revision=self.registry.read()["revision"])
            observed = {str(historic): {"available": True, "active": False,
                                        "source": "Fixture native inactivity observation",
                                        "observed_at": datetime.now(timezone.utc).isoformat()}}
            def fresh_provider(reader, root, repository, record, remotes, enabled):
                return dict(self.delivery, pull_request=182,
                            source="Fresh fixture provider observation") if record["flight"] == "historic-flight" else self.delivery
            before = self.snapshot([self.root, self.source, manual, historic, self.remote, self.registry.directory])
            with patch.object(audit, "_provider_delivery", side_effect=fresh_provider), patch.dict(os.environ, FC_AUDIT_READONLY="1"):
                report = audit.audit(self.root, self.registry, "fixture/repo", policy=self.policy,
                                     client_observations=observed)
            self.assert_report(report)
            self.assertEqual(self.snapshot([self.root, self.source, manual, historic, self.remote, self.registry.directory]), before)
            self.assertGreaterEqual(report["coverage"]["worktrees"]["count"], 4)
            for kind in ("worktree", "local_branch", "remote_branch", "remote_tracking_ref"):
                self.assertTrue(any(row["kind"] == kind for row in report["artifacts"]), kind)
            manual_row = self.artifact(report, "worktree", path=manual)
            self.assertTrue(manual_row["state"]["dirty"])
            self.assertEqual(manual_row["state"]["untracked"], ["owner-untracked.txt"])
            self.assertTrue(manual_row["state"]["locked"])
            self.assertEqual(manual_row["owners"], [])
            self.assertEqual(manual_row["recommendation"]["classification"], "preserve")
            main = self.artifact(report, "worktree", path=self.root)
            self.assertTrue(main["repository_main"])
            self.assertEqual(main["recommendation"]["classification"], "preserve")
            candidate = self.artifact(report, "worktree", path=historic)
            self.assertIs(candidate["integration"]["verified"], True, candidate)
            self.assertEqual(candidate["recommendation"]["classification"], "cleanup_candidate")
            self.assertIs(candidate["cleanup_authorized"], False)
            for branch in (row for row in report["artifacts"] if row["kind"] == "local_branch"):
                self.assertNotIn("dirty", branch["state"], "Uncommitted work belongs to a checkout, not a branch")
                self.assertNotIn("untracked", branch["state"])
                self.assertIn("unmerged", branch["branch_indicators"])
                self.assertIn("unpushed", branch["branch_indicators"])

    def test_readonly(self):
        # An explicit audit is a normal read-only entrypoint, even on the actual
        # default branch with no active flight and an absent Registry.
        with self.fixture():
            self.feature("repository_audit")
            self.prepare_base()
            self.transport()
            self.topic = "manual-topic"
            self.source = self.worktree(self.area / "manual", self.topic)
            private = self.source / ".env"
            private.write_text("PRIVATE_CONFIG_CONTENT_SENTINEL_81\n")
            marker = self.area / "configured-command-must-not-run"
            self.configure(self.root, checks=[{"name": "recorded-only", "phase": "cheap", "command":
                [sys.executable, "-B", "-c", "from pathlib import Path;Path(" + repr(str(marker)) + ").write_text('bad')"]}])
            self.assertEqual(self.git(self.root, "branch", "--show-current"), "trunk")
            self.assertFalse(self.registry.directory.exists())
            before = self.snapshot()
            for route, report in self.audit_routes(private_file=private):
                self.assert_report(report)
                self.assertEqual(self.snapshot(), before, route)
                self.assertFalse(self.registry.directory.exists(), "Read-only audit must not create ownership storage")
                self.assertFalse(marker.exists(), "Recorded project commands remain data during audit")
                self.assertNotIn("PRIVATE_CONFIG_CONTENT_SENTINEL_81", json.dumps(report))
                row = self.artifact(report, "worktree", path=self.source)
                self.assertGreaterEqual(row["state"]["ignored_count"], 1)
                self.assertFalse((self.root / ".git/FETCH_HEAD").exists())
            calls = [json.loads(line) for line in self.git_calls.read_text().splitlines()]
            forbidden = {"fetch", "prune", "checkout", "switch", "stash", "commit", "reset", "clean"}
            # The shim independently refuses writes inside all three CLI
            # processes; inspect their actual observation calls as well.
            observed = [row["args"] for row in calls if row["readonly"]]
            self.assertTrue(observed, "Every public audit route must expose its actual native observations")
            self.assertFalse(any(any(value in forbidden for value in args) for args in observed))
            self.assertFalse(any("worktree" in args and any(value in args for value in ("remove", "prune", "lock", "unlock"))
                                 for args in observed))

    def test_coverage(self):
        with self.world():
            audit = self.feature("repository_audit")
            h1 = self.advance_remote()
            before = self.snapshot()
            with patch.dict(os.environ, FC_AUDIT_READONLY="1"):
                report = audit.audit(self.root, self.registry, "fixture/repo", policy=self.policy)
            self.assert_report(report)
            remote = self.artifact(report, "remote_branch", ref="refs/heads/" + self.topic)
            cached = self.artifact(report, "remote_tracking_ref", ref="refs/remotes/origin/" + self.topic)
            self.assertEqual(remote["identity"]["oid"], h1)
            self.assertIs(remote["state"]["object_available"], False)
            self.assertIs(remote["integration"]["verified"], False)
            self.assertIn("absent locally", json.dumps(remote["integration"]))
            self.assertEqual(cached["identity"]["oid"], self.head)
            self.assertEqual(cached["state"]["advertised_oid"], h1)
            self.assertIs(cached["state"]["stale"], True)
            self.assertTrue(any(row["active"]["native"] == "unknown" for row in report["artifacts"]))
            self.assertFalse(any(row["kind"] in ("worktree", "recorded_checkout") and row["active"]["native"] == "unknown"
                                 and row["recommendation"]["classification"] == "cleanup_candidate"
                                 for row in report["artifacts"]))
            self.assertEqual(self.snapshot(), before)
            with patch.dict(os.environ, FC_AUDIT_READONLY="1", FC_REMOTE_UNAVAILABLE="1"):
                failed_remote = audit.audit(self.root, self.registry, "fixture/repo", policy=self.policy)
            self.assertTrue(any(not row["available"] and row.get("reason") for row in failed_remote["coverage"]["remotes"]))
            self.assertFalse(any(row["kind"] == "remote_branch" for row in failed_remote["artifacts"]))
            self.assertTrue(any(row["kind"] == "remote_tracking_ref" for row in failed_remote["artifacts"]))
            prior_calls = len(self.git_calls.read_text().splitlines())
            with patch.dict(os.environ, FC_AUDIT_READONLY="1"):
                offline = audit.audit(self.root, self.registry, "fixture/repo", remote=False, policy=self.policy)
            self.assertTrue(any(not row["available"] for row in offline["coverage"]["remotes"]))
            self.assertTrue(all(row.get("reason") for row in offline["coverage"]["remotes"]))
            offline_calls = [json.loads(line)["args"] for line in self.git_calls.read_text().splitlines()[prior_calls:]]
            self.assertFalse(any("ls-remote" in args for args in offline_calls))
            self.assertEqual(self.snapshot(), before)

    def test_authority(self):
        # C4 through every entry route: real H1 is absent locally, cached H0 is
        # stale, a manual checkout has private data, and a historical handoff
        # supplies no cleanup grant. The audit can report, never authorize.
        with self.world():
            self.feature("repository_audit")
            manual = self.worktree(self.area / "manual81", "manual81")
            private = manual / ".env"
            private.write_text("PRIVATE_IGNORED_CONTENT_81_NEVER_READ\n")
            historic = copy.deepcopy(self.registry.get("fixture"))
            historic.update(flight="historical-flight81", task="historical-task81", card="historical-card81")
            historic.pop("cleanup", None)
            historic.pop("checkout_guard", None)
            historic["checkout"].update(path=str(self.area / "old-removed-flight81"), branch="manual81")
            historic["grants"] = {"cleanup": [], "delivery": []}
            historic["lifecycle"] = {"state": "closed", "disposition": "Historical handoff; not a deletion grant"}
            self.registry.save(historic, expected_revision=self.registry.read()["revision"])
            h1 = self.advance_remote()
            self.assertFalse(self.object_exists(h1))
            before = self.snapshot([self.root, self.source, manual, self.remote, self.registry.directory])
            for route, report in self.audit_routes(private_file=private):
                self.assert_report(report)
                self.assertEqual(self.snapshot([self.root, self.source, manual, self.remote, self.registry.directory]), before, route)
                self.assertNotIn("PRIVATE_IGNORED_CONTENT_81_NEVER_READ", json.dumps(report))
                manual_row = self.artifact(report, "worktree", path=manual)
                self.assertEqual(manual_row["owners"], [])
                self.assertGreaterEqual(manual_row["state"]["ignored_count"], 1)
                self.assertEqual(manual_row["recommendation"]["classification"], "preserve")
                actual = self.artifact(report, "remote_branch", ref="refs/heads/" + self.topic)
                self.assertEqual(actual["identity"]["oid"], h1)
                self.assertIs(actual["state"]["object_available"], False)
                self.assertIs(actual["integration"]["verified"], False)
                cached = self.artifact(report, "remote_tracking_ref", ref="refs/remotes/origin/" + self.topic)
                self.assertEqual(cached["identity"]["oid"], self.head)
                self.assertEqual(cached["state"]["advertised_oid"], h1)
                self.assertTrue(all(row["cleanup_authorized"] is False for row in report["recommendations"]))
            with self.assertRaises(ValueError):
                self.life.register_cleanup(self.root, self.registry, "historical-flight81",
                                           inventory=[{"kind": "worktree", "identity": str(manual)}],
                                           reference="Historical handoff is not a grant")
            self.assertTrue(manual.exists())
            self.assertEqual(self.remote_tip(), h1)

    def trace_fetches(self, trace):
        if not trace.exists():
            return []
        return [row for line in trace.read_text().splitlines() if line.strip()
                for row in [json.loads(line)]
                if (row.get("event") == "child_start" and "fetch" in row.get("argv", []))
                or (row.get("event") == "cmd_name" and row.get("name") == "fetch")]

    def test_promisor_no_hydration(self):
        # Real partial clones qualify both native implicit-fetch detection and
        # the shared integration subprocess, rather than mocking Git's result.
        with self.fixture():
            self.feature("repository_audit")
            life = self.feature("flight_lifecycle")
            self.prepare_base()
            self.transport()
            original = self.root
            self.git(self.remote, "config", "uploadpack.allowFilter", "true")
            self.git(self.remote, "config", "uploadpack.allowAnySHA1InWant", "true")
            clones = [self.area / "partial-audit", self.area / "partial-control"]
            for clone in clones:
                result = subprocess.run([self.real_git, "clone", "--quiet", "--filter=blob:none",
                                         self.remote.as_uri(), str(clone)], env=self.env, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.git(clone, "config", "--get", "remote.origin.promisor"), "true")
                self.assertEqual(self.git(clone, "config", "--get", "remote.origin.partialclonefilter"), "blob:none")
            actor = self.area / "promisor-actor"
            result = subprocess.run([self.real_git, "clone", "--quiet", str(self.remote), str(actor)],
                                    env=self.env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.git(actor, "config", "user.name", "Promisor fixture")
            self.git(actor, "config", "user.email", "fixture@example.invalid")
            self.git(actor, "config", "core.hooksPath", os.devnull)
            self.git(actor, "config", "commit.gpgsign", "false")
            missing = self.commit(actor, "promised-proof.txt")
            self.git(actor, "push", "--quiet", "origin", "HEAD:refs/heads/trunk")
            self.root = self.source = clones[0]
            self.configure(self.root)
            self.git(self.root, "remote", "add", "metadata", "https://github.com/fixture/repo.git")
            head = self.git(self.root, "rev-parse", "HEAD")
            self.assertNotEqual(head, missing)
            def object_available(checkout):
                result = subprocess.run([self.real_git, "--no-optional-locks", "-C", str(checkout),
                                         "cat-file", "-e", missing + "^{commit}"], capture_output=True,
                                        env=dict(self.env, GIT_NO_LAZY_FETCH="1"))
                return result.returncode == 0
            self.assertFalse(object_available(self.root))
            self.assertFalse(object_available(clones[1]))
            # Unsuppressed native read is a positive sensitivity control. It
            # must expose Git's descendant fetch AND change the object store.
            control_trace = self.area / "control-trace.jsonl"
            control_before = self.snapshot([clones[1]])
            control = subprocess.run([self.real_git, "--no-optional-locks", "-C", str(clones[1]),
                                      "cat-file", "-e", missing + "^{commit}"], capture_output=True,
                                     env=dict(self.env, GIT_NO_LAZY_FETCH="0", GIT_TRACE2_EVENT=str(control_trace)))
            self.assertEqual(control.returncode, 0, control.stderr)
            self.assertTrue(self.trace_fetches(control_trace), "Control must expose a real descendant implicit fetch")
            self.assertTrue(object_available(clones[1]), "Unsuppressed control must actually hydrate H1")
            self.assertNotEqual(self.snapshot([clones[1]]), control_before)
            record = self.record(self.root)
            record["issues"], record["pull_requests"] = [81], [181]
            record["checkout_guard"] = {"base": {"commit": head}}
            record["delivery"] = {"target": "refs/remotes/metadata/trunk", "head": head}
            self.registry.save(record, expected_revision=self.registry.read()["revision"])
            provider = json.loads(self.provider_control.read_text())
            provider["pull"] = {"merged": True, "merge_commit_sha": missing,
                                "head": {"sha": head, "ref": "trunk", "repo": {"full_name": "fixture/repo"}},
                                "base": {"ref": "trunk", "repo": {"full_name": "fixture/repo"}}}
            self.provider_control.write_text(json.dumps(provider))
            gh = self.area / "tools/gh"
            text = gh.read_text()
            needle = " else:raise SystemExit('Unexpected provider request: '+e)"
            self.assertIn(needle, text)
            gh.write_text(text.replace(needle, " elif e=='repos/fixture/repo/pulls/181':v=c['pull']\n" + needle))
            # Audit intentionally sanitizes inherited trace variables. Inject
            # tracing in the external native Git wrapper after that boundary.
            trace = self.area / "audit-promisor-trace.jsonl"
            shim = self.area / "tools/git"
            text = shim.read_text()
            needle = "raise SystemExit(subprocess.call("
            self.assertIn(needle, text)
            shim.write_text(text.replace(needle, "os.environ['GIT_TRACE2_EVENT']=" + repr(str(trace)) + "\n" + needle))
            trace.write_text("")
            before = self.snapshot([self.root, self.remote, self.registry.directory])
            delivery = {"repository": "fixture/repo", "merged": True, "source_base": head,
                        "head": head, "merge_commit": missing, "target": "trunk", "pull_request": 181}
            with patch.dict(os.environ, GIT_NO_LAZY_FETCH="0"):
                shared = life.integration_status(self.root, head, "trunk", delivery=delivery,
                                                 remote_observation={"available": True, "target_tip": missing})
            self.assertIs(shared["verified"], False, shared)
            self.assertIn("unavailable", json.dumps(shared).lower())
            self.assertFalse(self.trace_fetches(trace), "Shared integration must not fetch missing promisor objects")
            self.assertFalse(object_available(self.root))
            self.assertEqual(self.snapshot([self.root, self.remote, self.registry.directory]), before)
            trace.write_text("")
            with patch.dict(self.env, GIT_NO_LAZY_FETCH="0"):
                for route, report in self.audit_routes():
                    self.assert_report(report)
                    self.assertFalse(self.trace_fetches(trace), route + ": implicit descendant fetch attempted")
                    self.assertFalse(object_available(self.root), route + ": missing H1 was hydrated")
                    self.assertEqual(self.snapshot([self.root, self.remote, self.registry.directory]), before, route)
                    branches = [row for row in report["artifacts"] if row["kind"] == "remote_branch"
                                and row["identity"]["oid"] == missing]
                    self.assertTrue(branches, route)
                    self.assertTrue(all(row["state"]["object_available"] is False for row in branches), route)
                    self.assertTrue(all(row["integration"]["verified"] is False for row in branches), route)
                    self.assertTrue(all("absent locally" in json.dumps(row["integration"]) for row in branches), route)
                    owner = self.artifact(report, "worktree", path=self.root)
                    self.assertIs(owner["integration"]["verified"], False, owner)
                    self.assertIn("unavailable", json.dumps(owner["integration"]).lower())
                    self.assertTrue(any(row.get("merge_commit") == missing for row in [owner["integration"]]),
                                    "Fresh fixture delivery must reach shared integration object probes")
                    trace.write_text("")
            self.assertTrue(original.exists(), "The unrelated fixture source remains preserved")

    def test_worktree_configured_remote(self):
        with self.fixture():
            self.feature("repository_audit")
            self.prepare_base()
            self.transport()
            main = self.root
            self.source = self.worktree(self.area / "configured-worktree", "configured-worktree")
            extra = self.area / "worktree-only-remote.git"
            result = subprocess.run([self.real_git, "clone", "--bare", "--quiet", str(self.remote), str(extra)],
                                    env=self.env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            unique = "refs/heads/only-in-worktree-remote"
            self.git(extra, "update-ref", unique, self.base)
            self.assertIsNone(self.remote_tip(unique))
            self.git(main, "config", "extensions.worktreeConfig", "true")
            self.git(self.source, "config", "--worktree", "remote.worktree-only.url", str(extra))
            self.git(self.source, "config", "--worktree", "remote.worktree-only.fetch",
                     "+refs/heads/*:refs/remotes/worktree-only/*")
            self.run_git(self.source, "config", "--local", "--get", "remote.worktree-only.url", expected=1)
            self.assertEqual(self.git(self.source, "remote", "get-url", "worktree-only"), str(extra))
            self.root = self.source
            before = self.snapshot([main, self.source, self.remote, extra, self.registry.directory])
            for route, report in self.audit_routes():
                self.assert_report(report)
                self.assertEqual(self.snapshot([main, self.source, self.remote, extra, self.registry.directory]), before, route)
                coverage = [row for row in report["coverage"]["remotes"] if row["remote"] == "worktree-only"]
                self.assertTrue(coverage, route + ": discoverable worktree-only remote silently omitted")
                self.assertTrue(all(row.get("endpoint") == str(extra) for row in coverage), coverage)
                available = [row for row in coverage if row["available"]]
                if available:
                    rows = [row for row in report["artifacts"] if row["kind"] == "remote_branch"
                            and row["identity"]["remote"] == "worktree-only" and row["identity"]["ref"] == unique]
                    self.assertEqual(len(rows), 1, route)
                    self.assertEqual(rows[0]["identity"]["endpoint"], str(extra))
                    self.assertEqual(rows[0]["identity"]["oid"], self.base)
                    self.assertEqual(rows[0]["owners"], [])
                    self.assertIs(rows[0]["cleanup_authorized"], False)
                else:
                    self.assertTrue(all(row.get("reason") for row in coverage), "Unavailable endpoint needs an explicit limitation")



if __name__ == "__main__":
    unittest.main()
