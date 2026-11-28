"""Settings preference selection at the real required lifecycle planner."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest

from lifecycle_cases import LifecycleCases, PRODUCT
import test_settings as fixtures


class SettingsCleanupTests(LifecycleCases, unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli

    def inventory(self, **kwargs):
        rows = [row for row in super().inventory(**kwargs) if row['kind'] != 'remote_branch']
        rows.append({'kind': 'remote_branch', 'identity': 'refs/heads/remote-reserved', 'remote': 'origin'})
        if not getattr(self, '_extra_refs_created', False):
            for branch in ('automatic-local', 'unfinished-local'):
                self.git(self.root, 'branch', branch, self.base)
            self._extra_refs_created = True
        return rows + [{'kind': 'local_branch', 'identity': 'refs/heads/' + name} for name in ('automatic-local', 'unfinished-local')]

    def test_settings_drives_actual_automatic_action_queue_without_disposition_authority(self):
        with self.world(), self.config_fixture() as (_, template, engine, installed, cli, supplied):
            from flightcheck_cli.settings import Settings
            # Install only into this already-owned disposable control project,
            # preserving its synthetic prior config before explicit setup.
            prior = (self.root / self.config.CONFIG).read_bytes()
            (self.area / 'pre-settings-project.json').write_bytes(prior)
            (self.root / self.config.CONFIG).unlink()
            source = Path(installed.__file__).resolve().parent.parent
            values = dict(supplied, default_branch='trunk')
            result, config, operations = installed.plan_installation(source, self.root, installed.load_manifest(), 'codex', values)
            installed.apply_plan(self.root, operations)
            (self.root / '.flightcheck/distribution.json').write_bytes(cli.encoded({'schema': 1, 'source_revision': result['source']['revision'], 'runtime': cli.runtime_identity(config)}))
            self.git(self.root, 'update-ref', 'refs/heads/automatic-local', self.head)
            self.git(self.source, 'push', '--quiet', 'origin', 'HEAD:refs/heads/remote-reserved')
            (self.source / 'retained-owner-work.txt').write_text('Preserve this worktree; Settings cannot waive it\n')
            # A separate unresolved native record reserves the actual remote
            # branch. Its unknown outcome and exact namespace remain untouched.
            reservation_worker = self.worktree(self.area / 'reserved-worker', 'native-reservation-worker')
            other = self.record(reservation_worker, 'native-reservation')
            native = {'kind': 'native_operation', 'identity': 'fixture-unknown-call', 'client': 'codex', 'requested_name': 'fixture-pending', 'outcome': 'unknown', 'observation_reference': 'Retained actual fixture unknown observation', 'reservations': {'paths': [], 'refs': ['refs/heads/remote-reserved'], 'names': ['fixture-pending']}}
            other['grants']['cleanup'] = [{'authority': 'owner', 'reference': 'Fixture reserves only this observed namespace', 'inventory': [native]}]
            self.registry.save(other, expected_revision=self.registry.read()["revision"])
            self.life.register_cleanup(self.root, self.registry, other['flight'], inventory=[native], reference=other['grants']['cleanup'][0]['reference'])
            reservation = copy.deepcopy(self.registry.get(other['flight']))
            owner = Settings(engine, self.root, registry=self.registry.directory, reference='Owner persistent cleanup preferences')
            original = copy.deepcopy(self.registry.get('fixture'))
            def save(enabled):
                preview = owner.preview({'changes': {'cleanup_policy': {'local_branches': enabled}}, 'expected_revision': owner.read()['revision']})
                owner.apply({'plan_id': preview['plan_id']})
                with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                    with self.guard.settings_execution(self.source, {'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}}, adopt=True): pass
                self.assertEqual(self.registry.get('fixture')['configuration']['revision'], owner.read()['revision'])
            save(False)
            off = self.plan()
            save(True)
            on = self.plan()
            proposals = on.get('next_actions', [])
            self.assertTrue(any(row.get('identity') == 'refs/heads/automatic-local' for row in proposals), 'Normal plan must present the eligible explicitly granted local branch as a concrete automatic action')
            self.assertFalse(off.get('next_actions', []))
            self.assertEqual({row['identity'] for row in proposals}, {'refs/heads/automatic-local'})
            self.assertTrue(all(row['command'][-2:] == ['--artifact', row['artifact']] for row in proposals))
            # Selection is presentation only, separate from mandatory #81
            # inventory/disposition and every exact grant/reservation.
            for report in (off, on):
                self.assertEqual(len(report['artifacts']), len(original['cleanup']['inventory']))
                self.assertTrue(self.source.exists())
                self.assertEqual(self.remote_tip("refs/heads/remote-reserved"), self.head)
                self.assertEqual(self.git(self.root, 'rev-parse', 'automatic-local'), self.head)
                self.assertEqual(self.registry.get('fixture')['grants'], original['grants'])
                self.assertEqual(self.registry.get('fixture')['cleanup'], original['cleanup'])
                self.assertEqual(self.registry.get(other['flight']), reservation)
            # Policy toggles do not remove rows or change their safety verdicts.
            fields = ('id', 'kind', 'identity', 'state', 'disposition', 'reason_code', 'reservations', 'requires')
            project = lambda report: [{key: row.get(key) for key in fields} for row in report['artifacts']]
            self.assertEqual(project(off), project(on))
            # The real normal CLI presents the same concrete review queue.
            client_file=self.area/'client.json';client_file.write_text(json.dumps(self.client_state))
            preservation_file=self.area/'preservation.json';preservation_file.write_text(json.dumps(self.saved_assets))
            output=io.StringIO()
            with patch.object(self.life,'_discover_delivery',return_value=self.delivery),contextlib.redirect_stdout(output):
                self.life.main(['plan','--checkout',str(self.root),'--registry',str(self.registry.directory),'--flight','fixture','--client-state',str(client_file),'--preservation',str(preservation_file)])
            presented=json.loads(output.getvalue())
            self.assertEqual([row['identity'] for row in presented['next_actions']],['refs/heads/automatic-local'])
            save(False)
            off=self.plan();self.assertFalse(off.get('next_actions', []))
            # Off affects automatic proposals, never mandatory independent #81
            # disposition. Existing scoped apply still acts on an exact grant.
            branch=next(row for row in off['artifacts'] if row['identity']=='refs/heads/automatic-local')
            self.apply(off,artifact_id=branch['id'])
            frozen=copy.deepcopy(self.registry.get('fixture'))
            self.assertTrue(frozen['cleanup']['frozen_binding'])
            preview=owner.preview({'changes':{'cleanup_policy':{'local_branches':True}},'expected_revision':owner.read()['revision']})
            pending=owner.apply({'plan_id':preview['plan_id']})
            self.assertTrue(any(row['flight']=='fixture' for row in pending['adoption']['deferred']))
            self.assertEqual(self.registry.get('fixture'),frozen,'Save cannot rewrite an established disposition lease')
            self.assertEqual(self.registry.get(other['flight']),reservation)
            self.assertEqual(self.remote_tip('refs/heads/remote-reserved'),self.head)
            self.assertTrue(self.source.exists())
