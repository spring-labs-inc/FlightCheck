"""Original-product regressions requested by the independent CODE reviewer."""
import base64
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
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


if __name__ == '__main__':
    unittest.main()
