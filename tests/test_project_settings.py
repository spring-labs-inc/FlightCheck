"""Project saves, real recorder boundaries and project-only authorization."""
import copy
import http.client
import hashlib
import json
import os
import signal
from urllib.parse import urlsplit, parse_qs
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from checkout_guard_cases import CheckoutCases, PRODUCT
import test_settings as fixtures
import test_settings_check_boundaries as boundary_fixtures


class ProjectSettingsTests(CheckoutCases, unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli
    installed_flight = boundary_fixtures.SettingsCheckBoundaryTests.installed_flight
    save = boundary_fixtures.SettingsCheckBoundaryTests.save
    command = boundary_fixtures.SettingsCheckBoundaryTests.command
    source_fingerprint = boundary_fixtures.SettingsCheckBoundaryTests.source_fingerprint
    named = boundary_fixtures.SettingsCheckBoundaryTests.named
    run_capture = boundary_fixtures.SettingsCheckBoundaryTests.run_capture
    receipt = boundary_fixtures.SettingsCheckBoundaryTests.receipt
    gate = boundary_fixtures.SettingsCheckBoundaryTests.gate
    task = boundary_fixtures.SettingsCheckBoundaryTests.task
    handoff = boundary_fixtures.SettingsCheckBoundaryTests.handoff

    def test_paused_save_resumes_through_normal_boundary_and_reconciles_checks(self):
        with self.installed_flight(lambda area: [{'name': 'alpha', 'command': self.command('paused-old'), 'phase': 'cheap'}]) as (owner, _):
            definition = owner.read()['values']['checks'][0]
            old_args = self.named(definition['command'], 'alpha')
            first = self.run_capture(old_args)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            old_path, old_receipt = self.receipt('alpha'); old_bytes = old_path.read_bytes()
            task = self.task([self.gate('alpha')]); self.handoff('preflight', task)
            paused = self.registry.get('fixture'); paused['lifecycle']['state'] = 'paused'
            self.registry.save(paused, expected_revision=self.registry.read()['revision'])
            original = self.registry.get('fixture')
            replacement = self.command('paused-new')
            saved = self.save(owner, {'checks': [{'name': 'alpha', 'command': replacement, 'phase': 'authoritative'}]})
            during = self.registry.get('fixture')
            for key in ('configuration', 'checkout_guard', 'grants', 'checkout', 'children', 'lifecycle'):
                self.assertEqual(during[key], original[key], 'Save must preserve paused ' + key)
            self.assertEqual(during.get('configuration_history'), original.get('configuration_history'))
            self.assertEqual(old_path.read_bytes(), old_bytes)
            with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                self.guard.reconcile(self.registry, 'fixture', self.root, 'Owner normally resumes paused work', session='session-1', policy=self.policy)
            resumed = self.registry.get('fixture')
            self.assertEqual(resumed['lifecycle']['state'], 'active')
            self.assertEqual(resumed['configuration'], original['configuration'], 'Reconciliation preserves capture until its safe execution boundary')
            denied = self.run_capture(old_args)
            self.assertNotEqual(denied.returncode, 0, 'Resumed old command/classification must not execute: ' + denied.stdout + denied.stderr)
            self.assertIn('changed', denied.stdout + denied.stderr)
            self.assertIn('fixture', saved['adoption']['queued'])
            adopted = self.registry.get('fixture')
            self.assertEqual(adopted['configuration']['revision'], saved['revision'])
            self.assertEqual(adopted['checkout_guard']['configuration_revision'], saved['revision'])
            self.assertEqual(adopted['grants'], original['grants'])
            self.assertEqual(adopted['checkout'], original['checkout'])
            self.assertEqual(adopted['children'], original['children'])
            self.assertEqual(adopted['configuration_history'][-1], original['configuration'])
            self.assertEqual(adopted['checkout_guard']['history'][:len(original['checkout_guard']['history'])], original['checkout_guard']['history'])
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertEqual((self.area / 'paused-old').read_text().splitlines(), ['run'])
            stale = self.handoff('checks', task)['checks'][0]
            self.assertEqual(stale['status'], 'unverified')
            fresh = self.run_capture(self.named(replacement, 'alpha'))
            self.assertEqual(fresh.returncode, 0, fresh.stdout + fresh.stderr)
            new_path, receipt = self.receipt('alpha')
            self.assertNotEqual(new_path, old_path)
            self.assertEqual(receipt['request']['configuration_check']['phase'], 'authoritative')
            self.assertEqual(receipt['inputs_before'], old_receipt['inputs_before'])
            self.assertEqual((self.area / 'paused-new').read_text().splitlines(), ['run'])
            task['gates'] = [self.gate('alpha')]
            self.handoff('preflight', task, amend=True)
            current = self.handoff('checks', task)['checks'][0]
            self.assertEqual(current['status'], 'passed'); self.assertEqual(Path(current['receipt']), new_path)
            self.assertEqual(old_path.read_bytes(), old_bytes)

    def queue(self, revision, reference):
        base = self.area / "project-transactions"; base.mkdir(mode=0o700, exist_ok=True)
        state = base / hashlib.sha256(str(self.root).encode()).hexdigest()[:24]; state.mkdir(mode=0o700, exist_ok=True)
        return self.registry.queue_configuration(self.root, revision, reference, transaction_state=state)

    def wait_file(self, path):
        deadline = time.monotonic() + 15
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(path.exists(), str(path))

    def test_overlapping_recorders_adopt_after_receipts_and_reuse_only_unaffected(self):
        with self.fixture():
            self.git(self.root, 'switch', '-c', 'work')
            self.adopt(self.root)
            original = self.registry.get('fixture')
            self.assertTrue(callable(getattr(self.registry, 'queue_configuration', None)), 'Single Save needs actual project adoption intents')
            events = self.area / 'events'; events.mkdir()
            evidence = self.area / 'checks'
            script = PRODUCT / 'workflow/scripts/capture_check.py'
            command = "from pathlib import Path;import time; p=Path(__import__('sys').argv[1]);p.with_suffix('.ready').touch();\nwhile not p.with_suffix('.go').exists(): time.sleep(.02)\nwith p.with_suffix('.runs').open('a') as f:f.write('run\\n')"
            def args(name):
                return [sys.executable, '-B', str(script), '--evidence-dir', str(evidence), '--create-evidence-dir', '--candidate', 'fixture-source', '--scope', 'Known check-only assumptions', '--gate', name, '--owner', 'worker', '--configuration-dependencies', '["checks","python","required_runtimes"]', '--fingerprint-command', json.dumps([sys.executable, '-B', '-c', "print('frozen full fixture input')"]), '--checkout-binding', json.dumps({'registry': str(self.registry.directory), 'flight': 'fixture'}), '--', sys.executable, '-B', '-c', command, str(events / name)]
            env = dict(self.env, CODEX_THREAD_ID='session-1')
            processes = []
            try:
                for name in ('first', 'second'):
                    processes.append(subprocess.Popen(args(name), cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
                    self.wait_file(events / (name + '.ready'))
                before = self.config.snapshot(self.root)
                values = self.config.propose(self.root, before, {'resources': {'documentation': 'docs'}}, before['revision'], 'Owner project Save')
                revision = self.config.revision(self.config.encoded(values))
                self.queue(revision, 'Owner project Save')
                self.assertEqual(self.registry.get('fixture')['configuration'], original['configuration'])
                (self.root / self.config.CONFIG).write_bytes(self.config.encoded(values))
                (events / 'first.go').touch()
                output = processes[0].communicate(timeout=20)[0]; self.assertEqual(processes[0].returncode, 0, output)
                self.assertEqual(self.registry.get('fixture')['configuration'], original['configuration'])
                (events / 'second.go').touch()
                output = processes[1].communicate(timeout=20)[0]; self.assertEqual(processes[1].returncode, 0, output)
                adopted = self.registry.get('fixture')
                self.assertEqual(adopted['configuration']['revision'], revision)
                self.assertEqual(adopted['grants'], original['grants'])
                self.assertEqual(adopted['checkout'], original['checkout'])
                self.assertEqual(adopted['configuration_history'][0], original['configuration'])
                for record in evidence.glob('check-*/run.json'):
                    receipt = json.loads(record.read_text())
                    self.assertEqual(receipt['status'], 'finished')
                    self.assertEqual(receipt['inputs_before'], receipt['inputs_after'])
                    self.assertEqual(receipt['checkout_context']['configuration_revision'], original['configuration']['revision'])
                    self.assertEqual(receipt['checkout_context_after']['configuration_revision'], original['configuration']['revision'])
                reused = subprocess.run(args('first'), cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(reused.returncode, 0, reused.stdout + reused.stderr)
                self.assertIn('Check reused:', reused.stdout)
                self.assertEqual((events / 'first.runs').read_text().splitlines(), ['run'])
                capture = self.module("capture_check")
                old_context = json.loads(next(evidence.glob('check-*/run.json')).read_text())["checkout_context"]
                current_context = json.loads(next(evidence.glob('reuse-*/reuse.json')).read_text())['checkout_context']
                self.assertTrue(capture.same_pass_checkout(old_context, current_context, ['checks', 'python', 'required_runtimes']))
                self.assertFalse(capture.same_pass_checkout(old_context, current_context, ["checkz"]))
                implicit = copy.deepcopy(current_context)
                implicit['settings_adoptions'][-1]['required_revalidation'].append('status_sync')
                self.assertFalse(capture.same_pass_checkout(old_context, implicit, ["status_sync"]))
                before = self.config.snapshot(self.root)
                checks = copy.deepcopy(before['values']['checks']); checks[0]['phase'] = 'authoritative'
                values = self.config.propose(self.root, before, {'checks': checks}, before['revision'], 'Owner changes check assumptions')
                self.queue(self.config.revision(self.config.encoded(values)), 'Owner changes check assumptions')
                (self.root / self.config.CONFIG).write_bytes(self.config.encoded(values))
                rerun = subprocess.run(args('first'), cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
                self.assertNotEqual(rerun.returncode, 0, 'Changed check definitions require trusted request reconciliation')
                self.assertIn('reconcil', rerun.stdout + rerun.stderr)
                self.assertEqual((events / 'first.runs').read_text().splitlines(), ['run'])
            finally:
                for process in processes:
                    if process.poll() is None: process.kill(); process.communicate()

    def test_intent_requires_published_revision_and_preserves_frozen_work(self):
        with self.fixture():
            self.git(self.root, 'switch', '-c', 'work'); self.adopt(self.root)
            before = self.registry.get('fixture')
            self.queue('a' * 64, 'Save interrupted before canonical apply')
            with self.guard.settings_execution(self.root, {'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}}, adopt=True):
                self.assertEqual(self.registry.get('fixture')['configuration'], before['configuration'])
            self.assertEqual(self.registry.get('fixture')['configuration'], before['configuration'])
            # A published A must remain adoptable if a later B queued but failed.
            prior = self.config.snapshot(self.root)
            values = self.config.propose(self.root, prior, {'resources': {'documentation': 'saved-A'}}, prior['revision'], 'A committed Save')
            revision = self.config.revision(self.config.encoded(values))
            self.queue(revision, 'A committed Save')
            (self.root / self.config.CONFIG).write_bytes(self.config.encoded(values))
            self.queue('c' * 64, 'B failed before publication')
            with self.guard.settings_execution(self.root, {'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}}, adopt=True):
                self.assertEqual(self.registry.get('fixture')['configuration']['revision'], revision)
            self.assertEqual(self.registry.get('fixture')['pending_configuration']['revision'], 'c' * 64)
            frozen = self.registry.get('fixture'); frozen['cleanup']['frozen_binding'] = {'reservation': 'preserve'}
            self.registry.save(frozen, expected_revision=self.registry.read()['revision'])
            raw = self.registry.path.read_bytes()
            result = self.queue('b' * 64, 'Later project Save')
            self.assertFalse(result['queued']); self.assertTrue(result['deferred'])
            self.assertEqual(self.registry.path.read_bytes(), raw)

    def test_project_session_without_flight_and_inherited_main_tracker(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            from flightcheck_cli import settings
            service = settings.Settings(engine, root, reference='Owner authorizes project settings')
            self.assertEqual(service.read()['status'], 'configuration')
            values = copy.deepcopy(service.read()['values']); values.pop('nit_tracker', None)
            model = cli.configuration_model(engine, root)
            normalized = model.normalize(root, values, trusted_metadata=True, probe_runtime=False)
            self.assertIsNone(normalized['nit_tracker'])
            normalized['resources']['issue_tracker'] = 'https://tracker.invalid/project'
            self.assertEqual(model.minor_tracker(normalized), normalized['resources']['issue_tracker'])
            normalized['resources']['issue_tracker'] = 'https://tracker.invalid/replacement'
            self.assertEqual(model.minor_tracker(normalized), normalized['resources']['issue_tracker'])
            # Real copied CLI launch: the owner supplies a project and editing
            # authority only. Internal transport IDs come from the existing session.
            env = dict(self.config_env, FLIGHTCHECK_STATE_DIR=str(area / 'project-private-state'))
            command = [sys.executable, '-B', str(root / '.flightcheck/install.py'), 'settings', str(root), '--authorize-local-settings', 'Owner authorizes persistent project Settings']
            launched = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            publication = json.loads(launched.stdout)
            endpoint = json.loads(Path(publication['endpoint']).read_bytes())
            try:
                self.assertEqual(publication['status'], 'project_settings')
                route = urlsplit(publication['host_preview_url']); fragment = {k:v[0] for k,v in parse_qs(route.fragment).items()}
                headers = {'Authorization': 'Bearer ' + fragment['cap'], **{'X-FlightCheck-' + k.title():v for k,v in fragment.items() if k != 'cap'}}
                connection = http.client.HTTPConnection(route.hostname, route.port, timeout=5)
                connection.request('GET', route.path + 'api/read', headers=headers); response = connection.getresponse(); before = json.loads(response.read())
                self.assertEqual(response.status, 200); self.assertEqual(before['authorization_scope'], 'project')
                def post(action, values):
                    connection.request('POST', route.path + 'api/' + action, body=json.dumps(values), headers={**headers, 'Content-Type':'application/json', 'Origin': 'http://' + route.netloc})
                    response = connection.getresponse(); values = json.loads(response.read()); self.assertEqual(response.status, 200, values); return values
                plan = post('preview', {'changes': {'nit_tracker': None, 'resources': {'issue_tracker': 'https://tracker.invalid/current'}}, 'expected_revision':before['revision']})
                self.assertEqual(plan['effects']['deferred'], [])
                post('apply', {'plan_id':plan['plan_id']})
                current = cli.configuration_model(engine, root).snapshot(root)
                self.assertEqual(model.minor_tracker(current['values']), 'https://tracker.invalid/current')
                self.assertIn('https://tracker.invalid/current', (root / '.flightcheck/docs/status.md').read_text())
                again = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                self.assertEqual(json.loads(again.stdout)['endpoint'], publication['endpoint'])
                connection.close()
            finally:
                # This fixture owns only the listener it just launched. No inherited
                # artifact, worker, reservation or client process is touched.
                os.kill(endpoint['pid'], signal.SIGTERM)
            with settings.project_server(service, PRODUCT / 'status-card') as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    connection.request('GET', server.status_route); response = connection.getresponse(); html = response.read().decode()
                    self.assertEqual(response.status, 200); self.assertIn('[ SETTINGS ]', html); self.assertNotIn(service.token, html)
                    connection.request('GET', server.route + 'api/read'); response = connection.getresponse(); response.read(); self.assertEqual(response.status, 403)
                    headers = {'Authorization': 'Bearer ' + service.token, **{'X-FlightCheck-' + k.title():v for k,v in service.context.items()}}
                    connection.request('GET', server.route + 'api/read', headers=headers); response = connection.getresponse(); response.read(); self.assertEqual(response.status, 200)
                    connection.close()
                finally:
                    server.shutdown(); thread.join()


if __name__ == '__main__': unittest.main()
