"""Current CODE-requested recovery witnesses; isolated Registry and providers only."""
import copy
import importlib
import json
from unittest.mock import patch
import unittest

import test_status_sync as witness


class StatusSyncRecoveryTests(unittest.TestCase):
    fixture = witness.StatusSynchronizationTests.fixture
    flight_git = witness.StatusSynchronizationTests.flight_git
    flight_repo = witness.StatusSynchronizationTests.flight_repo
    flight_checkout = witness.StatusSynchronizationTests.flight_checkout
    event = witness.StatusSynchronizationTests.event
    run_event = witness.StatusSynchronizationTests.run_event
    change = witness.StatusSynchronizationTests.change

    def owner_decision(self, f, name):
        observed = f[4].observe(11)
        decision = f[0] / (name + '.json')
        decision.write_text(json.dumps({'authority': 'fixture owner', 'repository': 'owner/repository',
            'issues': [11], 'project_id': 'project-A', 'field_id': 'field-status', 'expected': observed,
            'transition': 'in_progress', 'reason': 'Explicit isolated fixture recovery decision'}))
        decision.chmod(0o600)
        return self.event(expected={'11': observed}, reconciliation_reference=str(decision))

    def test_retained_intent_owner_reconciliation(self):
        for budget in (1, 2):
            with self.subTest(retained_attempts=budget), self.fixture() as f:
                provider, registry = f[4], f[3]
                if budget == 1:
                    original_write = provider.write
                    def lose_readback(*args):
                        try:
                            return original_write(*args)
                        finally:
                            provider.unavailable = True
                    provider.modes = ['timeout_applied']
                    provider.write = lose_readback
                    uncertain = self.run_event(f)
                    provider.write = original_write
                    provider.unavailable = False
                    self.assertEqual(uncertain['outcomes'][0]['reason'], 'ambiguous')
                else:
                    provider.modes = ['timeout_no_apply', 'timeout_no_apply']
                    self.assertEqual(self.run_event(f)['outcomes'][0]['reason'], 'retry_exhausted')
                old = copy.deepcopy(registry.get('owned-flight')['status_sync']['pending']['11'])
                self.assertEqual(old['attempts'], budget)
                provider.manual(11, provider.policy['options']['todo'])
                provider.fields['Priority'] = 'Restart owner priority'
                writes = provider.write_calls
                stale = self.event(expected={'11': old['before']}, reconciliation_reference='Stale fixture decision')
                missing_ref = self.event(expected={'11': provider.observe(11)})
                for retry in (self.event(), stale, missing_ref):
                    with self.subTest(retry=retry):
                        self.assertEqual(self.run_event(f, retry)['state'], 'unsynchronized')
                        self.assertEqual(provider.write_calls, writes)
                        self.assertEqual(provider.state[11]['option_id'], provider.policy['options']['todo'])
                        self.assertEqual(provider.fields['Priority'], 'Restart owner priority')
                decision = self.owner_decision(f, 'fresh-owner-decision')
                recovered = self.run_event(f, decision)
                self.assertEqual(recovered['state'], 'synchronized', recovered)
                self.assertEqual(provider.write_calls, writes + 1)
                self.assertEqual(provider.state[11]['option_id'], provider.policy['options']['in_progress'])
                self.assertEqual(provider.fields['Priority'], 'Restart owner priority')
                self.assertEqual(provider.fields['Sequence'], 'Owner sequence')
                self.assertEqual(registry.get('owned-flight')['status_sync']['pending'], {})
                audit = recovered['outcomes'][0]['reconciliation']
                self.assertEqual(audit['retired_intent'], old)
                self.assertEqual(audit['reference'], decision['reconciliation_reference'])
                self.assertEqual(audit['old_outcome'], 'unknown')
                self.assertNotEqual(recovered['outcomes'][0]['operation'], old['operation'])
        # An explicit recovery decision has its own bounded budget. Replaying it
        # cannot silently retire/reset that same uncertain operation again.
        with self.fixture() as f:
            provider = f[4]
            provider.modes = ['timeout_no_apply', 'timeout_no_apply']
            self.run_event(f)
            decision = self.owner_decision(f, 'new-budget')
            provider.modes = ['timeout_no_apply', 'timeout_no_apply']
            self.assertEqual(self.run_event(f, decision)['outcomes'][0]['reason'], 'retry_exhausted')
            self.assertEqual(provider.write_calls, 4)
            self.assertEqual(self.run_event(f, decision)['outcomes'][0]['reason'], 'retry_exhausted')
            self.assertEqual(provider.write_calls, 4)

    def test_repeat_start_after_manual_conflict(self):
        with self.fixture() as f:
            provider = f[4]
            provider.modes = ['timeout_manual']
            self.assertEqual(self.run_event(f)['outcomes'][0]['reason'], 'conflict')
            writes = provider.write_calls
            repeated = self.run_event(f)
            self.assertEqual(repeated['state'], 'unsynchronized', repeated)
            self.assertIn(repeated['outcomes'][0]['reason'], ('conflict', 'reconciliation_required'))
            self.assertEqual(provider.write_calls, writes)
            self.assertEqual(provider.state[11]['option_id'], provider.policy['options']['todo'])
            self.assertEqual(provider.fields['Priority'], 'Concurrent owner priority')
            recovered = self.run_event(f, self.owner_decision(f, 'manual-owner-decision'))
            self.assertEqual(recovered['state'], 'synchronized', recovered)
            self.assertEqual(provider.write_calls, writes + 1)
            self.assertEqual(provider.fields['Priority'], 'Concurrent owner priority')
            self.assertEqual(provider.fields['Sequence'], 'Owner sequence')

    def test_partial_merge_roadmap_and_automation_coverage(self):
        for metadata in (True, False):
            with self.subTest(metadata_available=metadata), self.fixture() as f:
                area, root, worker, registry, provider, sync = f
                base = self.flight_git(root, 'rev-parse', 'HEAD')
                (worker / 'partial.txt').write_text('accepted partial delivery\n')
                self.flight_git(worker, 'add', '.')
                self.flight_git(worker, 'commit', '-qm', 'Partial fixture delivery')
                head = self.flight_git(worker, 'rev-parse', 'HEAD')
                self.flight_git(root, 'merge', '--no-ff', '-qm', 'Integrated partial fixture', 'owned-flight')
                merged = self.flight_git(root, 'rev-parse', 'HEAD')
                delivery = {'repository': 'owner/repository', 'source_base': base, 'head': head,
                    'merge_commit': merged, 'merged': True, 'target': 'trunk', 'pull_request': 7}
                def partial(record):
                    record['pull_requests'] = [7]
                    record['lifecycle'] = {'state': 'merged', 'disposition': 'pending'}
                    record['status_sync']['work'][0]['scope'] = 'partial'
                    record['cleanup'] = {'protocol': 'required-v1', 'inventory': [], 'operations': [], 'state': 'pending',
                        'frozen_binding': {'source_head': head}, 'frozen_delivery': delivery,
                        'closure': {'complete': False, 'cleanup_complete': False,
                                    'blockers': ['Fixture worker disposition outstanding'], 'artifacts': []}}
                self.change(f, partial)
                provider.metadata_available = metadata
                before = copy.deepcopy(provider.state)
                fields = copy.deepcopy(provider.fields)
                event = self.event('accepted_completion', issues=[11, 99], completion={
                    'accepted': True, 'full_scope': False, 'reference': 'Fixture accepted integrated partial slice'},
                    expected={'11': provider.observe(11)}, reconciliation_reference='Fixture status-only decision')
                lifecycle = importlib.import_module('flight_lifecycle')
                with patch.object(lifecycle, '_discover_delivery', return_value=delivery), \
                        patch.object(lifecycle, '_push_endpoint', return_value='fixture endpoint'), \
                        patch.object(lifecycle, '_advertised', return_value=merged):
                    result = sync.synchronize(registry, 'owned-flight', event, checkout=root, provider=provider)
                with self.subTest(observable='completion'):
                    self.assertEqual(result['state'], 'unsynchronized', result)
                    self.assertEqual(result['outcomes'][0]['reason'], 'completion_unverified')
                with self.subTest(observable='no_status_or_closure'):
                    self.assertEqual(provider.state, before)
                    self.assertEqual(provider.mutations, [])
                    self.assertEqual(provider.closures, [])
                    self.assertEqual(provider.membership_writes, [])
                    self.assertEqual(provider.workflow_writes, [])
                    self.assertEqual(provider.fields, fields)
                with self.subTest(observable='automation_limit'):
                    # Disposition verification precedes provider setup, so neither
                    # configured metadata outcome has actually been inspected.
                    self.assertEqual(provider.automation_reads, 0)
                    self.assertFalse(result['automation']['available'])
                    self.assertFalse(result['automation']['semantics_available'])
                    self.assertEqual(result['automation']['inspection'], 'not_started')
                    self.assertIn('completion', result['automation']['detail'].lower())
                self.assertTrue(worker.exists())
                self.assertEqual(registry.get('owned-flight')['lifecycle']['disposition'], 'pending')
