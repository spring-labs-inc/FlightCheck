"""Isolated lifecycle/provider witnesses; never contact or mutate a live board."""

import contextlib
import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from foundation_flight_cases import FlightCases


PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])).resolve()


class StatusSynchronizationTests(unittest.TestCase):
    flight_git = FlightCases.flight_git
    flight_repo = FlightCases.flight_repo
    flight_checkout = FlightCases.flight_checkout

    @contextlib.contextmanager
    def fixture(self, mode="advisory"):
        # The reporter itself lives in the current scripts directory. An
        # original-product control must never fall back to those new modules.
        for name in ("status_sync", "status_sync_config", "status_sync_github"):
            self.assertTrue((PRODUCT / "workflow/scripts" / (name + ".py")).is_file(),
                            "The explicit product snapshot must supply " + name)
        names = ("status_sync", "status_sync_config", "status_sync_github", "project_config",
                 "flight_associations", "flight_lifecycle", "launch_detection", "checkout_guard")
        previous = {name: sys.modules.pop(name, None) for name in names}
        sys.path.insert(0, str(PRODUCT / "workflow/scripts"))
        try:
            sync = importlib.import_module("status_sync")
            schema = importlib.import_module("status_sync_config")
            model = importlib.import_module("project_config")
            associations = importlib.import_module("flight_associations")
            for name in ("status_sync", "status_sync_config", "status_sync_github", "project_config", "flight_associations"):
                self.assertEqual(Path(sys.modules[name].__file__).resolve(), PRODUCT / "workflow/scripts" / (name + ".py"))
            with tempfile.TemporaryDirectory(prefix="status-sync-fixture-") as tmp:
                area = Path(tmp).resolve()
                root = self.flight_repo(area / "repository")
                worker = self.flight_checkout(root, area / "worker", "owned-flight")
                policy = {"schema": 1, "mode": mode, "provider": "github-projects-v2", "project_id": "project-A",
                          "field_id": "field-status", "options": {k: "option-" + str(i) for i, k in enumerate(schema.STATES)},
                          "membership": "existing-only"}
                values = model.normalize(worker, {"python": sys.executable, "default_branch": "trunk",
                    "evidence_dir": str(area / "evidence"), "nit_tracker": "fixture notes", "policy_reference": "Fixture owner",
                    "checks": [{"name": "recorded", "command": ["python3", "check.py"], "phase": "cheap"}],
                    "status_sync": policy}, origin="setup")
                snapshot = {"revision": model.revision(model.encoded(values)), "values": values}
                grant = {"schema": 1, "authority": "owner", "reference": "Fixture exact status grant",
                         "repository": "owner/repository", "provider": policy["provider"], "project_id": policy["project_id"],
                         "field_id": policy["field_id"], "issues": [11, 12], "configuration_revision": snapshot["revision"]}
                record = {"schema": 1, "flight": "owned-flight", "task": "task-owned-flight", "card": "task-owned-flight",
                    "repository": associations.repository_identity(root, "owner/repository"), "issues": [11, 12, 99], "pull_requests": [],
                    "client": {"name": "fixture", "sessions": ["isolated-session"]}, "checkout": {
                        "path": str(worker), "kind": "disposable-temporary", "management": "manual", "branch": "owned-flight",
                        "commit": self.flight_git(worker, "rev-parse", "HEAD")}, "children": [], "configuration": snapshot,
                    "grants": {"tracker_status": grant, "delivery": [], "cleanup": []}, "delivery": {"target": "trunk"},
                    "lifecycle": {"state": "active", "disposition": "pending"}, "status_sync": {
                        "work": [{"issue": i, "role": "roadmap" if i == 99 else "implementation", "scope": "full",
                                  "reference": "Fixture changed scope"} for i in (11, 12, 99)],
                        "observations": {}, "pending": {}, "outcomes": []}}
                registry = associations.Registry(area / "registry")
                registry.save(record)
                provider = FakeProvider(sync, policy)
                yield area, root, worker, registry, provider, sync
        finally:
            sys.path.pop(0)
            for name in names:
                sys.modules.pop(name, None)
                if previous[name] is not None:
                    sys.modules[name] = previous[name]

    def event(self, kind="start", **extra):
        return {"kind": kind, "issues": [11], "reference": "Fixture actual " + kind, **extra}

    def run_event(self, fixture, event=None, verifier=None):
        area, root, worker, registry, provider, sync = fixture
        return sync.synchronize(registry, "owned-flight", event or self.event(), checkout=worker,
                                provider=provider, verifier=verifier or (lambda *a: {"status": "verified"}), pause=lambda delay: None)

    def change(self, fixture, edit):
        registry = fixture[3]
        before = registry.read()
        record = next(r for r in before["records"] if r["flight"] == "owned-flight")
        edit(record)
        record.setdefault("grant_reference", "Fixture explicit changed grant")
        registry.save(record, expected_revision=before["revision"])

    def test_lifecycle_start_resume_review_repair(self):
        with self.fixture() as f:
            provider = f[4]
            for kind in ("plan", "inspect", "card_poll", "message", "early_code"):
                self.assertEqual(self.run_event(f, self.event(kind))["state"], "not_an_event")
            self.assertEqual(provider.calls, [])
            with self.assertRaises(ValueError):
                self.run_event(f, self.event("revieew"))
            started = self.run_event(f)
            self.assertEqual(started["state"], "synchronized")
            self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["in_progress"])
            self.assertEqual(len(provider.mutations), 1)
            self.assertEqual(self.run_event(f)["outcomes"][0]["reason"], "already_aligned")
            not_ready = self.run_event(f, self.event("review", ready=False))
            self.assertEqual(not_ready["outcomes"][0]["reason"], "not_ready")
            self.assertEqual(len(provider.mutations), 1)
            review = self.run_event(f, self.event("review", ready=True))
            self.assertEqual(review["state"], "synchronized")
            self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["review"])
            self.assertEqual(self.run_event(f, self.event("resume"))["state"], "synchronized")
            self.assertEqual(len(provider.mutations), 2, "Resume must retain warranted Review, not restart it")
            self.assertEqual(self.run_event(f, self.event("repair"))["state"], "synchronized")
            self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["in_progress"])
            self.assertEqual(len(provider.mutations), 3)
            self.assertTrue(all(x["field_id"] == "field-status" for x in provider.mutations))

    def test_accepted_completion_and_partial_delivery(self):
        with self.fixture() as f:
            provider = f[4]
            partial = self.event("accepted_completion", completion={"accepted": True, "full_scope": False,
                                                                    "reference": "Accepted partial"})
            self.assertEqual(self.run_event(f, partial)["outcomes"][0]["reason"], "partial_delivery")
            full = self.event("accepted_completion", completion={"accepted": True, "full_scope": True,
                                                                 "reference": "Actual full issue acceptance"})
            self.assertEqual(self.run_event(f, full)["outcomes"][0]["reason"], "closure_required")
            self.assertEqual(provider.mutations, [])
            self.assertEqual(provider.closures, [])
            self.assertEqual(provider.automation_reads, 2)
            self.change(f, lambda r: r["status_sync"]["work"][0].update(scope="partial"))
            provider.state[11].update(state="CLOSED", state_reason="COMPLETED")
            self.assertEqual(self.run_event(f, full)["outcomes"][0]["reason"], "partial_delivery")
            self.change(f, lambda r: r["status_sync"]["work"][0].update(scope="full"))
            provider.state[11]["state_reason"] = "NOT_PLANNED"
            self.assertEqual(self.run_event(f, full)["outcomes"][0]["reason"], "cancelled")
            provider.state[11]["state_reason"] = "COMPLETED"
            # A fresh explicit observed-state decision covers the status-only
            # reconciliation after separately authorized completed closure.
            full.update(expected={"11": provider.observe(11)}, reconciliation_reference="Owner verifies completed closure")
            self.assertEqual(self.run_event(f, full)["state"], "synchronized")
            self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["done"])
            self.assertEqual(provider.closures, [])
            self.assertEqual(self.run_event(f, self.event("resume"))["outcomes"][0]["reason"], "completed_work")
        # Exercise the real completion verifier from stable control after worker
        # removal, with only its external provider reads replaced by fixture facts.
        with self.fixture() as f:
            area, root, worker, registry, provider, sync = f
            base = self.flight_git(root, "rev-parse", "HEAD")
            (worker / "accepted.txt").write_text("delivered\n")
            self.flight_git(worker, "add", ".")
            self.flight_git(worker, "commit", "-qm", "Accepted fixture change")
            head = self.flight_git(worker, "rev-parse", "HEAD")
            self.flight_git(root, "merge", "--no-ff", "-qm", "Integrated fixture", "owned-flight")
            merged = self.flight_git(root, "rev-parse", "HEAD")
            delivery = {"repository": "owner/repository", "source_base": base, "head": head,
                        "merge_commit": merged, "merged": True, "target": "trunk", "pull_request": 7}
            def close(record):
                record["pull_requests"] = [7]
                record["lifecycle"] = {"state": "closed", "disposition": "closed with retained artifacts"}
                record["cleanup"] = {"protocol": "required-v1", "inventory": [], "operations": [], "state": "closed",
                    "frozen_binding": {"source_head": head}, "frozen_delivery": delivery,
                    "closure": {"complete": True, "cleanup_complete": False, "blockers": [], "artifacts": []}}
            self.change(f, close)
            self.flight_git(root, "worktree", "remove", str(worker))
            self.assertFalse(worker.exists())
            provider.state[11].update(state="CLOSED", state_reason="COMPLETED", option_id=provider.policy["options"]["done"])
            event = self.event("accepted_completion", completion={"accepted": True, "full_scope": True, "reference": "Full owner acceptance"})
            lifecycle = importlib.import_module("flight_lifecycle")
            with patch.object(lifecycle, "_discover_delivery", return_value=delivery), \
                    patch.object(lifecycle, "_push_endpoint", return_value="fixture endpoint"), \
                    patch.object(lifecycle, "_advertised", return_value=merged):
                accepted = sync.synchronize(registry, "owned-flight", event, checkout=root, provider=provider)
                self.assertEqual(accepted["state"], "synchronized", accepted)
                self.change(f, lambda r: r["cleanup"]["closure"].update(complete=False))
                blocked = sync.synchronize(registry, "owned-flight", event, checkout=root, provider=provider)
                self.assertEqual(blocked["outcomes"][0]["reason"], "completion_unverified")
            self.assertFalse(worker.exists(), "Completion must never restore or adopt removed execution")
            self.assertEqual(registry.get("owned-flight")["lifecycle"]["state"], "closed")

    def test_multiple_issues_flights_and_epics(self):
        with self.fixture() as f:
            registry, provider = f[3:5]
            self.change(f, lambda r: r["status_sync"]["work"][1].update(role="implementation_epic"))
            before = provider.observe(12)
            result = self.run_event(f, self.event(issues=[11, 99]))
            self.assertEqual(result["outcomes"][1]["reason"], "roadmap")
            self.assertEqual(provider.observe(12), before, "Linked but unchanged issue must not be promoted")
            self.assertEqual([x["issue"] for x in provider.mutations], [11])
            self.assertEqual(self.run_event(f, self.event(issues=[12]))["state"], "synchronized")
            self.assertEqual(provider.state[12]["option_id"], provider.policy["options"]["in_progress"])
            with self.assertRaises(ValueError):
                self.run_event(f, self.event(issues=[700]))
            self.change(f, lambda r: r["status_sync"]["work"].pop(0))
            self.assertEqual(self.run_event(f)["outcomes"][0]["reason"], "work_scope_missing")
            # A real ownership-verification failure precedes all provider writes.
            count = len(provider.mutations)
            result = self.run_event(f, self.event(issues=[12]), verifier=lambda *a: {"status": "conflict"})
            self.assertEqual(result["outcomes"][0]["reason"], "ownership_unverified")
            self.assertEqual(len(provider.mutations), count)
        with self.fixture() as f:
            area, root, worker, registry, provider, sync = f
            other_worker = self.flight_checkout(root, area / "other-worker", "other-flight")
            peer = copy.deepcopy(registry.get("owned-flight"))
            peer.update(flight="other-flight", task="other-task", card="other-task")
            peer["checkout"].update(path=str(other_worker), branch="other-flight")
            peer["status_sync"]["work"] = [{"issue": 11, "role": "implementation", "scope": "partial", "reference": "Other explicit scoped work"}]
            registry.save(peer, expected_revision=registry.read()["revision"])
            self.assertEqual(self.run_event(f)["outcomes"][0]["reason"], "concurrent_flight")
            self.assertEqual(provider.mutations, [])
            self.assertEqual(self.run_event(f, self.event(issues=[12]))["state"], "synchronized")
            self.assertEqual([m["issue"] for m in provider.mutations], [12])

    def test_manual_and_concurrent_status_decisions(self):
        with self.fixture() as f:
            provider = f[4]
            self.run_event(f)
            original_fields = copy.deepcopy(provider.fields)
            provider.manual(11, provider.policy["options"]["ready"])
            result = self.run_event(f, self.event("review", ready=True))
            self.assertEqual(result["outcomes"][0]["reason"], "conflict")
            self.assertEqual(len(provider.mutations), 1)
            self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["ready"])
            self.assertEqual(provider.fields, original_fields)
            observed = provider.observe(11)
            event = self.event("review", ready=True, expected={"11": observed}, reconciliation_reference="Owner accepts new current status")
            provider.before_write = lambda: provider.manual(11, provider.policy["options"]["todo"])
            result = self.run_event(f, event)
            self.assertEqual(result["outcomes"][0]["reason"], "conflict")
            self.assertEqual(len(provider.mutations), 1, "Concurrent status between planning/apply must not be overwritten")
            self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["todo"])
            self.assertEqual(provider.fields, original_fields)
            provider.before_write = None
            provider.fields["Priority"] = "Owner priority decision"
            event.update(expected={"11": provider.observe(11)})
            self.assertEqual(self.run_event(f, event)["state"], "synchronized")
            self.assertEqual(provider.fields["Priority"], "Owner priority decision")
            self.assertEqual(provider.fields["Sequence"], original_fields["Sequence"])

    def test_authority_membership_and_unavailable_states(self):
        for mode in ("advisory", "required"):
            with self.subTest(mode=mode), self.fixture(mode) as f:
                registry, provider = f[3:5]
                provider.missing = True
                result = self.run_event(f)
                self.assertEqual(result["outcomes"][0]["reason"], "missing_membership")
                self.assertEqual(result["blocked"], mode == "required")
                self.assertEqual(provider.membership_writes, [])
                self.assertEqual(provider.mutations, [])
                # An external authorized membership decision is not a status
                # grant. Once resolved, retry observes the actual existing item.
                provider.missing = False
                self.assertEqual(self.run_event(f)["state"], "synchronized")
                self.assertEqual(len(provider.mutations), 1)
            with self.subTest(mode=mode, failure="authority"), self.fixture(mode) as f:
                self.change(f, lambda r: r["grants"].pop("tracker_status"))
                result = self.run_event(f)
                self.assertEqual(result["outcomes"][0]["reason"], "missing_authority")
                self.assertEqual(f[4].mutations, [])
                self.assertEqual(result["blocked"], mode == "required")
            with self.subTest(mode=mode, public_entry="cli"), self.fixture(mode) as f:
                f[4].missing = True
                event_path = f[0] / "private-event.json"
                event_path.write_text(json.dumps(self.event()))
                event_path.chmod(0o600)
                import io
                output = io.StringIO()
                with patch.object(f[5], "_verify", return_value={"status": "verified"}), \
                        patch.object(f[5], "resolve", return_value=f[4]), contextlib.redirect_stdout(output):
                    exit_code = f[5].main(["--checkout", str(f[2]), "--registry", str(f[3].directory),
                                          "--flight", "owned-flight", "--event", str(event_path)])
                self.assertEqual(exit_code, 1 if mode == "required" else 0)
                outcome = json.loads(output.getvalue())
                self.assertEqual(outcome["outcomes"][0]["reason"], "missing_membership")
                self.assertEqual(outcome["blocked"], mode == "required")
            with self.subTest(mode=mode, failure="provider"), self.fixture(mode) as f:
                f[4].unavailable = True
                result = self.run_event(f)
                self.assertEqual(result["outcomes"][0]["reason"], "provider_unavailable")
                self.assertEqual(result["blocked"], mode == "required")
            with self.subTest(mode=mode, failure="permission"), self.fixture(mode) as f:
                f[4].state[11]["writable"] = False
                result = self.run_event(f)
                self.assertEqual(result["outcomes"][0]["reason"], "permission_denied")
                self.assertEqual(f[4].mutations, [])

    def test_idempotent_and_ambiguous_provider_reconciliation(self):
        with self.fixture() as f:
            provider = f[4]
            provider.modes = ["timeout_applied"]
            result = self.run_event(f)
            self.assertEqual(result["state"], "synchronized")
            self.assertEqual(len(provider.mutations), 1)
            self.assertEqual(self.run_event(f)["outcomes"][0]["reason"], "already_aligned")
            self.assertEqual(len(provider.mutations), 1)
            self.assertEqual(f[3].get("owned-flight")["status_sync"]["pending"], {})
        with self.fixture() as f:
            provider = f[4]
            provider.modes = ["timeout_manual"]
            result = self.run_event(f)
            self.assertEqual(result["outcomes"][0]["reason"], "conflict")
            self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["todo"])
            self.assertEqual(provider.fields["Priority"], "Concurrent owner priority")
            self.assertEqual(len(provider.mutations), 1)
            self.assertEqual(provider.write_calls, 1, "Ambiguous response must be read before any retry")
        with self.fixture() as f:
            provider = f[4]
            provider.modes = ["timeout_no_apply", "timeout_no_apply"]
            result = self.run_event(f)
            self.assertEqual(result["outcomes"][0]["reason"], "retry_exhausted")
            self.assertEqual(provider.write_calls, 2)
            self.assertEqual(provider.mutations, [])
            self.assertTrue(f[3].get("owned-flight")["status_sync"]["pending"])
            self.run_event(f)
            self.assertEqual(provider.write_calls, 2, "Exhausted ambiguous attempt must not loop on resume")
        with self.fixture() as f:
            provider = f[4]
            provider.modes = ["timeout_no_apply", "ok"]
            self.assertEqual(self.run_event(f)["state"], "synchronized")
            self.assertEqual(provider.write_calls, 2)
            self.assertEqual(len(provider.mutations), 1)

    def test_native_automation_coexistence(self):
        for available in (False, True):
            with self.subTest(metadata_available=available), self.fixture() as f:
                provider = f[4]
                provider.metadata_available = available
                # Native automation already performed the warranted target.
                provider.state[11]["option_id"] = provider.policy["options"]["in_progress"]
                result = self.run_event(f)
                self.assertEqual(result["state"], "synchronized")
                self.assertEqual(result["automation"]["available"], available)
                self.assertFalse(result["automation"]["semantics_available"])
                self.assertEqual(provider.mutations, [])
                self.assertEqual(provider.workflow_writes, [])
                self.assertEqual(provider.automation_reads, 1)
                provider.manual(11, provider.policy["options"]["done"])
                partial = self.run_event(f, self.event("review", ready=True))
                self.assertEqual(partial["outcomes"][0]["reason"], "conflict")
                self.assertEqual(provider.state[11]["option_id"], provider.policy["options"]["done"])

    def test_github_adapter_exact_ids_and_conditional_status_only_write(self):
        with self.fixture() as f:
            sync, policy = f[5], f[4].policy
            requests = []
            live = {"option": policy["options"]["ready"], "updated": "status-rev-1", "Priority": "Owner priority", "Sequence": "Owner sequence"}
            def runner(argv, **kwargs):
                request = json.loads(kwargs["input"])
                query, variables = request["query"], request["variables"]
                requests.append(request)
                self.assertEqual(argv, ["gh", "api", "graphql", "--input", "-"])
                if "mutation(" in query:
                    self.assertIn("updateProjectV2ItemFieldValue", query)
                    self.assertEqual(variables["field"], policy["field_id"])
                    self.assertEqual(variables["item"], "existing-item-11")
                    self.assertEqual(variables["project"], policy["project_id"])
                    live.update(option=variables["option"], updated="status-rev-2")
                    data = {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "existing-item-11"}}}
                elif "field:node" in query:
                    data = {"project": {"id": policy["project_id"], "closed": False, "viewerCanUpdate": True},
                            "field": {"id": policy["field_id"], "project": {"id": policy["project_id"]},
                                      "options": [{"id": x} for x in policy["options"].values()]}}
                elif "projectItems(" in query:
                    self.assertEqual(variables["number"], 11)
                    data = {"repository": {"nameWithOwner": "owner/repository", "issue": {"number": 11, "state": "OPEN", "stateReason": None,
                            "projectItems": {"pageInfo": {"hasNextPage": False}, "nodes": [{"id": "existing-item-11", "isArchived": False,
                            "project": {"id": policy["project_id"]}}]}}}}
                elif "fieldValues(" in query:
                    data = {"node": {"id": "existing-item-11", "project": {"id": policy["project_id"]},
                            "fieldValues": {"pageInfo": {"hasNextPage": False}, "nodes": [{"field": {"id": policy["field_id"]},
                            "optionId": live["option"], "updatedAt": live["updated"]}]}}}
                elif "workflows(" in query:
                    data = {"node": {"id": policy["project_id"], "workflows": {"pageInfo": {"hasNextPage": False},
                            "nodes": [{"id": "workflow-owner", "name": "Custom name", "enabled": True}]}}}
                else:
                    self.fail(query)
                return subprocess.CompletedProcess(argv, 0, json.dumps({"data": data}), "")
            adapter = sync.GitHubProjects("owner/repository", policy, runner=runner)
            observed = adapter.observe(11)
            self.assertEqual(adapter.automation()["workflows"][0]["name"], "Custom name")
            self.assertFalse(adapter.automation()["semantics_available"])
            live["Priority"] = "Concurrent priority"
            written = adapter.write(11, policy["options"]["in_progress"], observed, "operation-1")
            self.assertEqual(written["state"], "written")
            self.assertEqual(live["Priority"], "Concurrent priority")
            self.assertEqual(live["Sequence"], "Owner sequence")
            self.assertEqual(len([r for r in requests if "mutation(" in r["query"]]), 1)
            stale = adapter.write(11, policy["options"]["review"], observed, "operation-2")
            self.assertEqual(stale["state"], "conflict")
            self.assertEqual(len([r for r in requests if "mutation(" in r["query"]]), 1)
            self.assertIn("no atomic compare-and-set", adapter.concurrency)


class FakeProvider:
    name = "github-projects-v2"
    concurrency = "Fixture compares exact Status identity before writes"

    def __init__(self, sync, policy):
        self.sync, self.policy = sync, policy
        self.state = {i: {"repository": "owner/repository", "issue": i, "project_id": policy["project_id"],
                         "field_id": policy["field_id"], "item_id": "existing-item-" + str(i),
                         "option_id": policy["options"]["ready"], "status_updated_at": "initial",
                         "writable": True, "state": "OPEN", "state_reason": None} for i in (11, 12, 99)}
        self.fields = {"Sequence": "Owner sequence", "Priority": "Owner priority", "labels": ["Owner label"], "parent": 99}
        self.calls, self.mutations, self.closures, self.membership_writes, self.workflow_writes = [], [], [], [], []
        self.write_calls, self.automation_reads, self.clock = 0, 0, 0
        self.missing = self.unavailable = False
        self.before_write = None
        self.modes = []
        self.metadata_available = True

    def observe(self, issue):
        self.calls.append(("read", issue))
        if self.unavailable:
            raise self.sync.ProviderError("provider_unavailable", "Fixture provider unavailable")
        if self.missing:
            raise self.sync.ProviderError("missing_membership", "Establish separately authorized membership, then retry")
        return copy.deepcopy(self.state[issue])

    def automation(self):
        self.automation_reads += 1
        return {"available": self.metadata_available, "semantics_available": False,
                "workflows": [{"id": "observed-workflow", "name": "Custom owner workflow", "enabled": True}] if self.metadata_available else [],
                "detail": "Actual metadata available; trigger/action semantics unavailable"}

    def manual(self, issue, option):
        self.clock += 1
        self.state[issue].update(option_id=option, status_updated_at="manual-" + str(self.clock))

    def write(self, issue, option, expected, operation):
        self.write_calls += 1
        if self.before_write:
            self.before_write()
        current = self.observe(issue)
        if self.sync.status_identity(current) != self.sync.status_identity(expected):
            return {"state": "conflict", "observation": current}
        mode = self.modes.pop(0) if self.modes else "ok"
        if mode == "timeout_no_apply":
            raise self.sync.ProviderError("provider_unavailable", "Uncertain request", ambiguous=True)
        self.clock += 1
        self.state[issue].update(option_id=option, status_updated_at="write-" + str(self.clock))
        self.mutations.append({"issue": issue, "field_id": self.policy["field_id"], "option": option, "operation": operation})
        if mode == "timeout_manual":
            self.manual(issue, self.policy["options"]["todo"])
            self.fields["Priority"] = "Concurrent owner priority"
        if mode in ("timeout_applied", "timeout_manual"):
            raise self.sync.ProviderError("provider_unavailable", "Response lost after mutation", ambiguous=True)
        return {"state": "written", "observation": self.observe(issue)}


if __name__ == "__main__":
    unittest.main()
