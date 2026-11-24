"""Native specification witnesses for the bounded flight-association foundation."""

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from unittest.mock import patch

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))


class FlightCases:
    def flight_modules(self):
        modules = []
        for name in ("flight_associations", "launch_detection"):
            path = PRODUCT / "workflow/scripts" / (name + ".py")
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            previous = sys.modules.get(name)
            sys.modules[name] = module
            self.addCleanup(lambda n=name, p=previous: sys.modules.pop(n, None) if p is None else sys.modules.__setitem__(n, p))
            spec.loader.exec_module(module)
            modules.append(module)
        return modules

    def flight_git(self, root, *args):
        return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args],
            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                     GIT_TERMINAL_PROMPT="0"), stderr=subprocess.PIPE, text=True).strip()

    def flight_repo(self, root):
        root.mkdir()
        self.flight_git(root, "init", "-q", "-b", "trunk")
        self.flight_git(root, "config", "user.name", "Foundation fixture")
        self.flight_git(root, "config", "user.email", "fixture@example.invalid")
        self.flight_git(root, "config", "core.hooksPath", os.devnull)
        (root / "existing.txt").write_text("existing\n")
        self.flight_git(root, "add", ".")
        self.flight_git(root, "commit", "-qm", "Existing fixture")
        return root

    def flight_checkout(self, root, path, branch=None):
        args = ["worktree", "add", "-q"]
        args += ["-b", branch] if branch else ["--detach"]
        self.flight_git(root, *args, str(path), "HEAD")
        return path

    def flight_snapshot(self, **values):
        result = {"default_branch": "trunk", "protected_branches": ["trunk"],
                  "checkout_policy": {"mode": "native-choice", "git_fallback": False},
                  "checks": [{"name": "native", "command": ["python3", "-B", "check.py"], "phase": "cheap"}]}
        result.update(values)
        revision = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return {"revision": revision, "values": result}

    def flight_record(self, associations, repo, checkout, flight="foundation", repository="owner/repo", children=()):
        def item(path, kind):
            branch = subprocess.run(["git", "--no-optional-locks", "-C", str(path), "symbolic-ref", "--quiet", "--short", "HEAD"], capture_output=True, text=True)
            return {"path": str(path), "kind": kind, "management": "native",
                    "branch": branch.stdout.strip() if branch.returncode == 0 else None,
                    "commit": self.flight_git(path, "rev-parse", "HEAD")}
        return {"schema": 1, "flight": flight, "task": flight, "card": flight,
                "repository": associations.repository_identity(repo, repository),
                "issues": [84], "pull_requests": [200], "client": {"name": "codex", "sessions": ["fixture-session"]},
                "checkout": item(checkout, "preserved-existing"),
                "children": [item(path, "disposable-temporary") for path in children],
                "configuration": self.flight_snapshot(), "grants": {"delivery": [], "cleanup": []},
                "lifecycle": {"state": "active", "disposition": "pending"}, "delivery": {"target": "trunk"}}

    def test_flight_revision_binding(self):
        associations, _ = self.flight_modules()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = self.flight_repo(home / "repo")
            checkout = self.flight_checkout(repo, home / "flight", "topic")
            registry = associations.Registry(home / "private")
            initial = self.flight_record(associations, repo, checkout)
            registry.save(initial)
            defaults = self.flight_snapshot(checkout_policy={"mode": "worktree-required", "git_fallback": False},
                                            checks=[{"name": "new check", "command": ["changed"], "phase": "authoritative"}],
                                            delivery="merge everything", cleanup="remove everything")
            # Inspect during the project-default change, before reconfiguration.
            resumed = associations.Registry(home / "private").get("foundation")
            self.assertEqual(resumed["configuration"], initial["configuration"])
            self.assertEqual(resumed["grants"], {"delivery": [], "cleanup": []})
            with self.assertRaises(ValueError):
                associations.reconfigure(resumed, defaults, "")
            forbidden = copy.deepcopy(resumed)
            forbidden["configuration"] = defaults
            with self.assertRaisesRegex(ValueError, "reconfiguration"):
                registry.save(forbidden, expected_revision=registry.read()["revision"])
            updated = associations.reconfigure(resumed, defaults, "Owner explicit reconfiguration")
            self.assertEqual(updated["configuration"], defaults)
            self.assertEqual(updated["grants"], resumed["grants"])
            self.assertEqual(updated["configuration_history"], [initial["configuration"]])
            self.assertEqual(updated["reconfiguration"]["required_revalidation"], ["checkout", "checks", "evidence"])
            self.assertEqual(registry.get("foundation")["configuration"], initial["configuration"],
                             "A proposal must not silently persist a reconfiguration")
            previous = registry.read()["revision"]
            registry.save(updated, expected_revision=previous)
            fresh = associations.Registry(home / "private").get("foundation")
            self.assertEqual(fresh["configuration"], defaults)
            self.assertEqual(fresh["grants"], {"delivery": [], "cleanup": []})
            self.assertEqual(initial["configuration"], resumed["configuration"], "Inputs stay immutable")

    def test_association_contract(self):
        associations, _ = self.flight_modules()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = self.flight_repo(home / "repo-a")
            checkout = self.flight_checkout(repo, home / "flight-a", "topic")
            child = self.flight_checkout(repo, home / "child")
            other = self.flight_repo(home / "repo-b")
            other_checkout = self.flight_checkout(other, home / "flight-b", "topic")
            registry = associations.Registry(home / "private")
            self.assertEqual(registry.read(), {"revision": None, "records": []})
            self.assertFalse((home / "private").exists(), "Read-only lookup must not create storage")
            record = self.flight_record(associations, repo, checkout, children=[child])
            first = registry.save(record)
            self.assertEqual(registry.related("another/repo", issues=[84]), [])
            fresh = associations.Registry(home / "private").related("owner/repo", issues=[84])[0]
            self.assertEqual(fresh["children"][0]["branch"], None)
            self.assertEqual(fresh["children"][0]["kind"], "disposable-temporary")
            self.assertEqual(fresh["checkout"]["kind"], "preserved-existing")
            self.assertEqual(fresh["task"], fresh["card"])
            self.assertEqual(stat.S_IMODE((home / "private").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(registry.path.stat().st_mode), 0o600)
            colliding = copy.deepcopy(record)
            colliding["flight"] = colliding["task"] = colliding["card"] = "competing"
            before = registry.path.read_bytes()
            with self.assertRaisesRegex(ValueError, "already owned"):
                registry.save(colliding, expected_revision=first["revision"])
            self.assertEqual(registry.path.read_bytes(), before)
            second = self.flight_record(associations, other, other_checkout, "other", "another/repo")
            registry.save(second, expected_revision=first["revision"])
            self.assertEqual([r["flight"] for r in registry.related("owner/repo", issues=[84])], ["foundation"])
            self.assertEqual([r["flight"] for r in registry.related("another/repo", issues=[84])], ["other"])
            with self.assertRaisesRegex(ValueError, "Stale"):
                registry.save(record, expected_revision=first["revision"])
            invalid = copy.deepcopy(record)
            invalid["configuration"]["values"]["checkout_policy"] = "native-choice"
            with self.assertRaisesRegex(ValueError, "checkout_policy"):
                associations.validate_record(invalid)
            with self.assertRaisesRegex(ValueError, "outside"):
                associations.Registry(checkout / "private").save(record)
            # A partial write before atomic replace leaves complete prior state.
            before = registry.path.read_bytes()
            with patch.object(associations.os, "replace", side_effect=OSError("injected publication failure")):
                with self.assertRaisesRegex(OSError, "publication"):
                    registry.save(record, expected_revision=registry.read()["revision"])
            self.assertEqual(associations.Registry(home / "private").read()["revision"], hashlib.sha256(before).hexdigest())
            self.assertEqual(registry.path.read_bytes(), before)

    def test_related_launch_detection(self):
        associations, launch = self.flight_modules()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = self.flight_repo(home / "repo")
            related = self.flight_checkout(repo, home / "related", "topic")
            unrelated = self.flight_checkout(repo, home / "unrelated", "another-topic")
            child = self.flight_checkout(repo, home / "child")
            (related / "new.txt").write_text("unfinished commit\n")
            self.flight_git(related, "add", "new.txt")
            self.flight_git(related, "commit", "-qm", "Unmerged flight work")
            (related / "untracked\nfile.txt").write_text("preserve me\n")
            (related / "existing.txt").write_text("dirty tracked\n")
            (unrelated / "existing.txt").write_text("unrelated unfinished work\n")
            registry = associations.Registry(home / "private")
            record = self.flight_record(associations, repo, related, children=[child])
            registry.save(record)
            common = Path(record["repository"]["git_common_dir"])
            def file_identity(path):
                metadata = path.stat()
                return (hashlib.sha256(path.read_bytes()).hexdigest(), metadata.st_mode,
                        metadata.st_size, metadata.st_mtime_ns)
            def git_state():
                return {str(p.relative_to(common)): file_identity(p)
                        for p in common.rglob("*") if p.is_file() and not p.is_symlink()}
            def working_state():
                return {str(p): file_identity(p) for checkout in (repo, related, unrelated, child)
                        for p in checkout.rglob("*") if p.is_file() and not p.is_symlink()
                        and ".git" not in p.relative_to(checkout).parts}
            before = git_state()
            working_before = working_state()
            calls = []
            real_git = launch.git
            def observed_git(root, *args):
                calls.append(args)
                return real_git(root, *args)
            with patch.object(launch, "git", side_effect=observed_git):
                result = launch.detect(repo, registry, "owner/repo", issues=[84], current_flight="foundation")
                clear = launch.detect(repo, registry, "owner/repo", issues=[999])
            command = [sys.executable, "-B", str(PRODUCT / "workflow/scripts/launch_detection.py"),
                       "--checkout", str(repo), "--registry", str(home / "private"),
                       "--repository", "owner/repo", "--issue", "84", "--current-flight", "foundation"]
            public = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(public.returncode, 0, public.stderr)
            self.assertEqual(json.loads(public.stdout)["related"][0]["decision"]["action"], "resume")
            with self.assertRaisesRegex(ValueError, "positive"):
                launch.detect(repo, registry, "owner/repo", issues=[-1])
            self.assertEqual(git_state(), before, "Launch observations must not mutate Git bytes/modes/mtime")
            self.assertEqual(working_state(), working_before, "Launch observations must preserve checkout bytes/modes/mtime")
            self.assertFalse(any(args[0] in {"fetch", "prune", "checkout", "switch", "stash", "commit", "reset"} for args in calls))
            self.assertTrue(result["decision_required"])
            self.assertEqual(result["related"][0]["decision"]["action"], "resume")
            observation = result["related"][0]["checkouts"][0]
            self.assertTrue(observation["state"]["dirty"])
            self.assertEqual(observation["state"]["untracked"], ["untracked\nfile.txt"])
            self.assertEqual(observation["branch_state"]["unmerged"], {"available": True, "count": 1})
            self.assertFalse(observation["branch_state"]["unpushed"]["available"])
            self.assertIn("upstream", observation["branch_state"]["unpushed"]["reason"])
            detached = result["related"][0]["checkouts"][1]
            self.assertIsNone(detached["state"]["branch"])
            self.assertEqual(detached["branch_state"]["detached_commit"], record["children"][0]["commit"])
            self.assertFalse(clear["decision_required"])
            self.assertEqual(clear["related"], [])
            self.assertTrue(any(row["state"].get("dirty") for row in clear["other_worktrees"]))
            self.assertIn("Not queried", result["coverage"]["remote"])
            waiting = launch.detect(repo, registry, "owner/repo", issues=[84])
            self.assertEqual(waiting["related"][0]["decision"]["action"], "wait")
            self.flight_git(repo, "worktree", "lock", str(related), "--reason", "Active fixture session")
            locked = launch.detect(repo, registry, "owner/repo", issues=[84], current_flight="foundation")
            self.assertEqual(locked["related"][0]["decision"]["action"], "wait")
            self.assertTrue(locked["related"][0]["checkouts"][0]["locked"])
            self.flight_git(repo, "worktree", "unlock", str(related))
            self.flight_git(related, "switch", "-q", "-c", "drifted")
            drifted = launch.detect(repo, registry, "owner/repo", issues=[84], current_flight="foundation")
            self.assertTrue(drifted["related"][0]["checkouts"][0]["branch_drift"])
            self.assertEqual(drifted["related"][0]["decision"]["action"], "wait")
            self.assertFalse(drifted["related"][0]["checkouts"][0]["branch_state"]["available"])
            # The same path restored as another repository is unavailable, never attributed.
            wrong = copy.deepcopy(record)
            other_repo = self.flight_repo(home / "other-clone")
            wrong["checkout"]["path"] = str(other_repo)
            registry.save(wrong, expected_revision=registry.read()["revision"])
            mismatched = launch.detect(repo, registry, "owner/repo", issues=[84])
            self.assertFalse(mismatched["related"][0]["checkouts"][0]["state"]["available"])
            self.assertEqual(mismatched["related"][0]["decision"]["action"], "wait")
            missing = copy.deepcopy(wrong)
            missing["checkout"]["path"] = str(home / "missing-checkout")
            registry.save(missing, expected_revision=registry.read()["revision"])
            unavailable = launch.detect(repo, registry, "owner/repo", issues=[84], current_flight="foundation")
            self.assertFalse(unavailable["related"][0]["checkouts"][0]["state"]["available"])
            self.assertIn("missing", unavailable["related"][0]["checkouts"][0]["state"]["reason"])
            paused = copy.deepcopy(record)
            self.flight_git(related, "switch", "-q", "topic")
            paused["lifecycle"]["state"] = "paused"
            registry.save(paused, expected_revision=registry.read()["revision"])
            reusable = launch.detect(repo, registry, "owner/repo", pull_requests=[200])
            self.assertEqual(reusable["related"][0]["decision"]["action"], "reuse")


    def test_detached_checkout_identity_drift(self):
        associations, launch = self.flight_modules()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = self.flight_repo(home / "repo")
            related = self.flight_checkout(repo, home / "related", "topic")
            child = self.flight_checkout(repo, home / "child")
            registry = associations.Registry(home / "private")
            record = self.flight_record(associations, repo, related, children=[child])
            original_child = record["children"][0]["commit"]
            self.assertIsNone(record["children"][0]["branch"])
            registry.save(record)

            # Named-branch advancement remains ordinary unfinished flight work.
            (related / "named-advance.txt").write_text("legitimate flight commit\n")
            self.flight_git(related, "add", "named-advance.txt")
            self.flight_git(related, "commit", "-qm", "Named flight advancement")
            named = launch.detect(repo, registry, "owner/repo", issues=[84], current_flight="foundation")
            main = named["related"][0]["checkouts"][0]
            self.assertTrue(main["identity_changed"])
            self.assertFalse(main["branch_drift"])
            self.assertEqual(main["branch_state"]["unmerged"], {"available": True, "count": 1})
            self.assertEqual(named["related"][0]["decision"]["action"], "resume")

            # A detached checkout is identified by its recorded commit A.
            (child / "detached-advance.txt").write_text("unreconciled detached commit\n")
            self.flight_git(child, "add", "detached-advance.txt")
            self.flight_git(child, "commit", "-qm", "Detached state B")
            changed_child = self.flight_git(child, "rev-parse", "HEAD")
            self.assertNotEqual(changed_child, original_child)
            detached_branch = subprocess.run(["git", "--no-optional-locks", "-C", str(child),
                                               "symbolic-ref", "--quiet", "--short", "HEAD"],
                                              capture_output=True, text=True)
            self.assertNotEqual(detached_branch.returncode, 0)
            report = launch.detect(repo, registry, "owner/repo", issues=[84], current_flight="foundation")
            child_observation = report["related"][0]["checkouts"][1]
            self.assertEqual(child_observation["recorded_commit"], original_child)
            self.assertEqual(child_observation["state"]["commit"], changed_child)
            self.assertIsNone(child_observation["state"]["branch"])
            self.assertTrue(child_observation["identity_changed"])
            self.assertFalse(child_observation["branch_drift"])
            self.assertTrue(child_observation.get("detached_drift", False),
                            "A different detached commit must be reported as identity drift")
            self.assertFalse(child_observation["branch_state"]["available"])
            self.assertIn("reconcile", child_observation["branch_state"]["reason"])
            self.assertNotIn("unmerged", child_observation["branch_state"],
                             "Commit B must not be attributed to the recorded child at A")
            self.assertEqual(report["related"][0]["decision"]["action"], "wait")
            paused = copy.deepcopy(record)
            paused["lifecycle"]["state"] = "paused"
            registry.save(paused, expected_revision=registry.read()["revision"])
            paused_report = launch.detect(repo, registry, "owner/repo", issues=[84])
            self.assertEqual(paused_report["related"][0]["decision"]["action"], "wait",
                             "A paused flight must not reuse an unreconciled detached child")

    def flight_observation_state(self, common, checkouts):
        def identity(path):
            metadata = path.stat()
            return (hashlib.sha256(path.read_bytes()).hexdigest(), metadata.st_mode,
                    metadata.st_size, metadata.st_mtime_ns)
        git_files = {str(path.relative_to(common)): identity(path)
                     for path in common.rglob("*") if path.is_file() and not path.is_symlink()}
        working_files = {str(path): identity(path) for checkout in checkouts
                         for path in checkout.rglob("*") if path.is_file() and not path.is_symlink()
                         and ".git" not in path.relative_to(checkout).parts}
        return git_files, working_files

    def test_launch_one_shot_selectors(self):
        associations, launch = self.flight_modules()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = self.flight_repo(home / "repo")
            related = self.flight_checkout(repo, home / "related", "topic")
            (related / "unfinished.txt").write_text("preserve related work\n")
            registry = associations.Registry(home / "private")
            record = self.flight_record(associations, repo, related)
            registry.save(record)
            common = Path(record["repository"]["git_common_dir"])
            before = self.flight_observation_state(common, (repo, related))
            for selector, matched, unmatched in (("issues", 84, 999),
                                                  ("pull_requests", 200, 999),
                                                  ("flights", "foundation", "unmatched-flight")):
                with self.subTest(selector=selector, matching=True):
                    control = launch.detect(repo, registry, "owner/repo", current_flight="foundation",
                                            **{selector: [matched]})
                    self.assertTrue(control["decision_required"])
                    self.assertEqual([row["flight"] for row in control["related"]], ["foundation"])
                    self.assertEqual(control["related"][0]["decision"]["action"], "resume")
                    observed = launch.detect(repo, registry, "owner/repo", current_flight="foundation",
                                             **{selector: iter([matched])})
                    self.assertEqual(observed, control,
                                     "A one-shot selector must retain the list control's related decision")
                with self.subTest(selector=selector, matching=False):
                    control = launch.detect(repo, registry, "owner/repo", **{selector: [unmatched]})
                    observed = launch.detect(repo, registry, "owner/repo", **{selector: iter([unmatched])})
                    self.assertFalse(control["decision_required"])
                    self.assertEqual(control["related"], [])
                    self.assertEqual(observed, control, "Unmatched selectors remain nonblocking")
            self.assertEqual(self.flight_observation_state(common, (repo, related)), before,
                             "Selector observations must preserve Git and checkout bytes/modes/mtime")

    def test_launch_default_branch_tag_collision(self):
        associations, launch = self.flight_modules()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = self.flight_repo(home / "repo")
            related = self.flight_checkout(repo, home / "related", "topic")
            (related / "new.txt").write_text("unmerged flight work\n")
            self.flight_git(related, "add", "new.txt")
            self.flight_git(related, "commit", "-qm", "Topic ahead of default branch")
            self.assertEqual(self.flight_git(repo, "rev-list", "--count", "refs/heads/trunk..refs/heads/topic"), "1")
            registry = associations.Registry(home / "private")
            record = self.flight_record(associations, repo, related)
            record["delivery"] = {}  # Exercise the configured default, not an explicit delivery target.
            registry.save(record)
            common = Path(record["repository"]["git_common_dir"])

            def observe():
                before = self.flight_observation_state(common, (repo, related))
                result = launch.detect(repo, registry, "owner/repo", issues=[84], current_flight="foundation")
                self.assertEqual(self.flight_observation_state(common, (repo, related)), before,
                                 "Ref comparison must preserve Git and checkout bytes/modes/mtime")
                self.assertTrue(result["decision_required"])
                self.assertEqual(result["related"][0]["decision"]["action"], "resume")
                return result["related"][0]["checkouts"][0]["branch_state"]["unmerged"]

            with self.subTest(target="configured-default", colliding_tag=False):
                self.assertEqual(observe(), {"available": True, "count": 1})
            self.flight_git(repo, "tag", "trunk", "refs/heads/topic")
            self.assertEqual(self.flight_git(repo, "rev-parse", "refs/tags/trunk"),
                             self.flight_git(repo, "rev-parse", "refs/heads/topic"))
            self.assertNotEqual(self.flight_git(repo, "rev-parse", "refs/tags/trunk"),
                                self.flight_git(repo, "rev-parse", "refs/heads/trunk"))
            with self.subTest(target="configured-default", colliding_tag=True):
                self.assertEqual(observe(), {"available": True, "count": 1},
                                 "A same-named tag must not replace the configured default branch")
            qualified = copy.deepcopy(record)
            qualified["delivery"] = {"target": "refs/heads/trunk"}
            registry.save(qualified, expected_revision=registry.read()["revision"])
            with self.subTest(target="qualified-delivery", colliding_tag=True):
                self.assertEqual(observe(), {"available": True, "count": 1})
