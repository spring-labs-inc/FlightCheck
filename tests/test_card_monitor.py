"""Bounded supervisor behavior without waiting for wall-clock expiry."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CARD = Path(__file__).resolve().parents[1] / 'status-card'
sys.path.insert(0, str(CARD))
spec = importlib.util.spec_from_file_location('card_connector', CARD/'connect.py')
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)


class Child:
    def __init__(self, pid):
        self.pid, self.stopped, self.terminated = pid, False, 0
    def poll(self):
        return 0 if self.stopped else None
    def terminate(self):
        self.stopped = True
        self.terminated += 1
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self.stopped = True


class CardMonitorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.args = argparse.Namespace(task='test-change')
        self.initial = {'user_url':'http://127.0.0.1:31234/task/test-change/',
                        'host_url':'http://127.0.0.1:31235/task/test-change/'}
        self.observed = {'task':'test-change', 'candidate':'a'*64,
                         'host_url':self.initial['host_url'], 'publication':'verified',
                         'snapshot':{'task':'test-change', 'candidate':'a'*64,
                                     'freshness':{'state':'active','owner_remaining_seconds':120,
                                                  'heartbeat_age_seconds':1,'owner_expires_at':'2026-11-23T23:00:00Z'}}}
        self.now = 0
    def clock(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds
    def run_monitor(self, child=None, lifetime=80):
        return connector.monitor(self.args, self.directory, self.initial, child,
                                 clock=self.clock, sleep=self.sleep, interval=1, lifetime=lifetime)

    def test_private_helper_binding_verifies_bytes_and_refuses_symlinks(self):
        bound = connector.bind_helpers(self.directory)
        self.assertEqual(bound, connector.bind_helpers(self.directory))
        helper = bound/'connect.py'
        original = helper.read_bytes()
        helper.write_bytes(original + b'\n# altered\n')
        with self.assertRaises(ValueError):
            connector.bind_helpers(self.directory)
        helper.unlink()
        helper.symlink_to(CARD/'connect.py')
        with self.assertRaises(ValueError):
            connector.bind_helpers(self.directory)

    def test_bounded_owned_recovery(self):
        owned = Child(1001)
        unrelated = Child(9999)
        replacements = [Child(number) for number in (1002,1003,1004,1005)]
        with patch.object(connector, 'remote_observation', return_value=self.observed), \
             patch.object(connector, 'forward_snapshot', return_value=None), \
             patch.object(connector.maintainer, 'current_card', return_value=None), \
             patch.object(connector, 'available', return_value=True), \
             patch.object(connector, 'start_forward', side_effect=replacements) as start:
            state = self.run_monitor(owned)
        self.assertEqual(start.call_count, 3)
        self.assertEqual(state['attempts'], 3)
        self.assertEqual(state['status'], 'disconnected')
        self.assertLess(self.now, 80)
        self.assertEqual(owned.terminated, 1)
        self.assertEqual([child.terminated for child in replacements], [1,1,1,0])
        self.assertEqual(unrelated.terminated, 0)

    def test_owned_recovery_identity_loss(self):
        # A stored PID cannot become a runtime child ownership handle.
        (self.directory/'connection.json').write_text(json.dumps({'pid':9999}))
        with patch.object(connector, 'remote_observation', return_value=self.observed), \
             patch.object(connector, 'forward_snapshot', return_value=None), \
             patch.object(connector.maintainer, 'current_card', return_value=None), \
             patch.object(connector, 'available', return_value=False), \
             patch.object(connector, 'start_forward') as start, \
             patch.object(connector.os, 'kill') as kill:
            state = self.run_monitor()
        self.assertEqual(state['status'], 'unavailable')
        self.assertIn('Ownership unavailable', state['error'])
        start.assert_not_called()
        kill.assert_not_called()
        self.assertEqual(json.loads((self.directory/'connection.json').read_text()), {'pid':9999})

    def test_stale_producer_is_distinct_from_disconnected_route(self):
        self.observed['snapshot']['freshness']['heartbeat_age_seconds'] = 31
        with patch.object(connector, 'remote_observation', return_value=self.observed) as remote, \
             patch.object(connector, 'start_forward') as start:
            state = self.run_monitor(lifetime=3)
        self.assertEqual(state['transport'], 'verified')
        self.assertFalse(any(call.kwargs.get('recover') for call in remote.call_args_list))
        start.assert_not_called()

    def test_dead_worker_listener_uses_lease_preserving_recovery(self):
        observations = []
        def observe(args, recover=False, timeout=20):
            observations.append(recover)
            value = json.loads(json.dumps(self.observed))
            value['publication'] = 'verified' if recover or len(observations) > 1 else 'unavailable'
            return value
        with patch.object(connector, 'remote_observation', side_effect=observe), \
             patch.object(connector, 'prepare_remote') as prepare, \
             patch.object(connector, 'forward_snapshot', return_value={'task':'test-change','publicationPort':31235,'candidate':'a'*64}), \
             patch.object(connector.maintainer, 'current_card', return_value=self.observed['snapshot']):
            state = self.run_monitor(lifetime=3)
        self.assertEqual(observations.count(True), 1)
        self.assertEqual(state['attempts'], 1)
        prepare.assert_not_called()
        self.assertEqual(self.observed['snapshot']['freshness']['owner_expires_at'], '2026-11-23T23:00:00Z')

    def test_expiry_inside_recovery(self):
        # Authorization can end inside any blocking recovery/probe/cleanup
        # step. The same observed expiry never grants another lifetime.
        for boundary in ('worker_recovery', 'forward_probe', 'card_probe', 'owned_cleanup', 'expired_reply'):
            with self.subTest(boundary=boundary):
                self.now = 0
                observed = json.loads(json.dumps(self.observed))
                observed['snapshot']['freshness']['owner_remaining_seconds'] = 1
                observed['publication'] = 'unavailable' if boundary in ('worker_recovery', 'expired_reply') else 'verified'
                remote_timeouts = []
                owned = Child(1001)
                unrelated = Child(9999)
                original_terminate = owned.terminate
                def terminate():
                    original_terminate()
                    if boundary == 'owned_cleanup':
                        self.now += 5
                owned.terminate = terminate
                def remote(args, recover=False, timeout=20):
                    value = json.loads(json.dumps(observed))
                    if recover:
                        remote_timeouts.append(timeout)
                        value['publication'] = 'verified'
                        if boundary == 'worker_recovery':
                            self.now += 5
                        elif boundary == 'expired_reply':
                            value['snapshot']['freshness'].update(state='expired', owner_remaining_seconds=0)
                    return value
                def forward(*args, **kwargs):
                    if boundary == 'forward_probe':
                        self.now += 5
                    return None
                def card(*args, **kwargs):
                    if boundary == 'card_probe':
                        self.now += 5
                    return None
                with patch.object(connector, 'remote_observation', side_effect=remote), \
                     patch.object(connector, 'forward_snapshot', side_effect=forward), \
                     patch.object(connector.maintainer, 'current_card', side_effect=card), \
                     patch.object(connector, 'available', return_value=True), \
                     patch.object(connector, 'start_forward', return_value=Child(1002)) as start, \
                     patch.object(connector.os, 'kill') as kill:
                    state = self.run_monitor(owned)
                start.assert_not_called()
                kill.assert_not_called()
                self.assertEqual(state['status'], 'producer_expired')
                self.assertIn('resume', state['error'].lower())
                self.assertEqual(owned.terminated, 1)
                self.assertEqual(unrelated.terminated, 0)
                self.assertTrue(all(timeout <= 1 for timeout in remote_timeouts))
                self.assertFalse((self.directory/'connection.json').exists())

    def test_same_expiry_cannot_extend_local_owner_lifetime(self):
        # A replayed server age or rolled-back wall clock cannot extend ownership.
        self.observed['snapshot']['freshness']['owner_remaining_seconds'] = 4
        with patch.object(connector, 'remote_observation', return_value=self.observed), \
             patch.object(connector, 'forward_snapshot', return_value={'task':'test-change','publicationPort':31235,'candidate':'a'*64}), \
             patch.object(connector.maintainer, 'current_card', return_value=self.observed['snapshot']):
            state = self.run_monitor(lifetime=30)
        self.assertEqual(state['status'], 'producer_expired')
        self.assertLessEqual(self.now, 5)

    def test_closed_final_route_is_retained_without_monitor_ownership(self):
        child = Child(1001)
        self.observed['snapshot']['freshness']['state'] = 'closed'
        with patch.object(connector, 'remote_observation', return_value=self.observed), \
             patch.object(connector.maintainer, 'current_card', return_value=self.observed['snapshot']):
            state = self.run_monitor(child)
        self.assertEqual(state['status'], 'producer_closed')
        self.assertEqual(state['ownership'], 'relinquished')
        self.assertEqual(child.terminated, 0)

    def test_wrong_task_and_expired_lease_never_repair(self):
        for mismatch in ('wrong-task', 'expired'):
            with self.subTest(mismatch=mismatch):
                self.now = 0
                observed = json.loads(json.dumps(self.observed))
                if mismatch == 'wrong-task':
                    observed['snapshot']['task'] = 'other-task'
                else:
                    observed['snapshot']['freshness']['owner_remaining_seconds'] = 0
                with patch.object(connector, 'remote_observation', return_value=observed), \
                     patch.object(connector, 'start_forward') as start:
                    state = self.run_monitor()
                self.assertIn(state['status'], ('unavailable', 'producer_expired'))
                start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
