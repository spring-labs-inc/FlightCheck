"""Eight stable native acceptance identities for bounded checkout verification."""
import copy
import json
import socket
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from checkout_guard_cases import CheckoutCases, PRODUCT


class CheckoutGuardTests(CheckoutCases, unittest.TestCase):
    def test_native(self):
        for selection in ("branch", "worktree", "detached"):
            with self.subTest(selection=selection), self.fixture():
                if selection == "branch":
                    self.git(self.root, "switch", "-q", "-c", "ordinary-topic")
                    path = self.root
                else:
                    path = self.worktree(self.area / "selected", "ordinary-topic" if selection == "worktree" else None)
                before = self.preserved_state(path)
                with patch.object(self.guard.launch_detection, "detect", wraps=self.guard.launch_detection.detect) as detector:
                    report = self.adopt(path)
                self.assertTrue(detector.called, "Native adoption must consult delivered related-flight detection")
                self.assertEqual(report["status"], "verified")
                self.assertEqual(self.registry.get("fixture")["checkout"]["path"], str(path))
                self.assertEqual(self.preserved_state(path), before, "Adoption records ownership without rewriting Git or owner files")
                descendant = self.commit(path)
                current = self.verify(path)
                self.assertEqual(current["checkout"]["commit"], descendant)
                if selection == "detached":
                    self.assertIsNone(current["checkout"]["branch"])
                    with self.assertRaisesRegex(ValueError, "branch|detach"):
                        self.verify(path, phase="delivery")
        for linked in (False, True):
            with self.subTest(required_worktree=linked), self.fixture():
                self.git(self.root, "switch", "-q", "-c", "safe-topic")
                path = self.worktree(self.area / "linked", "linked-topic") if linked else self.root
                self.configure(path, checkout_policy={"mode": "worktree-required", "git_fallback": False})
                if linked:
                    self.assertEqual(self.adopt(path)["status"], "verified")
                else:
                    with self.assertRaisesRegex(ValueError, "worktree"):
                        self.adopt(path)
                    self.assertEqual(self.registry.read()["records"], [])

    def test_protection(self):
        for branch in ("trunk", "release"):
            with self.subTest(protected=branch), self.fixture():
                if branch != "trunk":
                    self.git(self.root, "switch", "-q", "-c", branch)
                before = self.preserved_state(self.root)
                with self.assertRaisesRegex(ValueError, "protect|default"):
                    self.adopt(self.root)
                self.assertEqual(self.preserved_state(self.root), before)
                self.assertEqual(self.registry.read()["records"], [])
        for mismatch in ("repository", "default", "new-protection", "policy-unavailable", "base", "root", "common", "unconfirmed"):
            with self.subTest(mismatch=mismatch), self.fixture():
                path = self.worktree(self.area / "selected", "topic")
                record = self.record(path)
                kwargs = {}
                if mismatch == "repository":
                    kwargs["policy"] = dict(self.policy, repository="other/repo")
                elif mismatch == "default":
                    kwargs["policy"] = dict(self.policy, default_branch="new-default")
                elif mismatch == "new-protection":
                    kwargs["policy"] = dict(self.policy, protected_branches=["trunk", "release", "topic"])
                elif mismatch == "policy-unavailable":
                    def unavailable(*args):
                        raise ValueError("provider policy unavailable")
                    kwargs["policy"] = unavailable
                elif mismatch == "base":
                    other = self.repo(self.area / "other")
                    self.commit(other)
                    kwargs["base"] = self.git(other, "rev-parse", "HEAD")
                elif mismatch == "root":
                    nested = path / "nested"; nested.mkdir(); path = nested
                elif mismatch == "common":
                    other = self.repo(self.area / "other")
                    record["repository"] = self.associations.repository_identity(other, "fixture/repo")
                else:
                    record["configuration"]["values"][self.config.META]["fields"]["default_branch"]["confirmed"] = False
                with self.assertRaises(ValueError):
                    self.adopt(path, record, **kwargs)
                self.assertEqual(self.registry.read()["records"], [])
        for dirty in ("tracked", "untracked", "index"):
            with self.subTest(existing_work=dirty), self.fixture():
                path = self.worktree(self.area / "selected", "topic")
                (path / ("untracked\nowner.txt" if dirty == "untracked" else "existing.txt")).write_text("owner unfinished bytes\n")
                if dirty == "index":
                    self.git(path, "add", "existing.txt")
                before = self.preserved_state(path)
                with self.assertRaisesRegex(ValueError, "dirty|existing|adopt|untracked"):
                    self.adopt(path)
                self.assertEqual(self.preserved_state(path), before)
                self.assertEqual(self.adopt(path, decision={"reference": "Owner explicitly adopts existing work", "adopt_existing": True})["status"], "verified")
                self.assertEqual(self.preserved_state(path), before)

        for provider_case in ("classic-match", "classic-nonmatch", "malformed", "unsupported-pattern"):
            with self.subTest(provider=provider_case), self.fixture():
                branch = "blocked/unpublished" if provider_case == "classic-match" else "safe/unpublished"
                path = self.worktree(self.area / "selected", branch)
                control = {"classic_patterns": ["[unterminated" if provider_case == "unsupported-pattern" else "blocked/*"],
                           "malformed": provider_case == "malformed"}
                self.provider_control.write_text(json.dumps(control))
                if provider_case == "classic-nonmatch":
                    self.assertEqual(self.adopt(path, policy=None)["status"], "verified")
                else:
                    before = self.preserved_state(path)
                    with self.assertRaisesRegex(ValueError, "protect|policy|pattern|provider|authoritative"):
                        self.adopt(path, policy=None)
                    self.assertEqual(self.registry.read()["records"], [])
                    self.assertEqual(self.preserved_state(path), before)
                reads = [json.loads(line) for line in self.provider_log.read_text().splitlines()]
                self.assertTrue(any("graphql" in call for call in reads), "Current classic protection must include unpublished branch patterns")
                if provider_case == "classic-match":
                    record_file, client_file, forged_file = (self.area / name for name in ("record.json", "client.json", "forged-policy.json"))
                    record_file.write_text(json.dumps(self.record(path)))
                    client_file.write_text(json.dumps(self.observation))
                    forged_file.write_text(json.dumps(dict(self.policy, protected_branches=[])))
                    spoof = subprocess.run([sys.executable, "-B", str(PRODUCT / "setup/install.py"), "checkout", "adopt",
                                            "--checkout", str(path), "--registry", str(self.registry.directory), "--record", str(record_file),
                                            "--base", self.base, "--client-observation", str(client_file), "--policy", str(forged_file)],
                                           cwd=path, env=self.env, capture_output=True, text=True, timeout=25)
                    self.assertNotEqual(spoof.returncode, 0, "CLI cannot accept supplied policy as provider authority: " + spoof.stdout + spoof.stderr)
                    self.assertEqual(self.registry.read()["records"], [])

    def test_ownership(self):
        with self.fixture():
            main = self.worktree(self.area / "main", "topic")
            child = self.worktree(self.area / "child")
            unrelated = self.worktree(self.area / "unrelated", "codex/looks-related")
            (unrelated / "existing.txt").write_text("unrelated unfinished work\n")
            self.adopt(main, self.record(main, children=[child]))
            self.assertEqual(self.verify(child)["status"], "verified")
            with self.assertRaises(ValueError):
                self.verify(unrelated)
            with self.assertRaisesRegex(ValueError, "own|unfinished|related|competing"):
                self.adopt(main, self.record(main, flight="competing"))
            self.assertEqual(len(self.registry.read()["records"]), 1)
            other = self.worktree(self.area / "other", "other")
            with self.assertRaisesRegex(ValueError, "related|decision|unfinished"):
                self.adopt(other, self.record(other, flight="same-issue"))
            separate = self.record(other, flight="separate")
            separate["issues"], separate["pull_requests"] = [999], []
            self.assertEqual(self.adopt(other, separate)["status"], "verified")
            self.assertEqual(len(self.registry.read()["records"]), 2)
        # Two independent processes compete for the same actual checkout; one wins.
        with self.fixture():
            path = self.worktree(self.area / "selected", "topic")
            script = self.area / "claim.py"
            script.write_text("import json,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(PRODUCT / "workflow/scripts")) + ")\nimport checkout_guard as g\nr=json.loads(Path(sys.argv[1]).read_text())\ntry:\n g.adopt(Path(r['checkout']['path']),Path(sys.argv[2]),r,base=sys.argv[3],client_observation=json.loads(sys.argv[4]),policy=json.loads(sys.argv[5]))\nexcept ValueError as e:\n print(str(e));sys.exit(2)\n")
            processes = []
            for flight in ("owner-a", "owner-b"):
                record_path = self.area / (flight + ".json"); record_path.write_text(json.dumps(self.record(path, flight)))
                processes.append(subprocess.Popen([sys.executable, "-B", str(script), str(record_path), str(self.registry.directory), self.base,
                                                   json.dumps(self.observation), json.dumps(self.policy)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            results = [(p.communicate(timeout=25), p.returncode) for p in processes]
            self.assertEqual(sorted(r[1] for r in results), [0, 2], results)
            self.assertEqual(len(self.registry.read()["records"]), 1)

        for authorized in (False, True):
            with self.subTest(manual_fallback=authorized), self.fixture():
                path = self.worktree(self.area / "manual", "manual-topic")
                if authorized:
                    self.configure(path, checkout_policy={"mode": "native-choice", "git_fallback": True,
                                                         "fallback_reference": "Owner grants bounded manual Git fallback"})
                record = self.record(path)
                record["checkout"]["management"] = "manual"
                manual = dict(self.observation, selection="manual", available=False)
                if authorized:
                    self.assertEqual(self.adopt(path, record, client_observation=manual)["status"], "verified")
                    self.assertEqual(self.registry.get("fixture")["checkout"]["management"], "manual")
                else:
                    with self.assertRaisesRegex(ValueError, "fallback|manual|native"):
                        self.adopt(path, record, client_observation=manual)
                    self.assertEqual(self.registry.read()["records"], [])

    def test_execution(self):
        with self.fixture():
            path = self.worktree(self.area / "selected", "topic")
            adopted = self.adopt(path)
            self.assertEqual(adopted["status"], "verified")
            marker = self.area / "valid-ran"
            probe = [sys.executable, "-B", "-c", "print('fixed native gate inputs')"]
            _, receipts = self.capture(path, marker, "--checkout-binding", json.dumps({"registry": str(self.registry.directory), "flight": "fixture"}),
                                       "--gate", "native", "--fingerprint-command", json.dumps(probe))
            self.assertTrue(marker.exists())
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_bytes())
            self.assertEqual(receipt["checkout_context"]["checkout"]["path"], str(path))
            self.assertEqual(receipt["checkout_context"]["checkout"]["commit"], self.base)
            self.assertEqual(receipt["checkout_context_after"]["head_binding"], receipt["checkout_context"]["head_binding"])
            self.assertEqual(self.handoff_gate_status(path, receipt)["status"], "reusable")
            descendant = self.commit(path)
            stale = self.handoff_gate_status(path, receipt)
            self.assertEqual(stale["status"], "stale")
            self.assertIn("checkout", stale["reason"])
            for command in self.checkout_commands(path):
                result = subprocess.run(command, cwd=path, env=self.env, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["checkout"]["commit"], descendant)
            self.git(path, "switch", "-q", "-c", "drifted")
            marker = self.area / "drift-must-not-run"
            result, _ = self.capture(path, marker, "--checkout-binding", json.dumps({"registry": str(self.registry.directory), "flight": "fixture"}), expected=1)
            self.assertFalse(marker.exists(), result.stdout + result.stderr)
            self.assertRegex(result.stdout + result.stderr, "branch|drift|checkout")
            for command in self.checkout_commands(path):
                result = subprocess.run(command, cwd=path, env=self.env, capture_output=True, text=True, timeout=25)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "blocked")
            provider_reads = [json.loads(line) for line in self.provider_log.read_text().splitlines()]
            self.assertTrue(provider_reads)
            self.assertTrue(all(("graphql" in args and args[args.index("--method") + 1] == "POST")
                                or args[args.index("--method") + 1] == "GET" for args in provider_reads))
            with self.assertRaises(ValueError):
                self.verify(path, phase="review")
            with self.assertRaises(ValueError):
                self.verify(path, phase="delivery")

        for drift in ("protected-branch", "session"):
            with self.subTest(automatic_owner=drift), self.fixture():
                path = self.worktree(self.area / "automatic-selected", "automatic-topic")
                nested = path / "src"
                nested.mkdir()
                # Use the delivered namespace and actual private Registry, with
                # no explicit binding in either invocation arguments or env.
                self.registry = self.guard.default_registry(path)
                self.adopt(path)
                probe_marker = self.area / "automatic-fingerprint-ran"
                probe = [sys.executable, "-B", "-c", "from pathlib import Path;Path(" + repr(str(probe_marker)) + ").write_text('probe');print('automatic inputs')"]
                safe_marker = self.area / "automatic-safe-ran"
                _, receipts = self.capture(path, safe_marker, "--gate", "automatic", "--fingerprint-command", json.dumps(probe))
                self.assertTrue(safe_marker.exists())
                receipt = json.loads(receipts[0].read_bytes())
                self.assertEqual(receipt["checkout_context"]["status"], "verified")
                self.assertEqual(receipt["checkout_context"]["checkout"]["path"], str(path))
                evidence = receipts[0].parent.parent
                task = {"candidate": "fixture-candidate", "gates": [{"id": "automatic", "request": receipt["request"]}]}
                packet = self.handoff_checks(path, evidence, task)
                self.assertEqual(packet.returncode, 0, packet.stdout + packet.stderr)
                self.assertEqual(json.loads(packet.stdout)["checkout_context"]["status"], "verified")
                nested_marker = self.area / "automatic-nested-must-not-run"
                self.capture(nested, nested_marker, expected=1)
                self.assertFalse(nested_marker.exists(), "Owned subdirectories cannot downgrade to an unbound recorder")
                packet = self.handoff_checks(nested, evidence, task)
                self.assertNotEqual(packet.returncode, 0, "Owned subdirectories cannot produce unbound handoff packets: " + packet.stdout + packet.stderr)
                if drift == "protected-branch":
                    self.git(path, "switch", "-q", "-c", "release")
                    unsafe_env = self.env
                else:
                    unsafe_env = dict(self.env, FLIGHTCHECK_CLIENT="codex", FLIGHTCHECK_SESSION="unassociated-session")
                for cwd in (path, nested):
                    with self.subTest(unsafe_directory=str(cwd)):
                        probe_marker.unlink(missing_ok=True)
                        marker = self.area / ("automatic-unsafe-" + cwd.name)
                        self.capture(cwd, marker, "--gate", "automatic", "--fingerprint-command", json.dumps(probe), expected=1, env=unsafe_env)
                        self.assertFalse(marker.exists(), "Automatic owner must block the native command before execution")
                        self.assertFalse(probe_marker.exists(), "Automatic owner must block the fingerprint before execution")
                        packet = self.handoff_checks(cwd, evidence, task, env=unsafe_env)
                        self.assertNotEqual(packet.returncode, 0, packet.stdout + packet.stderr)
                        self.assertFalse(probe_marker.exists(), "Unsafe handoff cannot execute a fingerprint or qualify its receipt")

        with self.subTest(copied_recorder_missing_selected_verifier=True), self.fixture():
            path = self.worktree(self.area / "selected-without-verifier", "copy-topic")
            nested = path / "src"
            nested.mkdir()
            self.registry = self.guard.default_registry(path)
            self.adopt(path)
            copied = self.copy_recorder()
            binding = {"registry": str(self.registry.directory), "flight": "fixture"}
            contexts = [("explicit-argument", path, ["--checkout-binding", json.dumps(binding)], self.env),
                        ("explicit-environment", path, [], dict(self.env, FLIGHTCHECK_REGISTRY=str(self.registry.directory), FLIGHTCHECK_FLIGHT="fixture")),
                        ("automatic-root", path, [], self.env), ("automatic-subdirectory", nested, [], self.env)]
            for name, cwd, options, environment in contexts:
                with self.subTest(missing_verifier=name):
                    probe_marker = self.area / (name + "-probe-must-not-run")
                    marker = self.area / (name + "-check-must-not-run")
                    probe = [sys.executable, "-B", "-c", "from pathlib import Path;Path(" + repr(str(probe_marker)) + ").write_text('probe');print('inputs')"]
                    self.capture(cwd, marker, *options, "--gate", "selected-missing-verifier", "--fingerprint-command", json.dumps(probe),
                                 helper=copied, env=environment, expected=1)
                    self.assertFalse(probe_marker.exists())
                    self.assertFalse(marker.exists())

    def test_resume(self):
        with self.fixture():
            path = self.worktree(self.area / "selected", "topic")
            self.adopt(path)
            initial = self.registry.get("fixture")
            self.assertEqual(self.verify(path, session="session-1")["status"], "verified")
            with self.assertRaisesRegex(ValueError, "session|client|reconcil"):
                self.verify(path, session="new-session")
            same_client = dict(self.observation, session="session-2")
            self.guard.reconcile(self.registry, "fixture", path, "Owner resumes in new session", client_observation=same_client, policy=self.policy)
            self.assertEqual(self.verify(path, session="session-2")["status"], "verified")
            cross = dict(self.observation, client="claude", session="claude-session")
            self.guard.reconcile(self.registry, "fixture", path, "Owner adopts in second client", client_observation=cross, policy=self.policy)
            resumed = self.registry.get("fixture")
            self.assertEqual((resumed["task"], resumed["card"], resumed["configuration"], resumed["grants"]),
                             (initial["task"], initial["card"], initial["configuration"], initial["grants"]))
            self.assertEqual(self.verify(path, session="claude-session")["status"], "verified")
            moved = self.area / "moved"
            self.git(self.root, "worktree", "move", str(path), str(moved))
            with self.assertRaises(ValueError):
                self.verify(path)
            with self.assertRaises(ValueError):
                self.verify(moved)
            with self.assertRaises(ValueError):
                self.guard.reconcile(self.registry, "fixture", moved, "", previous_path=str(path), policy=self.policy)
            self.guard.reconcile(self.registry, "fixture", moved, "Owner reconciles native move", previous_path=str(path), policy=self.policy)
            self.assertEqual(self.verify(moved)["checkout"]["path"], str(moved))
            saved = self.registry.get("fixture")
            self.assertEqual(saved["task"], initial["task"])
            self.assertTrue(saved.get("checkout_history") or saved.get("checkout_guard", {}).get("history"),
                            "Resume must retain prior checkout and client observations")
            self.git(moved, "switch", "-q", "-c", "restored-branch")
            with self.assertRaises(ValueError):
                self.verify(moved)
            self.guard.reconcile(self.registry, "fixture", moved, "Owner reconciles restored branch", policy=self.policy)
            self.assertEqual(self.verify(moved)["checkout"]["branch"], "restored-branch")

        with self.subTest(restored_path_is_another_repository=True), self.fixture():
            path = self.worktree(self.area / "selected", "topic")
            self.adopt(path)
            previous = self.registry.get("fixture")
            moved = self.area / "native-moved"
            self.git(self.root, "worktree", "move", str(path), str(moved))
            self.repo(path)
            self.git(path, "switch", "-q", "-c", "topic")
            self.configure(path)
            with self.assertRaisesRegex(ValueError, "repository|common|identity"):
                self.guard.reconcile(self.registry, "fixture", path, "Owner asks to reconcile restored path", policy=self.policy)
            self.assertEqual(self.registry.get("fixture"), previous)
            self.assertTrue((moved / "existing.txt").exists())
            self.assertTrue((path / "existing.txt").exists())

    def test_handoff(self):
        with self.fixture():
            main = self.worktree(self.area / "main", "topic")
            child = self.worktree(self.area / "child")
            (child / "untracked-owner.txt").write_text("retain child bytes\n")
            record = self.record(main, children=[child])
            record["lifecycle"]["disposition"] = "preserve for issue-81 owner audit"
            record["issues"] = [82, 83, 111]
            record["pull_requests"] = [182, 211]
            record["identity"] = {"label": "issue-83 identity", "provider_links": ["issue-111-association"]}
            observed = self.adopt(main, record, decision={"reference": "Owner adopts child work", "adopt_existing": True})
            before = {str(p): self.preserved_state(p) for p in (main, child)}
            old = self.registry.get("fixture")
            self.guard.release(self.registry, "fixture", "Owner closes execution ownership", policy=self.policy)
            closed = self.registry.get("fixture")
            self.assertEqual(closed["lifecycle"]["state"], "closed")
            self.assertEqual((observed["checkout"]["execution_host"], old["checkout"]["execution_host"],
                              closed["checkout"]["execution_host"], closed["checkout_guard"]["history"][-1]["checkout"]["execution_host"]),
                             (socket.gethostname(),) * 4,
                             "Actual execution host must reach the private report and retained association handoff")
            for key in ("task", "card", "issues", "pull_requests", "identity", "configuration", "grants", "children", "delivery"):
                self.assertEqual(closed[key], old[key], key)
            self.assertEqual(closed["checkout_guard"]["history"][-1]["previous_lifecycle"], old["lifecycle"])
            self.assertEqual({str(p): self.preserved_state(p) for p in (main, child)}, before)
            with self.assertRaises(ValueError):
                self.verify(main)
            fresh = self.record(main, "next-owner")
            self.assertEqual(self.adopt(main, fresh)["status"], "verified")

    def test_configuration(self):
        with self.fixture():
            path = self.worktree(self.area / "selected", "topic")
            self.adopt(path)
            old = self.registry.get("fixture")
            defaults = self.configure(path, checkout_policy={"mode": "worktree-required", "git_fallback": False})
            self.assertEqual(self.registry.get("fixture")["configuration"], old["configuration"])
            pinned = self.verify(path)
            self.assertEqual(pinned["status"], "verified")
            self.assertEqual(pinned["configuration_revision"], old["configuration"]["revision"])
            with self.assertRaises(ValueError):
                self.associations.reconfigure(old, defaults, "")
            updated = self.associations.reconfigure(old, defaults, "Owner explicit flight configuration")
            self.registry.save(updated, expected_revision=self.registry.read()["revision"])
            with self.assertRaisesRegex(ValueError, "config|revision|reconcil"):
                self.verify(path)
            self.guard.reconcile(self.registry, "fixture", path, "Owner revalidates configuration", policy=self.policy)
            current = self.registry.get("fixture")
            self.assertEqual(current["configuration"], defaults)
            self.assertEqual(current["configuration_history"], [old["configuration"]])
            self.assertEqual(current["grants"], old["grants"])
            self.assertEqual(self.verify(path)["status"], "verified")

    def test_compatibility(self):
        # This method intentionally never imports the new module. Identical tests
        # exercise the original bb4f0e3 public helpers and private Registry APIs.
        with self.fixture(guarded=False):
            path = self.worktree(self.area / "legacy", "topic")
            snapshot = self.config.snapshot(path)
            self.assertEqual(snapshot["values"]["checkout_policy"]["mode"], "native-choice")
            record = self.record(path)
            self.registry.save(record)
            self.assertEqual(self.registry.get("fixture"), record)
            self.assertEqual(self.registry.related("fixture/repo", issues=[82]), [record])
            self.assertEqual(self.registry.related("another/repo", issues=[82]), [])
            changed = self.configure(path, protected_branches=["release", "stable"])
            proposal = self.associations.reconfigure(record, changed, "Owner legacy helper change")
            self.registry.save(proposal, expected_revision=self.registry.read()["revision"])
            self.assertEqual(self.registry.get("fixture")["configuration_history"], [snapshot])
            self.assertEqual(self.registry.get("fixture")["grants"], record["grants"])
            sentinel = self.area / "legacy-ran"
            _, receipts = self.capture(path, sentinel)
            self.assertTrue(sentinel.exists())
            self.assertEqual(len(receipts), 1)
            receipt = json.loads(receipts[0].read_bytes())
            self.assertEqual(receipt["status"], "finished")
            self.assertEqual(receipt["exit_code"], 0)
            self.assertEqual(receipt["cwd"], str(path))
            copied = self.copy_recorder()
            copied_sentinel = self.area / "copied-standalone-ran"
            _, copied_receipts = self.capture(path, copied_sentinel, helper=copied)
            self.assertTrue(copied_sentinel.exists(), "A copied recorder with stdlib alone must retain its unbound standalone contract")
            self.assertEqual(len(copied_receipts), 1)
            standalone = json.loads(copied_receipts[0].read_bytes())
            self.assertEqual((standalone["status"], standalone["exit_code"], standalone["cwd"]), ("finished", 0, str(path)))


if __name__ == "__main__":
    unittest.main()
