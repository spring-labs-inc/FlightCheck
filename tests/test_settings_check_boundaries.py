"""Normal preflight, named-check independence and bounded private disclosure."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from checkout_guard_cases import CheckoutCases, PRODUCT
import test_settings_repairs as repairs


class SettingsCheckBoundaryTests(CheckoutCases, unittest.TestCase):
    config_fixture = repairs.SettingsRepairTests.config_fixture
    config_module = repairs.SettingsRepairTests.config_module
    config_git = repairs.SettingsRepairTests.config_git
    config_cli = repairs.SettingsRepairTests.config_cli
    installed_flight = repairs.SettingsRepairTests.installed_flight
    save = repairs.SettingsRepairTests.save

    def command(self, name):
        return [sys.executable, '-B', '-c', "from pathlib import Path;p=Path(__import__('sys').argv[1]);\nwith p.open('a') as f:f.write('run\\n')", str(self.area / name)]

    def source_fingerprint(self):
        """Keep the same complete code/runtime probe across a config-only Save.

        Canonical configuration and its ownership/status projections are bound
        separately by the verified common-model revision. Nothing is removed
        from this source probe after a setting changes; new source files count.
        """
        probe = self.area / 'complete-code-fingerprint.py'
        if not probe.exists():
            probe.write_text("import json,sys\nfrom pathlib import Path\n"
                + "sys.path.insert(0," + repr(str(PRODUCT / 'workflow/scripts')) + ")\nimport fingerprint\n"
                + "root=Path(" + repr(str(self.root)) + ")\n"
                + "model_files={'.flightcheck/project.json','.flightcheck/installation.json','.flightcheck/docs/status.md'}\n"
                + "inputs=[str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts and '__pycache__' not in p.parts and str(p.relative_to(root)) not in model_files]\n"
                + "inputs.append(str(Path(__file__).resolve()))\n"
                + "print(json.dumps(fingerprint.gate({'root':str(root),'python':sys.executable,'dependencies':[],'environment':['CODEX_THREAD_ID'],'inputs':sorted(inputs)}),sort_keys=True))\n")
        return [sys.executable, '-B', str(probe)]

    def named(self, command, name, gate=None):
        args = repairs.SettingsRepairTests.capture(self, command, gate or name, [])
        args[args.index('--fingerprint-command') + 1] = json.dumps(self.source_fingerprint())
        pivot = args.index('--'); args[pivot:pivot] = ['--configuration-check', name]
        return args

    def run_capture(self, args):
        return subprocess.run(args, cwd=self.root, env=dict(self.env, CODEX_THREAD_ID='session-1'), capture_output=True, text=True, timeout=35)

    def receipt(self, gate):
        evidence = self.area / 'receipts'
        run = evidence / json.loads((evidence / ('gate-' + gate + '.json')).read_bytes())
        return run / 'run.json', json.loads((run / 'run.json').read_bytes())

    def gate(self, name):
        _, receipt = self.receipt(name)
        return {'id': name, 'phase': receipt['request']['configuration_check']['phase'], 'owner': 'worker', 'request': copy.deepcopy(receipt['request'])}

    def task(self, gates):
        return {'candidate': 'fixture-source', 'saved_candidate': 'fixture-source', 'scope': 'Synthetic configured-check boundary',
                'delivery': 'Synthetic local only; no provider writes', 'preview': None, 'diff': 'candidate.diff',
                'checkout_binding': {'registry': str(self.registry.directory), 'flight': 'fixture'}, 'gates': copy.deepcopy(gates),
                'acceptance': [{'id': 'named', 'kind': 'policy', 'description': 'Exact selected check identity and bounded handoff',
                                'proofs': [{'kind': 'check', 'gate': gates[0]['id'], 'assertion': 'The selected native check is verified'}]}]}

    def handoff(self, mode, task, *, amend=False):
        evidence = self.area / 'receipts'; evidence.mkdir(mode=0o700, exist_ok=True)
        (evidence / 'candidate.diff').write_text('Synthetic selected check only\n')
        path = evidence / 'task.json'; path.write_text(json.dumps(task)); path.chmod(0o600)
        args = [sys.executable, '-B', str(PRODUCT / 'workflow/scripts/handoff.py'), mode, '--task', str(path), '--evidence-dir', str(evidence)]
        if amend:
            contract = evidence / 'acceptance-contract.json'
            decision = {'candidate': task['candidate'], 'authority': 'owner', 'accepted': True,
                        'previous_contract_sha256': hashlib.sha256(contract.read_bytes()).hexdigest(),
                        'source': 'Synthetic owner explicitly reconciles the changed configured gate',
                        'reason': 'Keep the old frozen contract and receipts; reconcile only the new configured command/classification'}
            (evidence / 'owner-gate-amendment.json').write_text(json.dumps(decision))
            args += ['--amend-contract', 'owner-gate-amendment.json']
        result = subprocess.run(args, cwd=self.root, env=dict(self.env, CODEX_THREAD_ID='session-1'), capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_normal_preflight_remains_independent_after_check_adoption(self):
        with self.installed_flight(lambda area: [{'name': 'alpha', 'command': self.command('old-alpha'), 'phase': 'cheap'}]) as (owner, _):
            old_command = owner.read()['values']['checks'][0]['command']
            old_args = self.named(old_command, 'alpha')
            old = self.run_capture(old_args); self.assertEqual(old.returncode, 0, old.stdout + old.stderr)
            old_path, old_receipt = self.receipt('alpha'); old_bytes = old_path.read_bytes()
            task = self.task([self.gate('alpha')]); self.handoff('preflight', task)
            new_command = self.command('new-alpha')
            self.save(owner, {'checks': [{'name': 'alpha', 'command': new_command, 'phase': 'authoritative'}]})
            current = self.run_capture(self.named(new_command, 'alpha')); self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
            task['gates'] = [self.gate('alpha')]
            normal = self.handoff('preflight', task, amend=True)
            self.assertTrue(normal['ready']); self.assertEqual(normal['probe']['status'], 'passed')
            probe = json.loads(Path(normal['probe']['receipt']).read_bytes())
            self.assertEqual(probe['request']['configuration_dependencies'], [])
            stale = self.run_capture(old_args); self.assertNotEqual(stale.returncode, 0)
            self.assertIn('changed', stale.stdout + stale.stderr)
            self.assertEqual(old_path.read_bytes(), old_bytes)
            self.assertEqual(self.receipt('alpha')[1]['inputs_before'], old_receipt['inputs_before'])

    def test_unchanged_named_check_reuses_while_changed_check_requires_fresh_pass(self):
        with self.installed_flight(lambda area: [{'name': name, 'command': self.command(name + '-old'), 'phase': 'cheap'} for name in ('alpha', 'beta')]) as (owner, _):
            definitions = owner.read()['values']['checks']
            args = {row['name']: self.named(row['command'], row['name']) for row in definitions}
            for invocation in args.values():
                result = self.run_capture(invocation); self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            alpha_path, alpha = self.receipt('alpha'); alpha_bytes = alpha_path.read_bytes()
            beta_path, beta = self.receipt('beta'); beta_bytes = beta_path.read_bytes()
            task = self.task([self.gate('alpha'), self.gate('beta')]); self.handoff('preflight', task)
            replacement = self.command('beta-new')
            self.save(owner, {'checks': [definitions[0], {'name': 'beta', 'command': replacement, 'phase': 'authoritative'}]})
            unchanged = self.run_capture(args['alpha'])
            self.assertEqual(unchanged.returncode, 0, unchanged.stdout + unchanged.stderr)
            self.assertIn('Check reused:', unchanged.stdout)
            self.assertEqual(self.receipt('alpha')[0], alpha_path); self.assertEqual(alpha_path.read_bytes(), alpha_bytes)
            self.assertEqual((self.area / 'alpha-old').read_text().splitlines(), ['run'])
            stale = self.run_capture(args['beta']); self.assertNotEqual(stale.returncode, 0)
            self.assertIn('changed', stale.stdout + stale.stderr); self.assertEqual(beta_path.read_bytes(), beta_bytes)
            observed = {row['id']: row for row in self.handoff('checks', task)['checks']}
            self.assertEqual(observed['alpha']['status'], 'passed'); self.assertEqual(Path(observed['alpha']['receipt']), alpha_path)
            self.assertEqual(observed['beta']['status'], 'unverified')
            self.assertEqual(observed['alpha']['effective_inputs'], alpha['inputs_before'])
            fresh = self.run_capture(self.named(replacement, 'beta'))
            self.assertEqual(fresh.returncode, 0, fresh.stdout + fresh.stderr); self.assertNotIn('Check reused:', fresh.stdout)
            new_path, current = self.receipt('beta'); self.assertNotEqual(new_path, beta_path)
            self.assertEqual(current['inputs_before'], beta['inputs_before']); self.assertEqual(current['inputs_before'], current['inputs_after'])
            self.assertEqual((self.area / 'beta-old').read_text().splitlines(), ['run'])
            self.assertEqual((self.area / 'beta-new').read_text().splitlines(), ['run'])
            task['gates'] = [self.gate('alpha'), self.gate('beta')]
            self.handoff('preflight', task, amend=True)
            final = {row['id']: row for row in self.handoff('checks', task)['checks']}
            self.assertEqual(final['alpha']['status'], 'passed'); self.assertEqual(Path(final['alpha']['receipt']), alpha_path)
            self.assertEqual(final['beta']['status'], 'passed'); self.assertEqual(Path(final['beta']['receipt']), new_path)
            self.assertEqual(alpha_path.read_bytes(), alpha_bytes); self.assertEqual(beta_path.read_bytes(), beta_bytes)

    def test_unselected_private_argv_stays_out_of_context_receipt_and_packet(self):
        marker = 'UNSELECTED_HOST_PRIVATE_ARGV_09'
        with self.installed_flight(lambda area: [{'name': 'alpha', 'command': self.command('selected'), 'phase': 'cheap'},
                {'name': 'private-other', 'command': [sys.executable, '-B', '-c', 'pass', marker], 'phase': 'cheap'}]) as (owner, _):
            command = owner.read()['values']['checks'][0]['command']
            result = self.run_capture(self.named(command, 'alpha')); self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            path, receipt = self.receipt('alpha')
            self.assertNotIn(marker, json.dumps(receipt['checkout_context']))
            self.assertNotIn(marker, json.dumps(receipt['checkout_context_after']))
            self.assertNotIn(marker, path.read_text())
            task = self.task([self.gate('alpha')]); self.handoff('preflight', task)
            packet = self.handoff('resume', task)
            self.assertNotIn(marker, json.dumps(packet))
            self.assertNotIn(marker, (self.area / 'receipts/task.json').read_text())
            before = path.read_bytes()
            wrong = self.run_capture(self.named([sys.executable, '-B', '-c', 'pass'], 'alpha'))
            self.assertNotEqual(wrong.returncode, 0); self.assertIn('changed', wrong.stdout + wrong.stderr)
            self.assertEqual(path.read_bytes(), before)

    def test_resource_sibling_reuses_exact_receipt_while_changed_and_wide_revalidate(self):
        names = ('style', 'documentation', 'resources')
        with self.installed_flight(lambda area: [{'name': name, 'command': self.command('resource-' + name), 'phase': 'cheap'} for name in names]) as (owner, _):
            self.save(owner, {'resources': {'style_guide': 'docs/style.md', 'documentation': 'docs/original'}})
            paths = {'style': 'resources.style_guide', 'documentation': 'resources.documentation', 'resources': 'resources'}
            definitions = owner.read()['values']['checks']
            args = {}
            for definition in definitions:
                name = definition['name']; invocation = self.named(definition['command'], name)
                invocation[invocation.index('--configuration-dependencies') + 1] = json.dumps([paths[name]])
                args[name] = invocation
                result = self.run_capture(invocation); self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            originals = {name: self.receipt(name) for name in names}
            bytes_before = {name: path.read_bytes() for name, (path, _) in originals.items()}
            task = self.task([self.gate(name) for name in names]); self.handoff('preflight', task)
            self.save(owner, {'resources': {'documentation': 'docs/revised'}})
            style = self.run_capture(args['style'])
            self.assertEqual(style.returncode, 0, style.stdout + style.stderr)
            self.assertIn('Check reused:', style.stdout, 'Unchanged style-guide setting must preserve its exact receipt')
            self.assertEqual(self.receipt('style')[0], originals['style'][0])
            self.assertEqual((self.area / 'resource-style').read_text().splitlines(), ['run'])
            observed = {row['id']: row for row in self.handoff('checks', task)['checks']}
            self.assertEqual(observed['style']['status'], 'passed')
            self.assertEqual(Path(observed['style']['receipt']), originals['style'][0])
            for name in ('documentation', 'resources'):
                self.assertIn(observed[name]['status'], ('stale', 'unverified'))
                current = self.run_capture(args[name]); self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
                self.assertNotIn('Check reused:', current.stdout)
                path, receipt = self.receipt(name); self.assertNotEqual(path, originals[name][0])
                self.assertEqual(receipt['inputs_before'], originals[name][1]['inputs_before'])
                self.assertEqual(receipt['inputs_before'], receipt['inputs_after'])
                self.assertEqual((self.area / ('resource-' + name)).read_text().splitlines(), ['run', 'run'])
            for name, (path, _) in originals.items(): self.assertEqual(path.read_bytes(), bytes_before[name])
            unknown = copy.deepcopy(args['style'])
            unknown[unknown.index('--configuration-dependencies') + 1] = json.dumps(['resources.style_guide.unknown'])
            denied = self.run_capture(unknown); self.assertNotEqual(denied.returncode, 0)
            self.assertIn('Unknown configuration dependency', denied.stdout + denied.stderr)
            invalid_task = self.task([copy.deepcopy(self.gate('style'))])
            invalid_task['gates'][0]['request']['configuration_dependencies'] = ['resources.style_guide.unknown']
            invalid = self.handoff('checks', invalid_task)['checks'][0]
            self.assertEqual(invalid['status'], 'unverified')
            self.assertEqual(self.receipt('style')[0], originals['style'][0]); self.assertEqual(originals['style'][0].read_bytes(), bytes_before['style'])
