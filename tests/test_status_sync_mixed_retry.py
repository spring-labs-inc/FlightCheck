"""Real adapter mixed dispatched/read/retry boundary; transport injection only."""
import copy
import json
import subprocess
import unittest

import test_status_sync_readback as readback


class StatusSyncMixedRetryTests(unittest.TestCase):
    fixture = readback.StatusSyncReadbackTests.fixture
    flight_git = readback.StatusSyncReadbackTests.flight_git
    flight_repo = readback.StatusSyncReadbackTests.flight_repo
    flight_checkout = readback.StatusSyncReadbackTests.flight_checkout
    event = readback.StatusSyncReadbackTests.event
    adapter_fixture = readback.StatusSyncReadbackTests.adapter_fixture
    execute = readback.StatusSyncReadbackTests.execute

    def test_earlier_dispatch_survives_retry_predispatch_read_failure(self):
        with self.fixture() as f:
            adapter, live = self.adapter_fixture(f)
            original_runner = adapter.runner
            original_option, original_timestamp = live['option'], live['updated']
            phase = {'value': 'initial', 'reconciliation_reads': 0, 'retry_comparison_failures': 0}
            def runner(argv, **kwargs):
                query = json.loads(kwargs['input'])['query']
                if 'mutation(' in query and phase['value'] != 'restored':
                    result = original_runner(argv, **kwargs)
                    phase['value'] = 'fail_immediate_readback'
                    return result
                if phase['value'] == 'fail_immediate_readback':
                    self.assertIn('field:node', query)
                    result = original_runner(argv, **kwargs)
                    self.assertNotEqual(result.returncode, 0)
                    live['outage'] = False
                    phase['value'] = 'stale_reconciliation'
                    return result
                if phase['value'] == 'stale_reconciliation':
                    # The transport serves an exact stale preimage while the
                    # fixture's actual provider state remains the applied target.
                    actual = live['option'], live['updated']
                    live.update(option=original_option, updated=original_timestamp)
                    try:
                        result = original_runner(argv, **kwargs)
                    finally:
                        live.update(option=actual[0], updated=actual[1])
                    phase['reconciliation_reads'] += 1
                    if 'fieldValues(' in query:
                        phase['value'] = 'fail_retry_comparison'
                    return result
                if phase['value'] == 'fail_retry_comparison':
                    self.assertIn('field:node', query)
                    phase['retry_comparison_failures'] += 1
                    phase['value'] = 'after_retry_failure'
                    return subprocess.CompletedProcess(argv, 1, '', 'Fixture retry failed before dispatch')
                return original_runner(argv, **kwargs)
            adapter.runner = runner
            exact_event = json.dumps(self.event(), sort_keys=True).encode()
            first = self.execute(f, adapter, json.loads(exact_event))
            original = copy.deepcopy(live['intent_at_dispatch'])
            self.assertEqual(first['state'], 'unsynchronized')
            self.assertEqual(len(live['mutations']), 1)
            self.assertEqual(phase['reconciliation_reads'], 3)
            self.assertEqual(phase['retry_comparison_failures'], 1)
            self.assertEqual(live['option'], f[4].policy['options']['in_progress'])
            pending = f[3].get('owned-flight')['status_sync']['pending'].get('11')
            with self.subTest(observable='earlier_dispatch_remains_recoverable'):
                self.assertIsInstance(pending, dict)
                self.assertEqual(pending['operation'], original['operation'])
                self.assertEqual(pending['before'], original['before'])
                self.assertGreaterEqual(pending['attempts'], original['attempts'])
                self.assertLessEqual(pending['attempts'], 2)
            live.update(option=f[4].policy['options']['todo'], updated='manual-after-mixed-outage',
                        Priority='Owner priority after mixed outage', outage=False)
            phase['value'] = 'restored'
            replay = self.execute(f, adapter, json.loads(exact_event))
            with self.subTest(observable='identical_replay_preserves_manual_status'):
                self.assertEqual(replay['state'], 'unsynchronized', replay)
                self.assertEqual(replay['outcomes'][0]['reason'], 'conflict')
                self.assertEqual(live['option'], f[4].policy['options']['todo'])
                self.assertEqual(live['updated'], 'manual-after-mixed-outage')
            with self.subTest(observable='no_extra_dispatch_or_unrelated_field_change'):
                self.assertEqual(len(live['mutations']), 1)
                self.assertEqual(live['Priority'], 'Owner priority after mixed outage')
                self.assertEqual(live['Sequence'], 'Owner sequence')
            with self.subTest(observable='original_operation_and_budget_still_retained'):
                self.assertEqual(f[3].get('owned-flight')['status_sync']['pending'].get('11'), pending)
