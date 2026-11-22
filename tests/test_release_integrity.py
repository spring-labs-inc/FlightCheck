"""Original-product regressions requested by the independent CODE reviewer."""
import base64
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import subprocess
import sys
import unittest
import zipfile

import test_release as support


class ReleaseIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.ReleaseTests.setUpClass.__func__(cls)

    command = classmethod(support.ReleaseTests.command.__func__)
    setUp = support.ReleaseTests.setUp

    def folder(self, label):
        target = self.root / label
        shutil.copytree(self.artifacts, target)
        return target

    def repair_outer_record(self, folder, artifact):
        record = json.loads((folder / 'release.json').read_text())
        record['files'][artifact.name] = {'size': artifact.stat().st_size,
                                         'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()}
        (folder / 'release.json').write_text(json.dumps(record))

    def test_sdist_build_inputs_are_bound_to_source(self):
        self.command('verify', '--artifacts', self.artifacts, '--require-release')
        for variant in ('setup-py', 'setup-cfg', 'requirements', 'scripts'):
            with self.subTest(variant=variant):
                folder = self.folder(variant)
                artifact = next((folder / 'dist').glob('*.tar.gz'))
                with tarfile.open(artifact) as archive:
                    entries = [(copy.copy(item), archive.extractfile(item).read() if item.isfile() else None)
                               for item in archive.getmembers()]
                root = entries[0][0].name.split('/')[0]
                marker = self.root / 'must-not-execute'
                if variant in ('setup-py', 'setup-cfg'):
                    name = root + ('/setup.py' if variant == 'setup-py' else '/unexpected-build.cfg')
                    item = tarfile.TarInfo(name)
                    data = ("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n").encode()
                    item.size = len(data)
                    entries.append((item, data))
                else:
                    for item, data in entries:
                        if item.name.endswith('/pyproject.toml'):
                            changed = data.replace(b'setuptools==80.9.0', b'setuptools==1.0') if variant == 'requirements' else data.replace(
                                b'flightcheck = "flightcheck_cli.cli:main"', b'other_command = "flightcheck_cli.cli:main"')
                            self.assertNotEqual(data, changed)
                            item.size = len(changed)
                            entries[entries.index((item, data))] = (item, changed)
                            break
                with tarfile.open(artifact, 'w:gz') as archive:
                    for item, data in entries:archive.addfile(item, io.BytesIO(data) if data is not None else None)
                self.repair_outer_record(folder, artifact)
                self.command('verify', '--artifacts', folder, expected=1)
                self.assertFalse(marker.exists(), 'Verification must not execute added build code')

    def test_wheel_python_and_control_metadata_are_bound(self):
        self.command('verify', '--artifacts', self.artifacts, '--require-release')
        variants = [('METADATA', b'Requires-Python: >=3.9', b'Requires-Python: >=99'),
                    ('WHEEL', b'Wheel-Version: 1.0', b'Wheel-Version: 99.0'),
                    ('WHEEL', b'Root-Is-Purelib: true', b'Root-Is-Purelib: false'),
                    ('WHEEL', b'Tag: py3-none-any', b'Tag: cp999-cp999-win_amd64')]
        for i, (suffix, before, after) in enumerate(variants):
            with self.subTest(suffix=suffix, after=after.decode()):
                folder = self.folder('wheel-' + str(i))
                artifact = next((folder / 'dist').glob('*.whl'))
                with zipfile.ZipFile(artifact) as archive:
                    entries = {item.filename: (copy.copy(item), archive.read(item.filename)) for item in archive.infolist()}
                filename = next(n for n in entries if n.endswith('/' + suffix))
                item, data = entries[filename]
                self.assertIn(before, data)
                entries[filename] = (item, data.replace(before, after))
                record_name = next(n for n in entries if n.endswith('/RECORD'))
                table = io.StringIO(newline='')
                writer = csv.writer(table, lineterminator='\n')
                for name, (_, contents) in entries.items():
                    if name == record_name:writer.writerow([name, '', ''])
                    else:writer.writerow([name, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).decode().rstrip('='), str(len(contents))])
                entries[record_name] = (entries[record_name][0], table.getvalue().encode())
                with zipfile.ZipFile(artifact, 'w') as archive:
                    for item, contents in entries.values():archive.writestr(item, contents)
                self.repair_outer_record(folder, artifact)
                self.command('verify', '--artifacts', folder, expected=1)

    def test_canonical_release_tool_in_source_payload(self):
        source_payloads = []
        with zipfile.ZipFile(next((self.artifacts / 'dist').glob('*.whl'))) as archive:
            source_payloads.append(archive.read('flightcheck_cli/source.tar'))
        with tarfile.open(next((self.artifacts / 'dist').glob('*.tar.gz'))) as archive:
            member = next(m for m in archive.getmembers() if m.name.endswith('/flightcheck_cli/source.tar'))
            source_payloads.append(archive.extractfile(member).read())
        for raw in source_payloads:
            with self.subTest(artifact_sha256=hashlib.sha256(raw).hexdigest()), tarfile.open(fileobj=io.BytesIO(raw)) as source:
                names = {m.name for m in source.getmembers()}
                for name in ('tools/release.py', 'docs/maintainers/releasing.md',
                             '.github/workflows/release.yml', '.claude/agents/workflow-code-reviewer.md',
                             '.claude/agents/workflow-evidence-reviewer.md'):
                    self.assertIn(name, names)
                    self.assertEqual(source.extractfile(name).read(), (self.source / name).read_bytes())
                self.assertNotIn('release/release.py', names)
                self.assertFalse(any(name.startswith('experiments/pypi-installer/') for name in names))
        # Current docs and callers must use the canonical entrypoint/procedure.
        # Commit-pinned history links are provenance, not live instructions.
        for path in self.source.rglob('*'):
            relative = path.relative_to(self.source)
            if not path.is_file() or relative.parts[0] in ('.git', 'tests'):
                continue
            if path.suffix not in ('.py', '.md', '.yml', '.yaml', '.toml', '.sh'):
                continue
            content = re.sub(r'https://github\.com/[^\s)]+/(?:blob|tree)/[0-9a-f]{40}/[^\s)]+',
                             '', path.read_text())
            for obsolete in ('release/release.py', 'release/README.md'):
                self.assertNotIn(obsolete, content, str(relative))
        decoy = self.root / 'unrelated'
        decoy.mkdir()
        (decoy / 'pyproject.toml').write_text('Invalid decoy metadata must never be read')
        (decoy / 'LICENSE').write_text('Unrelated owner license')
        alias = self.root / 'source-alias'
        alias.symlink_to(self.source, target_is_directory=True)
        for cwd in (self.source, self.source / 'docs/maintainers', decoy, alias):
            with self.subTest(cwd=str(cwd)):
                before = {str(p.relative_to(decoy)): p.read_bytes() for p in decoy.rglob('*') if p.is_file()}
                result = subprocess.run([sys.executable, '-B', str(self.script), 'verify',
                                         '--artifacts', str(self.artifacts), '--require-release'],
                                        cwd=cwd, env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(json.loads(result.stdout)['release_eligible'])
                self.assertEqual({str(p.relative_to(decoy)): p.read_bytes() for p in decoy.rglob('*') if p.is_file()}, before)
                help_result = subprocess.run([sys.executable, '-B', str(self.script), '--help'],
                                             cwd=cwd, env=self.env, capture_output=True, text=True)
                self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
                self.assertEqual({str(p.relative_to(decoy)): p.read_bytes() for p in decoy.rglob('*') if p.is_file()}, before)



    def test_src_layout_and_sdist_configuration(self):
        import tomllib
        with zipfile.ZipFile(next((self.artifacts/'dist').glob('*.whl'))) as wheel:
            manifest=json.loads(wheel.read('flightcheck_cli/manifest.json'))
            with tarfile.open(fileobj=io.BytesIO(wheel.read('flightcheck_cli/source.tar'))) as archive:
                source={item.name:archive.extractfile(item).read() for item in archive if item.isfile()}
            expected={name.removeprefix('src/flightcheck_cli/'):hashlib.sha256(body).hexdigest()
                      for name,body in source.items() if name.startswith('src/flightcheck_cli/') and name.count('/')==2 and name.endswith('.py')}
            self.assertTrue(expected)
            self.assertEqual(manifest['cli_files'],expected)
            self.assertFalse(any(name.startswith('src/') for name in wheel.namelist()))
            config=tomllib.loads(source['pyproject.toml'].decode())
            self.assertEqual(config['tool']['setuptools']['package-dir'],{'':'src'})
            self.assertEqual(config['project']['description'],'FlightCheck is a lightweight set of repository instructions that guides AI-assisted changes from request to landing.')
        with tarfile.open(next((self.artifacts/'dist').glob('*.tar.gz'))) as archive:
            members={item.name.split('/',1)[1]:archive.extractfile(item).read() for item in archive if item.isfile()}
        staged=tomllib.loads(members['pyproject.toml'].decode())
        config['build-system']['build-backend']='setuptools.build_meta'
        config['build-system'].pop('backend-path')
        self.assertEqual(staged,config)
        self.assertEqual({n.removeprefix('src/flightcheck_cli/') for n in members if n.startswith('src/flightcheck_cli/') and n.endswith('.py')},set(expected))
        self.command('verify','--artifacts',self.artifacts,'--require-release')

    def test_dynamic_cli_inventory_uses_declared_source(self):
        changed=self.root/'dynamic-source'
        shutil.copytree(self.source,changed)
        package=changed/'src/flightcheck_cli' if (changed/'src/flightcheck_cli').is_dir() else changed/'flightcheck_cli'
        body=b'"""Legitimate dynamic CLI module fixture."""\nVALUE = 89\n'
        (package/'added_contract.py').write_bytes(body)
        if package.parent.name=='src':
            stale=changed/'flightcheck_cli';stale.mkdir();(stale/'cli.py').write_bytes(b'raise RuntimeError("stale source must not be packaged")\n')
        subprocess.run(['git','-C',str(changed),'add','--force','.'],env=self.env,check=True,capture_output=True)
        folder=self.root/'dynamic-artifacts'
        script=changed/'tools/release.py'
        self.command('prepare','--output',folder,'--review',script=script)
        self.command('verify','--artifacts',folder,script=script)
        with zipfile.ZipFile(next((folder/'dist').glob('*.whl'))) as wheel:
            manifest=json.loads(wheel.read('flightcheck_cli/manifest.json'))
            self.assertEqual(wheel.read('flightcheck_cli/added_contract.py'),body)
            self.assertEqual(manifest['cli_files']['added_contract.py'],hashlib.sha256(body).hexdigest())
            self.assertNotIn(b'stale source must not be packaged',wheel.read('flightcheck_cli/cli.py'))
        prefix='src/flightcheck_cli/' if package.parent.name=='src' else 'flightcheck_cli/'
        with tarfile.open(next((folder/'dist').glob('*.tar.gz'))) as archive:
            members={item.name.split('/',1)[1]:archive.extractfile(item).read() for item in archive if item.isfile()}
        self.assertEqual(members[prefix+'added_contract.py'],body)

if __name__ == '__main__':
    unittest.main()
