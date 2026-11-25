"""Additive verified-disposition fixtures; all mutations stay in disposable Git repos.

The existing lifecycle fixtures remain unchanged. Native responses below are
deterministic observations, not qualification of a live native client.
"""
import contextlib
import copy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from checkout_guard_cases import CheckoutCases
from lifecycle_cases import LifecycleCases


class DispositionCases(LifecycleCases):
    def retention_policy(self):
        actions = {
            "client_protection": "Use supported client handoff, then revalidate the exact artifact",
            "native_unavailable": "Restore supported capability and revalidate the retained artifact",
            "native_failed": "Inspect the retained native failure before any separately warranted retry",
            "native_unknown": "Reconcile the original operation before any conflicting mutation",
            "checked_out": "Release the preserved checkout before reconsidering branch cleanup",
        }
        return {"schema": 1, "authority": "owner", "reference": "Owner fixture setup retention policy",
                "allowed_reasons": {code: {"next_action": action, "responsible": "Fixture owner"}
                                    for code, action in actions.items()}}

    def record(self, path, flight="fixture", children=()):
        record = super().record(path, flight=flight, children=children)
        value = getattr(self, "_disposition_policy", None)
        if value is not None:
            record["grants"]["retention"] = copy.deepcopy(value)
        return record

    def inventory(self, *, kinds=("worktree", "local_branch", "remote_branch")):
        rows = super().inventory(kinds=kinds)
        if getattr(self, "_git_managed", False):
            for row in rows:
                if row["kind"] == "worktree":
                    row["git_managed"] = True
        if getattr(self, "_unknown_operation", False):
            rows.append({"kind": "native_operation", "identity": "fixture-native-call-unknown",
                         "client": "codex", "requested_name": "fixture-native-pending",
                         "outcome": "unknown", "observation_reference": "Fixture original native call lost its result",
                         "reservations": {"paths": [], "refs": ["refs/heads/native-reserved-ref"],
                                          "names": ["fixture-native-pending"]}})
        return rows

    def adopt(self, path, record=None, **kwargs):
        if getattr(self, "_git_managed", False) and record is not None and record["flight"] == "fixture":
            self.configure(path, checkout_policy={"mode": "native-choice", "git_fallback": True,
                                                  "fallback_reference": "Owner explicitly authorizes this Git-managed fixture"})
            record["configuration"] = self.config.snapshot(path)
            record["checkout"]["management"] = "manual"
            kwargs["client_observation"] = dict(self.observation, selection="manual")
        return super().adopt(path, record=record, **kwargs)

    @contextlib.contextmanager
    def disposition_world(self, *, retention=True, git_managed=False, unknown_operation=False, **kwargs):
        self._disposition_policy = self.retention_policy() if retention is True else (
            copy.deepcopy(retention) if retention else None)
        self._git_managed = git_managed
        self._unknown_operation = unknown_operation
        try:
            with super().world(**kwargs):
                self.client_state["reference"] = "Current fixture client observation"
                yield
        finally:
            self._disposition_policy = None
            self._git_managed = False
            self._unknown_operation = False

    def closure(self):
        return self.life.closure_status(self.root, self.registry, "fixture", delivery=self.delivery,
                                        policy=self.policy, client_state=self.client_state,
                                        preservation=self.saved_assets)

    def assert_retained(self, report, kind, reason=None):
        row = self.row(report, kind)
        self.assertEqual(row.get("disposition"), "retained_accepted", row)
        for field in ("reason", "next_action", "responsible", "policy_reference"):
            self.assertTrue(row.get(field), (field, row))
        if reason:
            self.assertEqual(row["reason_code"], reason, row)
        return row

    def assert_closed_retained(self, report):
        self.assertIs(report.get("disposition_complete"), True, report)
        self.assertIs(report.get("cleanup_complete"), False, report)
        self.assertEqual(report["status"], "closed_with_retained_artifacts", report)

    def unavailable(self):
        self.client_state.update(available=False, reference="Actual fixture native capability unavailable")

    def plain_record(self, path, flight, issue=999):
        record = CheckoutCases.record(self, path, flight=flight)
        record["issues"], record["pull_requests"] = [issue], []
        return record

    def readonly_audit(self):
        audit = self.feature("repository_audit")
        observations = {str(self.source): {"available": True, "active": False,
                        "source": "Current fixture client observation",
                        "observed_at": datetime.now(timezone.utc).isoformat()}}
        with patch.object(audit, "_provider_delivery", return_value=copy.deepcopy(self.delivery)), \
                patch.dict("os.environ", FC_AUDIT_READONLY="1"):
            return audit.audit(self.root, self.registry, "fixture/repo", policy=self.policy,
                               client_observations=observations)
