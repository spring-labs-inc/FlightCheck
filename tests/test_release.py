"""Black-box release candidates, policy failures and loopback registry controls."""
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
from unittest import mock
import zipfile

import yaml

ROOT = Path(os.environ.get('FLIGHTCHECK_PRODUCT_ROOT', Path(__file__).resolve().parents[1])).resolve()
BASE = str(Path(sys._base_executable).resolve())


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.area = tempfile.TemporaryDirectory(prefix='flightcheck-release-tests-')
        cls.addClassCleanup(cls.area.cleanup)
        cls.scratch = Path(cls.area.name).resolve()
        cls.source = cls.scratch / 'source'
        cls.source.mkdir()
        cls.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PIP_NO_INDEX='1',
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
        cls.env.pop('FLIGHTCHECK_BUILD_DEVELOPMENT', None)
        cls.env.pop('PYTHONPATH', None)
        names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
        for name in set(names) - {''}:
            path = ROOT / name
            if path.is_file():
                dest = cls.source / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
                dest.chmod(stat.S_IMODE(path.stat().st_mode))
        cls.version = tomllib.loads((cls.source / 'pyproject.toml').read_text())['project']['version']
        cls.tag = 'v' + cls.version
        for args in (['init', '-q', '--template='], ['config', 'core.hooksPath', os.devnull], ['add', '--force', '.'],
                     ['-c', 'user.name=Release test fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Synthetic release source fixture'],
                     ['tag', cls.tag]):
            subprocess.run(['git', '-C', str(cls.source), *args], env=cls.env, check=True, capture_output=True)
        cls.script = cls.source / 'tools/release.py'
        cls.artifacts = cls.scratch / 'release'
        cls.command('prepare', '--output', cls.artifacts, '--tag', cls.tag)
        cls.record = json.loads((cls.artifacts / 'release.json').read_text())

    @classmethod
    def command(cls, *args, expected=0, script=None, env=None):
        result = subprocess.run([sys.executable, '-B', str(script or cls.script), *map(str, args)],
                                cwd=cls.scratch, env=env or cls.env, capture_output=True, text=True)
        if result.returncode != expected:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(result.stdout)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=self.scratch)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def artifacts_copy(self):
        target = self.root / 'artifacts'
        shutil.copytree(self.artifacts, target)
        return target

    def test_review_and_clean_release_provenance(self):
        self.assertTrue(self.record['release_eligible'])
        self.assertFalse(self.record['source']['development'])
        self.assertEqual(self.record['source']['source_revision'], subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD'], text=True).strip())
        # Review mode is ineligible even on a clean source and cannot mint a release.
        review = self.root / 'review'
        self.command('prepare', '--output', review, '--review')
        self.assertFalse(self.command('verify', '--artifacts', review)['release_eligible'])
        self.command('verify', '--artifacts', review, '--require-release', expected=1)
        self.command('prepare', '--output', self.root / 'wrong-tag', '--tag', 'v9.9.9', expected=1)
        marker = self.source / 'uncommitted.txt'
        marker.write_text('Owner work must not impersonate a release\n')
        self.addCleanup(marker.unlink)
        self.command('prepare', '--output', self.root / 'dirty', '--tag', self.tag, expected=1)
        reviewed = self.command('prepare', '--output', self.root / 'dirty-review', '--review')
        self.assertFalse(reviewed['release_eligible'])
        self.assertTrue(reviewed['record']['source']['development'])
        self.assertNotEqual(reviewed['record']['source']['source_revision'], self.record['source']['source_revision'])

    def test_verify_rejects_tampering_and_incomplete_inventory(self):
        folder = self.artifacts_copy()
        self.command('verify', '--artifacts', folder, '--require-release')
        wheel = next((folder / 'dist').glob('*.whl'))
        original = wheel.read_bytes()
        wheel.write_bytes(original + b'changed')
        self.command('verify', '--artifacts', folder, expected=1)
        wheel.write_bytes(original)
        # A repaired outer digest cannot conceal altered executable/embedded assets.
        with zipfile.ZipFile(wheel) as archive:
            entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
        with zipfile.ZipFile(wheel, 'w') as archive:
            for item, data in entries:
                if item.filename == 'flightcheck_cli/cli.py':data += b'\n# unreviewed executable\n'
                archive.writestr(item, data)
        record = json.loads((folder / 'release.json').read_text())
        record['files'][wheel.name] = {'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(), 'size': wheel.stat().st_size}
        (folder / 'release.json').write_text(json.dumps(record))
        error = self.command('verify', '--artifacts', folder, expected=1)
        self.assertIn('CLI bytes', error['error'])
        wheel.write_bytes(original)
        (folder / 'release.json').write_bytes((self.artifacts / 'release.json').read_bytes())
        (folder / 'dist/extra.whl').write_bytes(b'not approved')
        self.command('verify', '--artifacts', folder, expected=1)
        (folder / 'dist/extra.whl').unlink()
        real = self.root / 'outside.whl'
        wheel.rename(real)
        wheel.symlink_to(real)
        self.command('verify', '--artifacts', folder, expected=1)
        self.assertEqual(real.read_bytes(), original)

    def policy(self):
        source = self.record['source']['source_revision']
        return {'mode': 'publish', 'current_sha': source,
                'run': {'id': 123, 'head_sha': source, 'event': 'workflow_dispatch', 'conclusion': 'success',
                        'path': '.github/workflows/release.yml', 'workflow_id': 9,
                        'repository': {'full_name': 'spring-labs-inc/FlightCheck'}},
                'workflow': {'id': 9, 'path': '.github/workflows/release.yml', 'state': 'active'},
                'artifact': {'id': 456, 'name': 'flightcheck-release', 'expired': False,
                             'workflow_run': {'id': 123, 'head_sha': source}},
                'environment': {'name': 'pypi', 'protection_rules': [{'type': 'required_reviewers', 'reviewers': [{'id': 7}]}]}}

    def gate(self, context, expected=0, enabled=True, folder=None):
        path = self.root / 'context.json'
        path.write_text(json.dumps(context))
        env = {**self.env, 'FLIGHTCHECK_PYPI_PUBLISH_ENABLED': 'true' if enabled else ''}
        return self.command('gate', '--artifacts', folder or self.artifacts, '--context', path,
                            '--manifest-sha256', hashlib.sha256((self.artifacts / 'release.json').read_bytes()).hexdigest(),
                            '--source-sha', self.record['source']['source_revision'], '--reviewed-run-id', '123',
                            '--reviewed-artifact-id', '456', expected=expected, env=env)

    def test_publishing_policy_binds_reviewed_run_and_exact_artifacts(self):
        context = self.policy()
        self.assertEqual(self.gate(context)['artifact_id'], '456')
        self.gate(context, expected=1, enabled=False)
        variants = [('mode', 'prepare'), ('current_sha', '0' * 40), ('run.id', 999),
                    ('run.path', '.github/workflows/other.yml'), ('run.head_sha', '0' * 40),
                    ('run.event', 'push'), ('run.conclusion', 'failure'), ('run.workflow_id', 8),
                    ('artifact.id', 457), ('artifact.expired', True), ('artifact.workflow_run.id', 999),
                    ('environment.protection_rules', [])]
        for key, value in variants:
            with self.subTest(key=key):
                changed = copy.deepcopy(context)
                current = changed
                path = key.split('.')
                for part in path[:-1]:current = current[part]
                current[path[-1]] = value
                error = self.gate(changed, expected=1)
                if key == 'run.id':self.assertIn('run identity', error['error'])
        folder = self.artifacts_copy()
        record = json.loads((folder / 'release.json').read_text())
        record['license_sha256'] = '0' * 64
        (folder / 'release.json').write_text(json.dumps(record))
        self.gate(context, folder=folder, expected=1)

    @contextmanager
    def registry(self):
        record = self.record
        state = {'mode': 'valid', 'requests': []}
        payloads = {name: (self.artifacts / 'dist' / name).read_bytes() for name in record['files']}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                state['requests'].append(('GET', self.path))
                hook = state.get('on_get')
                if hook:
                    hook(self.path)
                if state.get('redirect'):
                    self.send_response(302)
                    self.send_header('Location', state['redirect'])
                    self.end_headers()
                    return
                if state['mode'] == 'missing':self.send_error(404);return
                if self.path.endswith('/json'):
                    entries = [{'filename': n, 'digests': {'sha256': r['sha256']}, 'size': r['size'], 'yanked': False,
                                'url': 'http://127.0.0.1:' + str(self.server.server_port) + '/' + n} for n, r in record['files'].items()]
                    if state['mode'] == 'metadata':entries[0]['digests']['sha256'] = '0' * 64
                    if state['mode'] == 'yanked':entries[0]['yanked'] = True
                    data = json.dumps({'info': {'name': record['distribution'], 'version': record['version']}, 'urls': entries}).encode()
                else:
                    filename = self.path.lstrip('/')
                    data = state.get('overrides', {}).get(filename, payloads[filename])
                    if state['mode'] == 'bytes':data = bytes([data[0] ^ 1]) + data[1:]
                self.send_response(200);self.end_headers();self.wfile.write(data)
            def log_message(self, *args):pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:yield 'http://127.0.0.1:' + str(server.server_port), state
        finally:server.shutdown();server.server_close();worker.join()

    def test_registry_verification_and_draft_documentation(self):
        with self.registry() as (url, state):
            result = self.command('verify-index', '--artifacts', self.artifacts, '--test-index', url)
            self.assertEqual(result['status'], 'simulated_registry_match')
            self.assertTrue(result['simulated'])
            self.assertIn('pending', result['public_installation'])
            for mode in ('missing', 'metadata', 'yanked', 'bytes'):
                state['mode'] = mode
                error = self.command('verify-index', '--artifacts', self.artifacts, '--test-index', url, expected=1)
                if mode == 'bytes':self.assertIn('downloaded bytes', error['error'])
            self.assertTrue(all(method == 'GET' for method, _ in state['requests']))
        self.command('verify-index', '--artifacts', self.artifacts, '--test-index', 'https://untrusted.invalid', expected=1)
        before = (self.source / 'README.md').read_bytes()
        artifact_bytes = {str(path.relative_to(self.artifacts)): path.read_bytes()
                          for path in self.artifacts.rglob('*') if path.is_file()}
        refusal = self.command('docs', '--artifacts', self.artifacts, expected=1)
        self.assertIn('README quickstart changed; reconcile the proposal explicitly', refusal['error'])
        self.assertNotIn('readme', refusal)
        self.assertNotEqual(refusal.get('status'), 'proposal_only')
        self.assertEqual((self.source / 'README.md').read_bytes(), before)

        # Exercise the proposal's unpromoted input without changing the shared source.
        docs_source = self.root / 'docs-source'
        (docs_source / 'tools').mkdir(parents=True)
        docs_script = docs_source / 'tools/release.py'
        shutil.copyfile(self.script, docs_script)
        shutil.copyfile(self.source / 'pyproject.toml', docs_source / 'pyproject.toml')
        public_pin = ('pipx install flightcheck==' + self.version).encode()
        self.assertEqual(before.count(public_pin), 1)
        unpromoted = before.replace(public_pin, b'pipx install "git+https://github.com/spring-labs-inc/FlightCheck.git"')
        self.assertEqual(unpromoted.count(b'Install with [pipx]'), 1)
        unpromoted = unpromoted.replace(b'Install with [pipx]', b'Install from Git with [pipx]')
        published_note = b'For source installation and retained versions, use the setup guide.'
        self.assertEqual(unpromoted.count(published_note), 1)
        unpromoted = unpromoted.replace(published_note, b'PyPI installation will replace this Git channel after a release is published and verified.')
        self.assertNotEqual(unpromoted, before)
        docs_readme = docs_source / 'README.md'
        docs_readme.write_bytes(unpromoted)
        proposal = self.command('docs', '--artifacts', self.artifacts, script=docs_script)
        self.assertEqual(proposal['status'], 'proposal_only')
        self.assertEqual(proposal['before_sha256'], hashlib.sha256(unpromoted).hexdigest())
        self.assertEqual(proposal['readme'], before.decode())
        self.assertIn('flightcheck==' + self.version, proposal['readme'])
        for marker in ('## Get started', '## License and commercial use'):
            if marker == '## Get started':self.assertEqual(proposal['readme'].split(marker)[0], unpromoted.decode().split(marker)[0])
            else:self.assertEqual(proposal['readme'].split(marker)[1], unpromoted.decode().split(marker)[1])
        self.assertEqual(docs_readme.read_bytes(), unpromoted)
        self.assertEqual((self.source / 'README.md').read_bytes(), before)
        self.assertEqual(docs_script.read_bytes(), self.script.read_bytes())
        self.assertEqual({str(path.relative_to(self.artifacts)): path.read_bytes()
                          for path in self.artifacts.rglob('*') if path.is_file()}, artifact_bytes)

    def test_registry_qualification_scope(self):
        with self.registry() as (url, _):
            result = self.command('verify-index', '--artifacts', self.artifacts, '--test-index', url)
        qualification = result['native_qualification']
        self.assertIn('bounded native/manual scope', qualification)
        self.assertIn('#14 closed', qualification)
        self.assertIn('docs/claude-trial-report.md', qualification)
        self.assertIn('exact release-wheel local/SSH/browser checks pending', qualification)
        self.assertIn('no automatic interception', qualification)
        self.assertEqual(result['status'], 'simulated_registry_match')
        self.assertTrue(result['simulated'])
        self.assertIn('pending', result['public_installation'])

    def release_module(self):
        spec = importlib.util.spec_from_file_location('release_fixture', self.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_release_output_canonical_parent_boundary(self):
        prefix = self.scratch / 'parent-route'
        prefix.mkdir(exist_ok=True)
        protected = self.source / 'forbidden-release-output'
        self.addCleanup(shutil.rmtree, protected, ignore_errors=True)
        alias = prefix / '..' / self.source.name / protected.name
        module = self.release_module()
        created = []
        original_mkdir = Path.mkdir
        def observe_mkdir(path, *args, **kwargs):
            if path.resolve() == protected.resolve():
                created.append(str(path))
            return original_mkdir(path, *args, **kwargs)
        with mock.patch.object(Path, 'mkdir', autospec=True, side_effect=observe_mkdir):
            with self.assertRaises(ValueError):
                module.prepare(alias, tag=self.tag)
        self.assertEqual(created, [])
        error = self.command('prepare', '--tag', self.tag, '--output', alias, expected=1)
        self.assertIn('outside the checkout', error['error'])
        self.assertFalse(protected.exists())
        outside = self.root / 'external-review'
        self.assertFalse(self.command('prepare', '--review', '--output', outside)['release_eligible'])

    def test_registry_redirects_stop_before_destination_request(self):
        with self.registry() as (destination, destination_state):
            with self.registry() as (origin, origin_state):
                origin_state['redirect'] = destination + '/pypi/flightcheck/' + self.version + '/json'
                self.command('verify-index', '--artifacts', self.artifacts, '--test-index', origin, expected=1)
        self.assertEqual(len(origin_state['requests']), 1)
        self.assertEqual(destination_state['requests'], [])

    def test_registry_public_origin_is_checked_before_download(self):
        module = self.release_module()
        metadata_url = 'https://pypi.org/pypi/flightcheck/' + self.version + '/json'
        payloads = {n: (self.artifacts / 'dist' / n).read_bytes() for n in self.record['files']}
        for template, accepted in (
            ('https://files.pythonhosted.org/{filename}', True),
            ('https://files.pythonhosted.org:443/{filename}', True),
            ('https://files.pythonhosted.org:8443/{filename}', False),
            ('https://files.pythonhosted.org@untrusted.invalid/{filename}', False),
            ('http://files.pythonhosted.org/{filename}', False),
            ('https://user@files.pythonhosted.org/{filename}', False),
            ('https://@files.pythonhosted.org/{filename}', False),
            ('https://:@files.pythonhosted.org/{filename}', False),
            ('https://files.pythonhosted.org/{filename}#fragment', False),
            ('https://files.pythonhosted.org/{filename}#', False),
        ):
            with self.subTest(url=template):
                entries = [{'filename': n, 'digests': {'sha256': r['sha256']}, 'size': r['size'],
                            'yanked': False, 'url': template.format(filename=n)} for n, r in self.record['files'].items()]
                requested = []
                def download(url, expected_size=None):
                    requested.append(url)
                    if url == metadata_url:
                        return json.dumps({'info': {'name': 'flightcheck', 'version': self.version}, 'urls': entries}).encode()
                    return payloads[module.urlsplit(url).path.rsplit('/', 1)[-1]]
                with mock.patch.object(module, 'read_url', side_effect=download):
                    if accepted:
                        result = module.verify_index(self.artifacts)
                        self.assertEqual(result['status'], 'verified_public_artifact_bytes')
                        self.assertIn('pending', result['public_installation'])
                    else:
                        with self.assertRaisesRegex(ValueError, 'origin'):
                            module.verify_index(self.artifacts)
                        self.assertEqual(requested, [metadata_url])

    def test_registry_test_index_rejects_component_presence(self):
        module = self.release_module()
        with self.registry() as (url, _):
            result = module.verify_index(self.artifacts, url)
            self.assertEqual(result['status'], 'simulated_registry_match')
            for base in (url.replace('http://', 'http://@'),
                         url.replace('http://', 'http://:@'), url + '#', url + '#fragment'):
                with self.subTest(base=base):
                    requested = []
                    def forbidden_read(target, expected_size=None):
                        requested.append(target)
                        raise AssertionError('Reader reached before test-index validation')
                    with mock.patch.object(module, 'read_url', side_effect=forbidden_read):
                        with self.assertRaisesRegex(ValueError, 'Test registries'):
                            module.verify_index(self.artifacts, base)
                    self.assertEqual(requested, [])

    def test_registry_snapshot_binding(self):
        folder = self.artifacts_copy()
        manifest = folder / 'release.json'
        original = manifest.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        with self.registry() as (url, state):
            result = self.command('verify-index', '--artifacts', folder, '--test-index', url,
                                  '--manifest-sha256', digest)
            self.assertEqual(result['manifest_sha256'], digest)
            state['requests'].clear()
            with self.subTest(boundary='before request'):
                error = self.command('verify-index', '--artifacts', folder, '--test-index', url,
                                     '--manifest-sha256', '0' * 64, expected=1)
                self.assertIn('manifest', error['error'].lower())
                self.assertEqual(state['requests'], [])
            def replace_manifest(path):
                if path.endswith('/json'):
                    manifest.write_bytes(original + b'\n')
            state['on_get'] = replace_manifest
            with self.subTest(boundary='during readback'):
                error = self.command('verify-index', '--artifacts', folder, '--test-index', url,
                                     '--manifest-sha256', digest, expected=1)
                self.assertIn('manifest', error['error'].lower())

    def test_registry_rejects_valid_same_name_wheel_substitution(self):
        filename = next(n for n in self.record['files'] if n.endswith('.whl'))
        original = (self.artifacts / 'dist' / filename).read_bytes()
        replacement = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            with zipfile.ZipFile(replacement, 'w') as altered:
                altered.comment = archive.comment
                for index, item in enumerate(archive.infolist()):
                    changed = copy.copy(item)
                    if index == 0:
                        changed.date_time = (1981, 1, 1, 0, 0, 0)
                    altered.writestr(changed, archive.read(item.filename))
        substitute = replacement.getvalue()
        self.assertNotEqual(substitute, original)
        self.assertEqual(len(substitute), len(original))
        variant = self.root / filename
        variant.write_bytes(substitute)
        module = self.release_module()
        self.assertEqual(module.wheel_payload(variant, 'flightcheck', self.version),
                         module.wheel_payload(self.artifacts / 'dist' / filename, 'flightcheck', self.version))
        with self.registry() as (url, state):
            result = self.command('verify-index', '--artifacts', self.artifacts, '--test-index', url)
            self.assertEqual(result['status'], 'simulated_registry_match')
            self.assertIn('pending', result['public_installation'])
            state['overrides'] = {filename: substitute}
            error = self.command('verify-index', '--artifacts', self.artifacts, '--test-index', url, expected=1)
            self.assertIn('downloaded bytes disagree', error['error'])
            self.assertEqual(error['status'], 'incomplete')

    def test_review_wheel_installs_but_cannot_publish(self):
        folder = self.root / 'review'
        result = self.command('prepare', '--review', '--output', folder)
        self.assertFalse(result['release_eligible'])
        record = result['record']
        wheel = next((folder / 'dist').glob('*.whl'))
        self.assertEqual(hashlib.sha256(wheel.read_bytes()).hexdigest(), record['files'][wheel.name]['sha256'])
        tool = self.root / 'review-tool'
        self.install(wheel, tool)
        smoke = subprocess.run([str(tool / 'bin/flightcheck'), '--version'], env=self.env,
                               capture_output=True, text=True)
        self.assertEqual(smoke.returncode, 0, smoke.stdout + smoke.stderr)
        self.assertIn('flightcheck ' + self.version, smoke.stdout)
        identity = subprocess.run([str(tool / 'bin/python'), '-B', '-c',
                                   "from importlib.metadata import version;assert version('flightcheck')==" + repr(self.version)],
                                  env=self.env, capture_output=True, text=True)
        self.assertEqual(identity.returncode, 0, identity.stdout + identity.stderr)
        context = self.root / 'no-actions-context.json'
        context.write_text(json.dumps({'mode': 'publish'}))
        error = self.command('gate', '--artifacts', folder, '--context', context,
                             '--manifest-sha256', hashlib.sha256((folder / 'release.json').read_bytes()).hexdigest(),
                             '--source-sha', record['source']['source_revision'], '--reviewed-run-id', '0',
                             '--reviewed-artifact-id', '0', expected=1,
                             env={**self.env, 'FLIGHTCHECK_PYPI_PUBLISH_ENABLED': ''})
        self.assertIn('cannot authorize publication', error['error'])
        self.assertEqual(hashlib.sha256(wheel.read_bytes()).hexdigest(), record['files'][wheel.name]['sha256'])

    def install(self, artifact, target):
        subprocess.run([BASE, '-B', '-m', 'venv', str(target)], env=self.env, check=True, capture_output=True)
        env = dict(self.env)
        if artifact.is_dir() or artifact.name.endswith('.tar.gz'):
            # Explicit offline PEP 517 no-isolation test: use the pinned maintainer
            # build libraries, then remove this override for every runtime command.
            import setuptools
            env['PYTHONPATH'] = str(Path(setuptools.__file__).resolve().parents[1])
        result = subprocess.run([str(target / 'bin/python'), '-B', '-m', 'pip', 'install', '--no-index', '--no-deps',
                                 '--no-build-isolation', str(artifact)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_installed_candidate_preserves_project_and_survives_tool_removal(self):
        for artifact in [self.source, *sorted((self.artifacts / 'dist').iterdir())]:
            with self.subTest(artifact=artifact.name):
                kind = 'source' if artifact.is_dir() else 'sdist' if artifact.name.endswith('.tar.gz') else 'wheel'
                area = self.root / kind
                area.mkdir(mode=0o700)
                tool = area / 'tool'
                self.install(artifact, tool)
                env = {**self.env, 'FLIGHTCHECK_INSTALLER_STATE_DIR': str(area / 'private-state')}
                project = area / 'project';project.mkdir()
                subprocess.run(['git', '-C', str(project), 'init', '-q', '-b', 'main'], env=env, check=True)
                owner = {'AGENTS.md': b'Owner instructions\n', 'CLAUDE.md': b'Independent Claude policy\n',
                         'requirements.txt': b'# Existing app dependencies\n', '.claude/settings.json': b'{"hooks":{}}\n'}
                for name, data in owner.items():
                    path = project / name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data)
                (project / 'CLAUDE.md').chmod(0o600)
                values = {'python': BASE, 'activation': 'opt-in', 'delivery': 'No provider writes', 'default_branch': 'main',
                          'evidence_dir': str(area / 'evidence'), 'nit_tracker': 'Private notes', 'policy_reference': 'Synthetic owner policy',
                          'checks': [{'name': 'Must not run in setup', 'command': [BASE, '-c', 'raise SystemExit(93)'], 'phase': 'cheap'}]}
                config = area / 'choices.json';config.write_text(json.dumps(values));plan = area / 'plan.json'
                result = subprocess.run([str(tool / 'bin/python'), '-B', '-c', "import flightcheck_cli;from importlib.metadata import version;assert version('flightcheck')==" + repr(self.version)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for args in (['--version'], ['init', str(project), '--agent', 'both', '--config', str(config), '--plan', str(plan)],
                             ['init', str(project), '--apply', str(plan)], ['doctor', str(project)]):
                    result = subprocess.run([str(tool / 'bin/flightcheck'), *args], env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for name, data in owner.items():
                    actual = (project / name).read_bytes()
                    self.assertTrue(actual.startswith(data) if name.endswith('.md') else actual == data, name)
                self.assertEqual(stat.S_IMODE((project / 'CLAUDE.md').stat().st_mode), 0o600)
                self.assertTrue((project / '.claude/skills/develop-change/SKILL.md').is_file())
                self.assertTrue((project / '.agents/skills/develop-change/SKILL.md').is_file())
                shutil.rmtree(tool)
                result = subprocess.run([BASE, '-B', str(project / '.flightcheck/install.py'), 'verify', '--target', str(project)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'ready_for_client_probe')

    def test_workflow_and_readme_publication_hold(self):
        workflow = yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        self.assertEqual(workflow['on']['workflow_dispatch']['inputs']['mode']['default'], 'prepare')
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        jobs = workflow['jobs']
        self.assertEqual(jobs['prepare']['if'], "${{ inputs.mode == 'prepare' }}")
        for name, job in jobs.items():
            if name != 'publish':self.assertNotIn('id-token', job.get('permissions', {}))
            for step in job['steps']:
                if 'uses' in step:self.assertRegex(step['uses'], r'^[\w/-]+@[a-f0-9]{40}$')
        publish = jobs['publish']
        self.assertIn("inputs.mode == 'publish'", publish['if'])
        self.assertIn("vars.FLIGHTCHECK_PYPI_PUBLISH_ENABLED == 'true'", publish['if'])
        self.assertIn("needs.verify-publication.result == 'success'", publish['if'])
        self.assertEqual(publish['environment']['name'], 'pypi')
        output_step = jobs['verify-publication']['steps'][-1]['run']
        output_code = output_step.split("python - <<'OUTPUT'\n", 1)[1].split('\nOUTPUT', 1)[0]
        (self.root / 'policy.json').write_text(json.dumps({'artifact_id': '456'}))
        output_path = self.root / 'github-output'
        result = subprocess.run([sys.executable, '-B', '-c', output_code],
                                env={**self.env, 'RUNNER_TEMP': str(self.root), 'GITHUB_OUTPUT': str(output_path)},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output_path.read_text(), 'artifact_id=456\n')
        self.assertEqual(publish['permissions']['id-token'], 'write')
        self.assertFalse(any('checkout' in step.get('uses', '') for step in publish['steps']))
        self.assertFalse(any('build ' in step.get('run', '') or 'release.py' in step.get('run', '') for step in publish['steps']))
        download = publish['steps'][0]
        self.assertEqual(download['with']['artifact-ids'], '${{ needs.verify-publication.outputs.artifact_id }}')
        self.assertIn("hashlib.sha256(raw).hexdigest()==os.environ['MANIFEST_SHA']", publish['steps'][1]['run'])
        self.assertIn('pypa/gh-action-pypi-publish@', publish['steps'][-1]['uses'])
        readme = (ROOT / 'README.md').read_text()
        quickstart = readme.split('## Get started', 1)[1].split('## Guides', 1)[0]
        self.assertIn('pipx install flightcheck==0.1.0a2', quickstart)
        self.assertNotIn('pipx install "git+https://github.com/spring-labs-inc/FlightCheck.git"', quickstart)
        rows = [line.split(']')[0].split('[')[-1] for line in readme.splitlines() if line.startswith('| [')]
        self.assertEqual(rows, ['Status Card', 'Workflow', 'Verdict', 'Setup', 'Benchmarks', 'Contributing'])
        guide = (ROOT / 'docs/maintainers/releasing.md').read_text()
        for phrase in ('Published alpha', 'required human reviewers', 'same bytes', 'actual PyPI', 'simulated_registry_match', '#14'):
            self.assertIn(phrase, guide)
        shared = (ROOT / 'setup/README.md').read_text()
        self.assertIn('pipx uninstall flightcheck-cli', shared)
        self.assertIn('Published PyPI distribution: `flightcheck`, version `0.1.0a2`', shared)
        self.assertIn('pipx install "git+https://github.com/spring-labs-inc/FlightCheck.git"', shared)
        self.assertNotIn('not yet a verified public release', shared)
        uv_blocks = [block.split('```', 1)[0] for block in shared.split('```sh\n')[1:] if block.lstrip().startswith('uv tool install ')]
        self.assertEqual(len(uv_blocks), 1, 'Expected one persistent uv installation alternative')
        uv_command = ' '.join(uv_blocks[0].replace('\\\n', ' ').split())
        self.assertEqual(uv_command, 'uv tool install --python /absolute/path/to/python3 --no-python-downloads --no-config --default-index https://pypi.org/simple --prerelease explicit flightcheck==0.1.0a2')

    def workflow(self):
        workflow = yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)
        return workflow

    def downloaded_fixture(self, workflow, job, runner, variant):
        step = next(step for step in workflow['jobs'][job]['steps']
                    if step.get('uses', '').startswith('actions/download-artifact@'))
        options = step['with']
        expected_id = ('${{ inputs.reviewed_artifact_id }}' if job == 'verify-publication'
                       else '${{ needs.verify-publication.outputs.artifact_id }}')
        self.assertEqual(options['artifact-ids'], expected_id)
        self.assertEqual(options['run-id'], '${{ inputs.reviewed_run_id }}')
        self.assertNotIn('name', options, 'A named/latest download must not replace immutable ID selection')
        self.assertEqual(options['path'], '${{ runner.temp }}/release')
        # Exact pinned d3f86a1 source: isSingleArtifactDownload is based on name,
        # not on the number of IDs. Missing merge-multiple defaults to false.
        merge = options.get('merge-multiple', 'false') in ('true', 'True', 'TRUE')
        destination = runner / 'release'
        if not options.get('name') and not merge:
            destination /= 'flightcheck-release'
        if variant == 'nested':
            destination /= 'unexpected-child'
        if variant == 'missing':
            return destination
        if variant == 'empty':
            destination.mkdir(parents=True)
            return destination
        shutil.copytree(self.artifacts, destination)
        if variant in ('wheel-byte', 'sdist-byte'):
            path = next((destination / 'dist').glob('*.whl' if variant == 'wheel-byte' else '*.tar.gz'))
            data = path.read_bytes()
            path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        elif variant == 'extra':
            (destination / 'dist/unapproved-stale.whl').write_bytes(b'Unapproved extra distribution')
        elif variant == 'manifest-byte':
            path = destination / 'release.json'
            path.write_bytes(path.read_bytes() + b'\n')
        return destination

    def workflow_environment(self, runner):
        return {**self.env, 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'],
                'RUNNER_TEMP': str(runner), 'FLIGHTCHECK_PYPI_PUBLISH_ENABLED': 'true',
                'RUN_ID': '123', 'ARTIFACT_ID': '456',
                'SOURCE_SHA': self.record['source']['source_revision'],
                'GITHUB_SHA': self.record['source']['source_revision'],
                'MANIFEST_SHA': hashlib.sha256((self.artifacts / 'release.json').read_bytes()).hexdigest(),
                'GITHUB_OUTPUT': str(runner / 'github-output')}

    def test_workflow_verify_publication_download_layout(self):
        workflow = self.workflow()
        policy = workflow['jobs']['verify-publication']['steps'][-1]['run']
        for variant in ('valid', 'nested', 'missing', 'empty', 'wheel-byte', 'sdist-byte',
                        'extra', 'manifest-byte', 'wrong-current-sha', 'wrong-source-sha', 'wrong-artifact-id'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(dir=self.root) as area:
                runner = Path(area)
                destination = self.downloaded_fixture(workflow, 'verify-publication', runner, variant)
                provider = runner / 'provider'
                provider.mkdir()
                context = self.policy()
                if variant == 'wrong-source-sha':
                    context['run']['head_sha'] = '0' * 40
                elif variant == 'wrong-artifact-id':
                    context['artifact']['id'] = 457
                for name in ('run', 'artifact', 'environment', 'workflow'):
                    (provider / (name + '.json')).write_text(json.dumps(context[name]))
                env = self.workflow_environment(runner)
                if variant == 'wrong-current-sha':
                    env['GITHUB_SHA'] = '0' * 40
                result = subprocess.run(['/bin/bash', '-e', '-c', policy], cwd=self.source,
                                        env=env, capture_output=True, text=True)
                policy_result = json.loads((runner / 'policy.json').read_text())
                if variant == 'valid':
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr + json.dumps(policy_result))
                    self.assertEqual(policy_result['status'], 'eligible_for_protected_job')
                    self.assertEqual(policy_result['artifact_id'], '456')
                    self.assertEqual((runner / 'github-output').read_text(), 'artifact_id=456\n')
                    self.assertEqual(destination, runner / 'release')
                    for name, expected in self.record['files'].items():
                        self.assertEqual(hashlib.sha256((destination / 'dist' / name).read_bytes()).hexdigest(), expected['sha256'])
                else:
                    self.assertNotEqual(result.returncode, 0, variant)
                    self.assertEqual(policy_result['status'], 'incomplete')
                    self.assertFalse((runner / 'github-output').exists(), 'A failed policy cannot authorize the protected download')
        self.assertIn("needs.verify-publication.result == 'success'", workflow['jobs']['publish']['if'])

    def test_workflow_protected_publish_download_layout(self):
        workflow = self.workflow()
        publish = workflow['jobs']['publish']
        bytecheck = publish['steps'][1]['run']
        self.assertEqual(publish['environment']['name'], 'pypi')
        self.assertTrue(publish['steps'][-1]['uses'].startswith('pypa/gh-action-pypi-publish@'))
        self.assertNotIn('if', publish['steps'][-1], 'Do not make upload run after a failed bytecheck')
        self.assertEqual(publish['steps'][-1]['with']['packages-dir'], '${{ runner.temp }}/release/dist/')
        for variant in ('valid', 'nested', 'missing', 'empty', 'wheel-byte', 'sdist-byte', 'extra', 'manifest-byte'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory(dir=self.root) as area:
                runner = Path(area)
                destination = self.downloaded_fixture(workflow, 'publish', runner, variant)
                result = subprocess.run(['/bin/bash', '-e', '-c', bytecheck], cwd=self.source,
                                        env=self.workflow_environment(runner), capture_output=True, text=True)
                if variant == 'valid':
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(destination, runner / 'release')
                    self.assertEqual({p.name for p in (runner / 'release/dist').iterdir()}, set(self.record['files']))
                    for name, expected in self.record['files'].items():
                        self.assertEqual(hashlib.sha256((runner / 'release/dist' / name).read_bytes()).hexdigest(), expected['sha256'])
                else:
                    self.assertNotEqual(result.returncode, 0, variant)
        # No publishing action or live provider approval is executed in this test.

    def test_preparation_candidate_version_consistency(self):
        metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        self.assertEqual(metadata['version'], '0.1.0a2', 'Keep explicit published a2 identity unchanged through cleanup, independent of derived fixture values')
        self.assertEqual(metadata['name'], 'flightcheck')
        self.assertEqual(metadata['license'], 'FSL-1.1-MIT')
        workflow = self.workflow()
        self.assertEqual(workflow['on']['workflow_dispatch']['inputs']['tag']['default'], 'v0.1.0a2')
        self.assertEqual(set(workflow['on']), {'workflow_dispatch'})
        publish = workflow['jobs']['publish']
        self.assertEqual(publish['environment']['name'], 'pypi')
        self.assertEqual(publish['permissions']['id-token'], 'write')
        self.assertIn("vars.FLIGHTCHECK_PYPI_PUBLISH_ENABLED == 'true'", publish['if'])
        self.assertIn("needs.verify-publication.result == 'success'", publish['if'])
        self.assertFalse(any('checkout' in s.get('uses', '') for s in publish['steps']))
        setup_status = [line for line in (ROOT / 'setup/README.md').read_text().splitlines() if line.startswith('Published PyPI distribution: `flightcheck`')]
        self.assertEqual(len(setup_status), 1, 'Expected one current published status sentence in setup/README.md')
        self.assertIn('version `0.1.0a2`', setup_status[0])
        distribution_status = [line for line in (ROOT / 'docs/pypi-distribution.md').read_text().splitlines() if line.startswith('Current release:')]
        self.assertEqual(len(distribution_status), 1, 'Expected one current published status sentence in docs/pypi-distribution.md')
        self.assertIn('`0.1.0a2`', distribution_status[0])
        guide = (ROOT / 'docs/maintainers/releasing.md').read_text()
        release_status = [line for line in guide.splitlines() if line.startswith('**Published alpha.**')]
        self.assertEqual(len(release_status), 1, 'Expected one current published status sentence in docs/maintainers/releasing.md')
        self.assertIn('version `0.1.0a2`', release_status[0])
        self.assertIn('--ref APPROVED_VERSION_TAG -f mode=prepare -f tag=APPROVED_VERSION_TAG', guide)
        self.assertIn('--ref APPROVED_VERSION_TAG -f mode=publish -f tag=APPROVED_VERSION_TAG', guide)
        self.assertIn('instructions for the exact approved public version in a fresh isolated application/tool environment', guide)
        self.assertNotIn("pipx install 'flightcheck==0.1.0a2'", guide)
        self.assertIn('Never rebuild or republish a2', guide)
        self.assertIn('Keep it disabled during preparation.', guide)


if __name__ == '__main__':
    unittest.main()
