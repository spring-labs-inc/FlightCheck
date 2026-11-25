"""Verified cleanup, accepted retention and persistent reservation witnesses."""
import copy
from pathlib import Path
from unittest.mock import patch
import unittest

from disposition_cases import DispositionCases


class VerifiedDispositionTests(DispositionCases, unittest.TestCase):
    def test_setup_policy(self):
        invalid = []
        value = self.retention_policy()
        value["authority"] = "agent"
        invalid.append(value)
        value = self.retention_policy()
        del value["allowed_reasons"]["native_unknown"]["next_action"]
        invalid.append(value)
        value = self.retention_policy()
        value["allowed_reasons"]["convenience"] = {"next_action": "Skip eligible cleanup", "responsible": "Agent"}
        invalid.append(value)
        for policy in invalid:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                with self.disposition_world(retention=policy):
                    pass

        with self.disposition_world():
            registered = self.registry.get("fixture")["cleanup"]["registration"]
            self.assertEqual(registered.get("retention_policy"), self.retention_policy())
            self.assertEqual(len(registered.get("retention_policy_sha256", "")), 64)
            # Merely emitting a native-action request is not an attempted native
            # cleanup and cannot silently qualify as unknown-result retention.
            pending = self.apply(self.plan())
            self.assertEqual(pending["status"], "native_action_required", pending)
            self.assertFalse(self.closure().get("disposition_complete", False))
            self.assertTrue(self.source.exists())
            self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), self.head)

        with self.disposition_world():
            record = self.registry.get("fixture")
            record["grants"]["retention"]["allowed_reasons"]["unfinished_work"] = {
                "next_action": "Preserve newly noticed work", "responsible": "Different actor"}
            record["grant_reference"] = "Unapproved attempted widening after frozen setup"
            try:
                self.registry.save(record, expected_revision=self.registry.read()["revision"])
            except ValueError:
                pass
            else:
                report = self.plan()
                self.assertTrue(report["blockers"], report)
                self.assertFalse(report.get("disposition_complete", False), report)
            self.assertTrue(self.source.exists())
            self.assertEqual(self.remote_tip(), self.head)

    def test_independent_cleanup(self):
        with self.disposition_world():
            self.unavailable()
            source_bytes = (self.source / "tool.sh").read_bytes()
            self.assertFalse(self.closure().get("disposition_complete", False),
                             "An eligible remote cannot be hidden by a worktree retention policy")
            called = []
            result = self.apply(self.plan(), native_cleanup=lambda request: called.append(request))
            self.assertEqual(called, [], "Unavailable native capability must not be invoked")
            self.assertIsNone(self.remote_tip(), "Blocked worktree must not prevent eligible actual remote cleanup")
            self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), self.head)
            self.assertTrue(self.source.is_dir())
            self.assertEqual((self.source / "tool.sh").read_bytes(), source_bytes)
            self.assert_retained(result, "worktree", "native_unavailable")
            self.assert_retained(result, "local_branch", "checked_out")
            self.assert_closed_retained(result)
            events = self.registry.get("fixture")["cleanup"]["operations"]
            remote_id = self.row(result, "remote_branch")["id"]
            self.assertTrue(any(e.get("artifact_id") == remote_id and e.get("event") == "outcome"
                                and e.get("state") == "removed" for e in events), events)
            self.guard.release(self.registry, "fixture", "Close with verified local retention",
                               policy=self.policy, control_checkout=self.root,
                               client_state=self.client_state, preservation=self.saved_assets)
            # A distinct, explicitly authorized fixture actor owns a recreated
            # actual remote ref. The closed flight's LOCAL reservation must
            # not become a blanket reservation of every remote with that name.
            self.git(self.root, "push", "--quiet", "origin", self.head + ":refs/heads/" + self.topic)
            other_path = self.worktree(self.area / "later-remote-owner", "later-remote-owner")
            self.git(other_path, "reset", "--hard", self.head)
            other = self.plain_record(other_path, "remote-owner")
            remote_inventory = [{"kind": "remote_branch", "identity": "refs/heads/" + self.topic, "remote": "origin"}]
            reference = "Owner separately grants only recreated actual fixture remote"
            other["grants"]["cleanup"] = [{"authority": "owner", "reference": reference,
                                           "inventory": remote_inventory}]
            self.guard.adopt(other_path, self.registry, other, base=self.base,
                             client_observation=self.observation, policy=self.policy)
            self.life.register_cleanup(self.root, self.registry, "remote-owner", inventory=remote_inventory,
                                       reference=reference)
            remote_plan = self.life.plan(self.root, self.registry, "remote-owner", delivery=self.delivery,
                                         policy=self.policy)
            remote_result = self.life.apply(self.root, self.registry, "remote-owner", remote_plan,
                                            delivery=self.delivery, policy=self.policy)
            self.assertIsNone(self.remote_tip(), "Closed local retention must not block separately owned remote cleanup")
            self.assertTrue(remote_result["complete"], remote_result)
            self.assertTrue(self.source.exists())
            self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), self.head)

    def test_native_outcomes(self):
        for outcome in ("failed", "unknown"):
            with self.subTest(outcome=outcome), self.disposition_world():
                called = []

                def actual_attempt(request):
                    called.append(copy.deepcopy(request))
                    if outcome == "unknown":
                        raise TimeoutError("Fixture native response lost after dispatch")
                    return {"client": "codex", "path": str(self.source),
                            "operation_id": request["operation_id"], "success": False,
                            "error": "Fixture native client refused protected target"}

                try:
                    result = self.apply(self.plan(), native_cleanup=actual_attempt)
                except TimeoutError as error:
                    self.fail("Dispatched unknown outcome was not retained/accounted: " + str(error))
                self.assertEqual(len(called), 1)
                self.assertIsNone(self.remote_tip(), "A native failure must not suppress independent remote cleanup")
                self.assertTrue(self.source.exists())
                row = self.assert_retained(result, "worktree", "native_" + outcome)
                self.assertEqual(row["operation_state"], outcome)
                self.assert_closed_retained(result)
                original = copy.deepcopy(self.registry.get("fixture")["cleanup"]["operations"])
                again = self.apply(self.plan(), native_cleanup=actual_attempt)
                self.assertEqual(len(called), 1, "Do not retry failed/unknown native work until green")
                self.assertEqual(self.assert_retained(again, "worktree")["operation_state"], outcome)
                retained = self.registry.get("fixture")["cleanup"]["operations"]
                self.assertEqual(retained[:len(original)], original)
                self.assertFalse(any(e.get("event") == "native_ack" and e.get("state") == "removed" for e in retained))
                self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), self.head)

    def test_unknown_reservations(self):
        try:
            with self.disposition_world(unknown_operation=True):
                self.unavailable()
                result = self.apply(self.plan())
                operation = self.assert_retained(result, "native_operation", "native_unknown")
                self.assertEqual(operation["operation_state"], "unknown")
                self.assertEqual(operation["identity"], "fixture-native-call-unknown")
                self.assertEqual(operation["reservations"]["paths"], [])
                self.assertEqual(operation["reservations"]["names"], ["fixture-native-pending"])
                self.assertIsNone(self.remote_tip(), "An unrelated eligible ref remains independently removable")
                # A first closure cannot rewrite the frozen operation's
                # identity or silently release any known reserved namespace.
                saved = self.registry.read()
                for malformed in ("identity", "names", "refs"):
                    record = copy.deepcopy(self.registry.get("fixture"))
                    record["lifecycle"] = {"state": "closed", "disposition": "closed with retained artifacts"}
                    record["cleanup"]["state"] = "closed_with_retained_artifacts"
                    record["cleanup"]["closure"] = copy.deepcopy(result)
                    native = next(row for row in record["cleanup"]["closure"]["artifacts"]
                                  if row["kind"] == "native_operation")
                    if malformed == "identity":
                        native["identity"] = "invented-different-operation"
                    else:
                        native["reservations"][malformed] = []
                    with self.subTest(first_closure=malformed), self.assertRaises(ValueError):
                        self.registry.save(record, expected_revision=saved["revision"])
                    self.assertEqual(self.registry.read(), saved)
                targets = [self.area / "fixture-native-pending" / "SpringDev",
                           self.area / "alias" / "fixture-native-pending"]
                for number, target in enumerate(targets):
                    target.parent.mkdir(exist_ok=True)
                    conflict = self.worktree(target, "conflicting-topic-" + str(number))
                    record = self.plain_record(conflict, "conflicting-flight-" + str(number))
                    before = self.registry.read()
                    with self.assertRaises(ValueError):
                        self.guard.adopt(conflict, self.registry, record, base=self.base,
                                         client_observation=self.observation, policy=self.policy)
                    self.assertEqual(self.registry.read(), before)
                    self.assertTrue(conflict.exists())
                unrelated = self.worktree(self.area / "unrelated-safe", "unrelated-safe")
                admitted = self.guard.adopt(unrelated, self.registry, self.plain_record(unrelated, "unrelated-flight"),
                                            base=self.base, client_observation=self.observation, policy=self.policy)
                self.assertEqual(admitted["status"], "verified")
                # A separately scoped actor still cannot delete an exact ref
                # reserved by an unknown operation. Other existing owner branch
                # names differ, so this tests the reservation itself.
                reserved_ref = "refs/heads/native-reserved-ref"
                self.git(self.root, "update-ref", reserved_ref, self.head)
                self.git(unrelated, "reset", "--hard", self.head)
                other = self.registry.get("unrelated-flight")
                other["delivery"]["head"] = self.head
                other["grants"]["cleanup"] = [{"authority": "owner", "reference": "Only exact reserved fixture ref",
                                                "inventory": [{"kind": "local_branch", "identity": reserved_ref}]}]
                other["grant_reference"] = "Separate fixture actor cleanup grant"
                self.registry.save(other, expected_revision=self.registry.read()["revision"])
                refused = False
                try:
                    self.life.register_cleanup(self.root, self.registry, "unrelated-flight",
                        inventory=[{"kind": "local_branch", "identity": reserved_ref}],
                        reference="Only exact reserved fixture ref")
                    attempt = self.life.plan(self.root, self.registry, "unrelated-flight", delivery=self.delivery,
                                              policy=self.policy, client_state=self.client_state)
                    attempted = self.life.apply(self.root, self.registry, "unrelated-flight", attempt,
                                                delivery=self.delivery, policy=self.policy,
                                                client_state=self.client_state)
                    refused = not attempted.get("complete", False) and bool(attempted["blockers"])
                except ValueError:
                    refused = True
                self.assertTrue(refused, "Unknown exact-ref reservation must prevent a conflicting cleanup")
                self.assertEqual(self.git(self.root, "rev-parse", reserved_ref), self.head)
                self.assertEqual(self.registry.get("fixture")["lifecycle"]["state"], "active")
        except ValueError as error:
            self.fail("Required unknown-operation accounting/reservation was rejected: " + str(error))

    def test_closed_retained_visibility(self):
        try:
            with self.disposition_world(unknown_operation=True):
                self.unavailable()
                self.assert_closed_retained(self.apply(self.plan()))
                released = self.guard.release(self.registry, "fixture", "Policy-accepted retained fixture closeout",
                                               policy=self.policy, control_checkout=self.root,
                                               client_state=self.client_state, preservation=self.saved_assets)
                self.assertEqual(released["status"], "released")
                self.assertEqual(self.registry.get("fixture")["lifecycle"]["state"], "closed")
                before = self.snapshot()
                related = self.life.launch(self.root, self.registry, "fixture/repo", issues=[81])
                unrelated = self.life.launch(self.root, self.registry, "fixture/repo", issues=[999])
                audit = self.readonly_audit()
                self.assertEqual(self.snapshot(), before, "Launch/audit must leave actual bytes/modes/mtimes unchanged")
                self.assertTrue(related["decision_required"], related)
                linked = next(row for row in related["related"] if row["flight"] == "fixture")
                launch_rows = linked.get("retained_artifacts", [])
                self.assertEqual({row["kind"] for row in launch_rows},
                                 {"worktree", "local_branch", "native_operation"}, linked)
                self.assertTrue(all(row.get("next_action") and row.get("reason_code") for row in launch_rows), linked)
                self.assertFalse(unrelated["decision_required"], unrelated)
                self.assertIs(audit["read_only"], True)
                self.assertIs(audit["cleanup_authorized"], False)
                expected = {
                    "worktree": ("path", str(self.source), "native_unavailable", "blocked"),
                    "local_branch": ("ref", "refs/heads/" + self.topic, "checked_out", "blocked"),
                    "native_operation": ("operation", "fixture-native-call-unknown", "native_unknown", "unknown"),
                }
                observed = {}
                for kind, (field, identity, reason, outcome) in expected.items():
                    matches = [row for row in audit["artifacts"] if row["kind"] == kind
                               and row["identity"].get(field) == identity]
                    self.assertEqual(len(matches), 1, (kind, matches))
                    artifact = matches[0]
                    obligations = [row for row in artifact.get("retained_obligations", [])
                                   if row.get("flight") == "fixture" and row["kind"] == kind
                                   and row["identity"] == identity]
                    self.assertEqual(len(obligations), 1, artifact)
                    obligation = obligations[0]
                    self.assertEqual(obligation["disposition"], "retained_accepted")
                    self.assertEqual(obligation["reason_code"], reason)
                    self.assertEqual(obligation["operation_state"], outcome)
                    self.assertEqual(obligation["policy_reference"], self.retention_policy()["reference"])
                    for required in ("reason", "next_action", "responsible"):
                        self.assertTrue(obligation.get(required), (required, artifact))
                    self.assertNotEqual(artifact["recommendation"]["classification"], "cleanup_candidate")
                    observed[kind] = (artifact, obligation)
                native, operation = observed["native_operation"]
                self.assertEqual(native["state"]["existence"], "unknown")
                self.assertIs(native["state"]["available"], False)
                self.assertIsNone(native["identity"].get("path"), "Unknown native target must not acquire an invented path")
                self.assertIsNone(native["identity"].get("git_dir"), "Unknown native target must not acquire an invented admin identity")
                self.assertEqual(operation["reservations"]["paths"], [])
                self.assertEqual(operation["reservations"]["names"], ["fixture-native-pending"])
                self.assertEqual(operation["reservations"]["refs"], ["refs/heads/native-reserved-ref"])
                self.assertIn(str(self.source), observed["worktree"][1]["reservations"]["paths"])
                self.assertIn("refs/heads/" + self.topic, observed["local_branch"][1]["reservations"]["refs"])
                self.assertEqual(len(audit["recommendations"]), len(audit["artifacts"]))
                for row in audit["artifacts"]:
                    self.assertIs(row["cleanup_authorized"], False)
                    self.assertTrue(row["recommendation"]["action"])
                # A closed flight's retained physical checkout is still owned.
                replacement = self.plain_record(self.source, "new-competing-flight")
                with self.assertRaises(ValueError):
                    self.guard.adopt(self.source, self.registry, replacement, base=self.base,
                                     client_observation=self.observation, policy=self.policy)
                self.assertTrue(self.source.exists())
        except ValueError as error:
            self.fail("Required closed-retained visibility setup was rejected: " + str(error))

    def test_git_managed_closeout(self):
        with self.disposition_world(git_managed=True):
            admin = Path(self.git(self.source, "rev-parse", "--absolute-git-dir"))
            result = self.apply(self.plan())
            self.assertFalse(self.source.exists(), "Explicitly owned Git-managed worker must be removed without native tools")
            self.assertFalse(admin.exists())
            self.assertIsNone(self.remote_tip())
            self.assertEqual(self.run_git(self.root, "show-ref", "--verify", "--quiet", "refs/heads/" + self.topic,
                                          expected=1), "")
            self.assertIs(result.get("disposition_complete"), True, result)
            self.assertIs(result.get("cleanup_complete"), True, result)
            released = self.guard.release(self.registry, "fixture", "Actual Git-managed worker closeout",
                                           policy=self.policy, control_checkout=self.root)
            self.assertEqual(released["status"], "released")

        # Advance A -> B at the actual update-ref invocation, after the final
        # plan observation. A no-lease deletion mutation must lose B and fail
        # this witness; an ordinary fresh observation alone cannot prove CAS.
        with self.disposition_world(git_managed=True):
            actor = self.worktree(self.area / "concurrent-holder", "concurrent-holder")
            self.git(actor, "reset", "--hard", self.head)
            newer = self.commit(actor, "new-owner-work.txt")
            ref = "refs/heads/" + self.topic
            original_git = self.life._git
            races = []

            def advance_at_cas(root, *arguments, **kwargs):
                if arguments[:3] == ("update-ref", "--no-deref", "-d") and arguments[3] == ref and not races:
                    self.git(self.root, "update-ref", ref, newer, self.head)
                    self.assertEqual(self.git(self.root, "rev-parse", ref), newer)
                    races.append({"old": self.head, "new": newer, "arguments": arguments})
                return original_git(root, *arguments, **kwargs)

            with patch.object(self.life, "_git", side_effect=advance_at_cas):
                result = self.apply(self.plan())
            self.assertEqual(len(races), 1, "Witness must reach the real local deletion boundary")
            self.assertEqual(self.git(self.root, "rev-parse", ref), newer, "Exact old-OID CAS must preserve B")
            self.assertFalse(self.source.exists())
            self.assertEqual(self.row(result, "worktree").get("disposition"), "cleanup_complete")
            self.assertFalse(result.get("disposition_complete", False), result)
            with self.assertRaises(ValueError):
                self.guard.release(self.registry, "fixture", "Cannot release unaccounted advanced branch",
                                   policy=self.policy, control_checkout=self.root)
            self.assertTrue((actor / "new-owner-work.txt").exists())

        # A completed removal is not proof about an exact branch recreated at
        # A before release, even when its new checkout would ordinarily qualify
        # for checked_out retention under the setup policy.
        with self.disposition_world(git_managed=True):
            removed = self.apply(self.plan())
            self.assertIs(removed.get("cleanup_complete"), True, removed)
            history = copy.deepcopy(self.registry.get("fixture")["cleanup"]["operations"])
            local_id = self.row(removed, "local_branch")["id"]
            last_removal = next(event for event in reversed(history)
                                if event.get("artifact_id") == local_id and event.get("event") == "outcome")
            self.assertEqual(last_removal["state"], "removed")
            recreated = self.worktree(self.area / "recreated-holder", self.topic)
            self.git(recreated, "reset", "--hard", self.head)
            before = self.snapshot([recreated])
            current = self.closure()
            local = self.row(current, "local_branch")
            self.assertEqual(local.get("last_operation"), last_removal)
            self.assertEqual(local.get("observed_oid"), self.head)
            # This actual fresh row and original journal exercise association
            # resolution directly, without inventing a retention acceptance.
            self.assertFalse(self.associations._resolved_artifact(
                self.registry.get("fixture")["cleanup"], local),
                "Historical removal must not discharge a later reappearance obligation")
            self.assertFalse(current.get("disposition_complete", False), current)
            self.assertEqual(local.get("reason_code"), "reappeared", local)
            self.assertNotEqual(local.get("disposition"), "retained_accepted", local)
            self.assertTrue(any("reappeared" in value.lower() for value in local.get("blockers", [])), local)
            with self.assertRaises(ValueError):
                self.guard.release(self.registry, "fixture", "Recreated branch requires a separate decision",
                                   policy=self.policy, control_checkout=self.root)
            self.assertEqual(self.registry.get("fixture")["lifecycle"]["state"], "active")
            self.assertEqual(self.registry.get("fixture")["cleanup"]["operations"], history)
            self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), self.head)
            self.assertTrue(recreated.is_dir())
            self.assertEqual(self.snapshot([recreated]), before)
            self.assertFalse(self.source.exists())
            self.assertIsNone(self.remote_tip())

    def test_retention_safeguards(self):
        for blocker in ("dirty", "private", "locked"):
            with self.subTest(blocker=blocker), self.disposition_world():
                if blocker == "dirty":
                    (self.source / "tool.sh").write_text("Unfinished owner changes\n")
                elif blocker == "private":
                    (self.source / ".env").write_text("PRIVATE_UNOWNED_FIXTURE_DATA\n")
                else:
                    self.git(self.root, "worktree", "lock", str(self.source), "--reason", "Owner active lock")
                before_files = self.snapshot([self.source])
                result = self.apply(self.plan())
                self.assertIsNone(self.remote_tip(), "A blocked/unaccepted worktree must not suppress independently safe cleanup")
                self.assertTrue(self.source.exists())
                self.assertEqual(self.snapshot([self.source]), before_files)
                self.assertEqual(self.git(self.root, "rev-parse", "refs/heads/" + self.topic), self.head)
                self.assertFalse(result.get("disposition_complete", False), result)
                self.assertNotEqual(self.row(result, "worktree").get("disposition"), "retained_accepted")

        for blocker in ("protected", "unintegrated"):
            with self.subTest(blocker=blocker), self.disposition_world(integrated=blocker != "unintegrated"):
                if blocker == "protected":
                    self.policy["protected_branches"].append(self.topic)
                before = self.snapshot([self.root, self.source, self.remote])
                result = self.apply(self.plan())
                self.assertFalse(result.get("disposition_complete", False), result)
                self.assertTrue(self.source.exists())
                self.assertEqual(self.remote_tip(), self.head)
                self.assertEqual(self.snapshot([self.root, self.source, self.remote]), before)

    def test_legacy_compatibility(self):
        with self.disposition_world(retention=False):
            result = self.apply(self.plan(), native_cleanup=self.remove_native)
            self.assertIs(result["complete"], True, result)
            self.assertFalse(self.source.exists())
            self.assertIsNone(self.remote_tip())
            self.assertEqual(self.guard.release(self.registry, "fixture", "Legacy strict complete cleanup",
                                               policy=self.policy, control_checkout=self.root)["status"], "released")

        with self.fixture():
            selected = self.worktree(self.area / "markerless", "markerless")
            self.retained_legacy(selected, self.record(selected))
            self.assertNotIn("cleanup", self.registry.get("fixture"))
            self.assertEqual(self.guard.release(self.registry, "fixture", "Existing markerless compatible release",
                                               policy=self.policy, control_checkout=self.root)["status"], "released")
            self.assertTrue(selected.exists())


if __name__ == "__main__":
    unittest.main()
