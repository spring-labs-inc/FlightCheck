"""CODE-requested continuation across explicit and ordinary native invocations."""
import copy
import json
import unittest

import test_status_sync as witness
import test_status_sync_recovery as recovery


class StatusSyncRetryContinuationTests(unittest.TestCase):
    fixture = witness.StatusSynchronizationTests.fixture
    flight_git = witness.StatusSynchronizationTests.flight_git
    flight_repo = witness.StatusSynchronizationTests.flight_repo
    flight_checkout = witness.StatusSynchronizationTests.flight_checkout
    event = witness.StatusSynchronizationTests.event
    run_event = witness.StatusSynchronizationTests.run_event
    change = witness.StatusSynchronizationTests.change
    owner_decision = recovery.StatusSyncRecoveryTests.owner_decision

    def test_ordinary_retry_preserves_explicit_decision_budget(self):
        with self.fixture() as f:
            provider, registry = f[4], f[3]
            provider.modes = ['timeout_no_apply', 'timeout_no_apply']
            self.assertEqual(self.run_event(f)['outcomes'][0]['reason'], 'retry_exhausted')
            decision = self.owner_decision(f, 'explicit-owner-R')
            exact_event = json.dumps(decision, sort_keys=True).encode()
            original_write = provider.write
            def unavailable_immediate_readback(*args):
                try:
                    return original_write(*args)
                finally:
                    provider.unavailable = True
            provider.modes = ['timeout_no_apply']
            provider.write = unavailable_immediate_readback
            first = self.run_event(f, json.loads(exact_event))
            provider.write = original_write
            provider.unavailable = False
            self.assertEqual(first['outcomes'][0]['reason'], 'ambiguous')
            retained = copy.deepcopy(registry.get('owned-flight')['status_sync']['pending']['11'])
            self.assertEqual(retained['attempts'], 1)
            self.assertEqual(retained['reconciliation_reference'], decision['reconciliation_reference'])
            audits = copy.deepcopy(registry.get('owned-flight')['status_sync']['reconciliations'])
            self.assertEqual(len(audits), 1)
            self.assertEqual(provider.write_calls, 3)
            before = provider.observe(11)
            fields = copy.deepcopy(provider.fields)
            provider.modes = ['timeout_no_apply']
            ordinary = self.run_event(f, self.event())
            self.assertEqual(ordinary['outcomes'][0]['reason'], 'retry_exhausted')
            self.assertEqual(provider.write_calls, 4)
            pending = registry.get('owned-flight')['status_sync']['pending']['11']
            with self.subTest(observable='persisted_decision_identity'):
                self.assertEqual(pending['operation'], retained['operation'])
                self.assertEqual(pending['attempts'], 2)
                self.assertEqual(pending['reconciliation_reference'], decision['reconciliation_reference'])
            replay = self.run_event(f, json.loads(exact_event))
            with self.subTest(observable='identical_replay_is_exhausted'):
                self.assertEqual(replay['state'], 'unsynchronized', replay)
                self.assertEqual(replay['outcomes'][0]['reason'], 'retry_exhausted')
            with self.subTest(observable='no_new_authority_or_actions'):
                self.assertEqual(provider.write_calls, 4)
                self.assertEqual(provider.mutations, [])
                self.assertEqual(provider.observe(11), before)
                self.assertEqual(provider.fields, fields)
                self.assertEqual(registry.get('owned-flight')['status_sync']['reconciliations'], audits)
                self.assertEqual(registry.get('owned-flight')['status_sync']['pending']['11']['operation'], retained['operation'])
