"""CODE-80 repairs through public sessions and the real selected recorder."""
import contextlib
import copy
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from checkout_guard_cases import CheckoutCases, PRODUCT
import test_settings as fixtures


class SettingsRepairTests(CheckoutCases, unittest.TestCase):
    config_fixture = fixtures.SettingsTests.config_fixture
    config_module = fixtures.SettingsTests.config_module
    config_git = fixtures.SettingsTests.config_git
    config_cli = fixtures.SettingsTests.config_cli

    @contextlib.contextmanager
    def installed_flight(self, checks=None):
        with self.fixture(), self.config_fixture() as (_, root, engine, installed, cli, supplied):
            from flightcheck_cli.settings import Settings
            self.root = root
            self.git(root, 'remote', 'add', 'origin', 'https://github.com/fixture/repo.git')
            self.git(root, 'switch', '-c', 'codex/settings-repair')
            self.base = self.git(root, 'rev-parse', 'HEAD')
            self.registry = self.associations.Registry(cli.configuration_registry(engine, root))
            owner = Settings(engine, root, 'fixture', 'session-1', self.registry.directory, reference='Owner authorizes synthetic project Settings', project_scope=True)
            changes = {'default_branch': 'trunk'}
            if checks is not None: changes['checks'] = checks(self.area)
            plan = owner.preview({'changes': changes, 'expected_revision': owner.read()['revision']})
            owner.apply({'plan_id': plan['plan_id']})
            self.adopt(root, decision={'adopt_existing': True, 'reference': 'Owner adopts only synthetic installer bytes'})
            yield owner, engine

    def capture(self, command, gate='repair', dependencies=None):
        args = [sys.executable, '-B', str(PRODUCT / 'workflow/scripts/capture_check.py'), '--evidence-dir', str(self.area / 'receipts'), '--create-evidence-dir', '--candidate', 'fixture-source', '--scope', 'CODE-80 actual execution boundary', '--gate', gate, '--owner', 'worker', '--fingerprint-command', json.dumps([sys.executable, '-B', '-c', "print('unchanged complete fixture inputs')"]), '--checkout-binding', json.dumps({'registry': str(self.registry.directory), 'flight': 'fixture'})]
        if dependencies is not None:
            args += ['--configuration-dependencies', json.dumps(dependencies)]
        return args + ['--', *command]

    def save(self, owner, changes):
        plan = owner.preview({'changes': changes, 'expected_revision': owner.read()['revision']})
        return owner.apply({'plan_id': plan['plan_id']})

    def test_obsolete_reconfiguration_cannot_mutate_a_running_capture(self):
        with self.installed_flight() as (owner, engine):
            from flightcheck_cli import settings
            ready, finish = self.area / 'ready', self.area / 'finish'
            command = [sys.executable, '-B', '-c', "from pathlib import Path;import time;Path(__import__('sys').argv[1]).touch();\nwhile not Path(__import__('sys').argv[2]).exists():time.sleep(.02)", str(ready), str(finish)]
            process = subprocess.Popen(self.capture(command, dependencies=[]), cwd=self.root, env=dict(self.env, CODEX_THREAD_ID='session-1'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            with settings.project_server(owner, PRODUCT / 'status-card') as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    deadline = time.monotonic() + 15
                    while not ready.exists() and time.monotonic() < deadline: time.sleep(.02)
                    self.assertTrue(ready.exists())
                    original = self.registry.get('fixture')
                    self.save(owner, {'resources': {'documentation': 'docs'}})
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    headers = {'Authorization': 'Bearer ' + owner.token, 'Content-Type': 'application/json', **{'X-FlightCheck-' + k.title(): v for k, v in owner.context.items()}}
                    for action in ('reconfigure-preview', 'reconfigure-apply'):
                        conn.request('POST', server.route + 'api/' + action, json.dumps({'flight': 'fixture', 'reference': 'Attempt obsolete direct reconfiguration', 'plan_id': 'absent'}), headers)
                        response = conn.getresponse(); response.read()
                        self.assertEqual(response.status, 409, action + ' must be unavailable; only safe-boundary adoption may change execution')
                    self.assertEqual(self.registry.get('fixture')['configuration'], original['configuration'])
                    self.assertEqual(self.registry.get('fixture')['checkout_guard'], original['checkout_guard'])
                    finish.touch(); output = process.communicate(timeout=20)[0]
                    self.assertEqual(process.returncode, 0, output)
                    receipt = json.loads(next((self.area / 'receipts').glob('check-*/run.json')).read_bytes())
                    self.assertEqual(receipt['checkout_context']['configuration_revision'], original['configuration']['revision'])
                    self.assertEqual(receipt['checkout_context_after']['configuration_revision'], original['configuration']['revision'])
                    adopted = self.registry.get('fixture')
                    self.assertEqual(adopted['configuration']['revision'], adopted['checkout_guard']['configuration_revision'])
                    self.save(owner, {'checkout_policy': {'mode': 'worktree-required'}})
                    with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                        with self.guard.settings_execution(self.root, {'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}}, adopt=True): pass
                    self.assertEqual(self.registry.get('fixture')['configuration'], adopted['configuration'], 'An incompatible checkout must defer, never move or split its guard')
                finally:
                    finish.touch()
                    if process.poll() is None: process.communicate(timeout=20)
                    server.shutdown(); thread.join(timeout=5)

    def test_changed_checks_block_old_requests_but_independent_proof_reuses(self):
        def configured(area):
            command = [sys.executable, '-B', '-c', "from pathlib import Path;import time,sys;area=Path(sys.argv[1]);\nwith (area/'started').open('a') as f:f.write('started\\n')\nwhile not (area/'finish').exists():time.sleep(.02)\nwith (area/'old-command-runs').open('a') as f:f.write('run\\n')", str(area)]
            return [{'name': 'original configured check', 'command': command, 'phase': 'cheap'}]
        with self.installed_flight(configured) as (owner, engine):
            marker = self.area / 'old-command-runs'
            command = owner.read()['values']['checks'][0]['command']
            env = dict(self.env, CODEX_THREAD_ID='session-1')
            independent_marker = self.area / 'independent-unit-runs'
            independent_command = [sys.executable, '-B', '-c', "from pathlib import Path;p=Path(__import__('sys').argv[1]);p.write_text(p.read_text()+'run\\n' if p.exists() else 'run\\n')", str(independent_marker)]
            affected = self.capture(command, 'affected', ['checks'])
            independent = self.capture(independent_command, 'independent', [])
            unit = subprocess.run(independent, cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(unit.returncode, 0, unit.stdout + unit.stderr)
            old = self.registry.get('fixture')
            processes = []
            try:
                for gate in ('affected', 'overlap'):
                    processes.append(subprocess.Popen(self.capture(command, gate, ['checks']), cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    started = self.area / 'started'
                    if started.exists() and len(started.read_text().splitlines()) == 2: break
                    time.sleep(.02)
                self.assertTrue(started.exists()); self.assertEqual(len(started.read_text().splitlines()), 2)
                checks = [{'name': 'replacement check', 'command': [sys.executable, '-B', '-c', "raise SystemExit('replacement selected')"], 'phase': 'authoritative'}]
                self.save(owner, {'checks': checks})
                self.assertEqual(self.registry.get('fixture')['configuration'], old['configuration'], 'Save during overlapping captures waits for a safe boundary')
                (self.area / 'finish').touch()
                for process in processes:
                    output = process.communicate(timeout=25)[0]; self.assertEqual(process.returncode, 0, output)
                for pointer in ('affected', 'overlap'):
                    run_id = json.loads((self.area / ('receipts/gate-' + pointer + '.json')).read_bytes())
                    receipt = json.loads((self.area / 'receipts' / run_id / 'run.json').read_bytes())
                    self.assertEqual(receipt['request']['command'], command)
                    self.assertEqual(receipt['checkout_context']['configuration_revision'], old['configuration']['revision'])
                    self.assertEqual(receipt['checkout_context_after']['configuration_revision'], old['configuration']['revision'])
            finally:
                (self.area / 'finish').touch()
                for process in processes:
                    if process.poll() is None: process.communicate(timeout=25)
            run = subprocess.run(affected, cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(run.returncode, 0, 'Old configured command must not be certified under adopted check definitions')
            self.assertIn('reconcil', run.stdout + run.stderr)
            self.assertEqual(marker.read_text().splitlines(), ['run', 'run'])
            reuse = subprocess.run(independent, cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(reuse.returncode, 0, reuse.stdout + reuse.stderr)
            self.assertIn('Check reused:', reuse.stdout)
            self.assertEqual(independent_marker.read_text().splitlines(), ['run'])
            capture = self.module('capture_check'); handoff = self.module('handoff')
            with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                current = capture.guard_context(self.root, {'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}})
            run_id = json.loads((self.area / 'receipts/gate-affected.json').read_bytes())
            receipt = json.loads((self.area / 'receipts' / run_id / 'run.json').read_bytes())
            prior_cwd = Path.cwd()
            try:
                os.chdir(self.root)
                with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                    status = handoff.gate_status(self.area / 'receipts', {'id': 'affected', 'phase': 'cheap', 'owner': 'worker', 'request': receipt['request']}, 'fixture-source', False, current)
                self.assertEqual(status['status'], 'unverified'); self.assertIn('reconcil', status['reason'])
            finally:
                os.chdir(prior_cwd)
            # Actual handoff must not bless a frozen affected request even if a
            # caller supplied a new context after adoption.
            self.assertFalse(capture.same_pass_checkout(receipt['checkout_context'], current, ['checks']))
            self.assertNotEqual(old['configuration']['revision'], current['configuration_revision'])
            # Explicit trusted request reconciliation selects the current model's
            # exact command and classification. A wrong classification is denied
            # again by the normal handoff, without rewriting the frozen gate.
            replacement = [sys.executable, '-B', '-c', 'pass']
            self.save(owner, {'checks': [{'name': 'replacement check', 'command': replacement, 'phase': 'authoritative'}]})
            selected = self.capture(replacement, 'reconciled', ['checks'])
            selected[selected.index('--'):selected.index('--')] = ['--configuration-check', 'replacement check']
            run = subprocess.run(selected, cwd=self.root, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            run_id = json.loads((self.area / 'receipts/gate-reconciled.json').read_bytes())
            selected_receipt = json.loads((self.area / 'receipts' / run_id / 'run.json').read_bytes())
            self.assertEqual(selected_receipt['request']['configuration_check'], {'name': 'replacement check', 'phase': 'authoritative'})
            prior_cwd = Path.cwd()
            try:
                os.chdir(self.root)
                with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                    current = capture.guard_context(self.root, {'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}})
                    gate = {'id': 'reconciled', 'phase': 'cheap', 'owner': 'worker', 'request': selected_receipt['request']}
                    self.assertIn('classification', handoff.gate_status(self.area / 'receipts', gate, 'fixture-source', False, current)['reason'])
                    gate['phase'] = 'authoritative'
                    self.assertEqual(handoff.gate_status(self.area / 'receipts', gate, 'fixture-source', False, current)['status'], 'reusable')
            finally:
                os.chdir(prior_cwd)

    def test_task_transport_rejects_unrelated_project_before_binding_and_reads(self):
        with self.config_fixture() as (area, root, engine, installed, cli, supplied):
            from flightcheck_cli import settings
            private = area / 'card'; private.mkdir(mode=0o700)
            status = private / 'task.json'; status.write_text(json.dumps({'task': 'same-task'}))
            route = private / 'reply-route.json'; route.write_text(json.dumps({'task': 'same-task', 'checkout': str(root)}))
            other = area / 'other'; other.mkdir(); self.config_git(other, 'init', '-q', '-b', 'trunk')
            args = ['--task', 'same-task', '--session', 'owner-session', '--authorize-local-settings', 'Owner project editing', '--project-scope', '--card-status', str(status)]
            with patch.object(settings, 'prepare_route', return_value={'status': 'published', 'user_url': 'http://localhost/task/same-task/'}), patch.object(settings, 'ensure_settings_listener'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'project|repository'):
                    settings.main([str(other), *args], engine)
                self.assertFalse((private / 'settings-session.json').exists(), 'Reject before writing a private capability')
                # A stable base and a linked worker are the same canonical Git
                # project. The route need not use the literal Settings root.
                worker = area / 'linked-worker'; self.config_git(root, 'worktree', 'add', '--detach', str(worker), 'HEAD')
                route.write_text(json.dumps({'task': 'same-task', 'checkout': str(worker)}))
                self.assertEqual(settings.main([str(root), *args], engine), 0)
            binding = json.loads((private / 'settings-session.json').read_bytes())
            request = SimpleNamespace(server=SimpleNamespace(task_file=status, task_route='/task/same-task/'))
            adapter = settings.card_request(request, PRODUCT / 'status-card')
            self.assertEqual(adapter.server.settings.read()['status'], 'configuration')
            self.assertEqual(adapter.server.route, '/task/same-task/settings/')
            self.save(adapter.server.settings, {'resources': {'documentation': 'docs'}})
            route.write_text(json.dumps({'task': 'same-task', 'checkout': str(other)}))
            with self.assertRaisesRegex(ValueError, 'project|repository'):
                settings.card_request(request, PRODUCT / 'status-card')
            route.write_text(json.dumps({'task': 'same-task', 'checkout': str(worker)}))
            binding['root'] = str(other)
            (private / 'settings-session.json').write_text(json.dumps(binding)); (private / 'settings-session.json').chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'project|repository'):
                settings.card_request(request, PRODUCT / 'status-card')

    def test_dependency_paths_are_complete_and_unknown_paths_never_reuse(self):
        with self.fixture():
            self.git(self.root, 'switch', '-c', 'work'); self.adopt(self.root)
            capture = self.module('capture_check'); handoff = self.module('handoff')
            with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                old = capture.guard_context(self.root, {'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}})
            before = self.config.snapshot(self.root)
            values = self.config.propose(self.root, before, {'preview': 'new instructions'}, before['revision'], 'Owner changes preview')
            # The focused contexts model an actual, explicit same-execution
            # adoption. The full stable execution identity remains strict.
            current = copy.deepcopy(old); current['binding_digest'] = 'new-binding'; current['head_binding'] = 'new-head'
            current['configuration_revision'] = self.config.revision(self.config.encoded(values))
            current['settings_adoptions'] = [{'from_revision': old['configuration_revision'], 'to_revision': current['configuration_revision'], 'changed_fields': ['preview'], 'required_revalidation': []}]
            self.assertTrue(capture.same_pass_checkout(old, current, ['cleanup_policy.local_branches']))
            for key in ('cleanup_policy.not_a_setting', 'activation.child', 'status_sync.options.typo', 'resources.not_configured'):
                with self.subTest(dependency=key):
                    self.assertFalse(capture.same_pass_checkout(old, current, [key]))
                    self.assertFalse(handoff.same_pass_checkout(old, current, [key]))
                    self.assertFalse(capture.same_pass_checkout(old, old, [key]), 'Same-context fast path cannot validate an invalid declaration')
                    run = subprocess.run(self.capture([sys.executable, '-B', '-c', 'pass'], 'invalid', [key]), cwd=self.root, env=dict(self.env, CODEX_THREAD_ID='session-1'), capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(run.returncode, 0, 'Actual recorder must reject unknown configuration dependency')
                    prior_cwd = Path.cwd()
                    try:
                        os.chdir(self.root)
                        with patch.dict(os.environ, CODEX_THREAD_ID='session-1'):
                            gate = {'id': 'invalid', 'phase': 'cheap', 'request': {'scope':'Unknown dependency negative', 'configuration_dependencies': [key], 'command': [sys.executable, '-B', '-c', 'pass'], 'artifacts': []}}
                            status = handoff.gate_status(self.area / 'receipts', gate, 'fixture-source', False, old)
                        self.assertEqual(status['status'], 'unverified'); self.assertIn('dependency path', status['reason'])
                    finally:
                        os.chdir(prior_cwd)
