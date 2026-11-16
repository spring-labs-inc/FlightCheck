"""Native reproductions requested by independent CODE review."""
import json
from pathlib import Path
import stat
import subprocess
import unittest
import test_terminal_installer as support


class RecoveryBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.TerminalInstallerTests.setUpClass.__func__(cls)

    install_tool = classmethod(support.TerminalInstallerTests.install_tool.__func__)
    setUp = support.TerminalInstallerTests.setUp
    git = support.TerminalInstallerTests.git
    save_config = support.TerminalInstallerTests.save_config
    files = support.TerminalInstallerTests.files
    cli = support.TerminalInstallerTests.cli
    plan = support.TerminalInstallerTests.plan

    def injected_apply(self, body, expected):
        code = """from contextlib import contextmanager
from pathlib import Path
import json,os,stat
import flightcheck_cli.cli as cli
ROOT=Path(TARGET)
original=cli.installer
@contextmanager
def injected():
    with original() as (module,*rest):
        BODY
        yield (module,*rest)
cli.installer=injected
raise SystemExit(cli.main(['init',TARGET,'--apply',PLAN,'--json']))
""".replace('TARGET', repr(str(self.project))).replace('PLAN', repr(str(self.plan_path))).replace('        BODY', '\n'.join('        '+line for line in body.splitlines()))
        result = subprocess.run([str(self.tool / 'bin/python'), '-B', '-c', code], cwd=self.project,
                                env=self.environ, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_ordinary_failure_conflicts_preserve_all_files(self):
        for change in ('bytes', 'mode'):
            with self.subTest(change=change):
                self.setUp()
                self.plan()
                checkpoint = self.root / 'at-failure.json'
                body = """write=module.write_file
written=[]
def fail(root,name,before,after,**kwargs):
    write(root,name,before,after,**kwargs)
    written.append(name)
    if len(written)==3:
        earlier=root/written[0]
        if CHANGE=='bytes':earlier.write_bytes(b'Owner work while apply is open\\n')
        else:earlier.chmod(0o600)
        snapshot={str(p.relative_to(root)):[p.read_bytes().hex(),stat.S_IMODE(p.stat().st_mode)] for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts}
        Path(CHECKPOINT).write_text(json.dumps(snapshot))
        raise OSError('Injected later write failure')
module.write_file=fail
""".replace('CHANGE',repr(change)).replace('CHECKPOINT',repr(str(checkpoint)))
                result=self.injected_apply(body,1)
                self.assertIn('recovery required',result.stdout)
                expected=json.loads(checkpoint.read_text())
                self.assertEqual({n:[b.hex(),m] for n,(b,m) in self.files().items()},expected,
                                 'Conflict detection must precede every rollback mutation')
                journal=next((self.root/'private-state').rglob('transaction.json'))
                record=json.loads(journal.read_text())
                self.assertEqual(record['status'],'rollback_required')
                self.assertTrue(all((journal.parent/row['backup']).is_file() for row in record['files'] if row['backup']))

    def test_temporary_write_crashes_recover_without_owner_loss(self):
        for window in ('create','link'):
            for owner_file in (False,True):
                with self.subTest(window=window,owner_file=owner_file):
                    self.setUp()
                    self.plan()
                    body="""mkstemp=module.tempfile.mkstemp
open_file=module.os.open
link=module.os.link
def add_owner(parent):
    if OWNER:(Path(parent)/'owner-note.txt').write_text('Unrelated owner file\\n')
def crash_temp(*args,**kwargs):
    result=mkstemp(*args,**kwargs)
    if kwargs.get('prefix')=='.flightcheck-':
        add_owner(Path(result[1]).parent)
        if WINDOW=='create':os._exit(77)
    return result
def crash_open(path,flags,*args,**kwargs):
    result=open_file(path,flags,*args,**kwargs)
    if str(path).startswith(str(ROOT)) and Path(path).name.startswith('.flightcheck-') and flags&os.O_EXCL:
        add_owner(Path(path).parent)
        if WINDOW=='create':os._exit(77)
    return result
def crash_link(source,target,*args,**kwargs):
    link(source,target,*args,**kwargs)
    if str(target).startswith(str(ROOT)):
        add_owner(Path(target).parent)
        if WINDOW=='link':os._exit(77)
module.tempfile.mkstemp=crash_temp
module.os.open=crash_open
module.os.link=crash_link
""".replace('OWNER',repr(owner_file)).replace('WINDOW',repr(window))
                    self.injected_apply(body,77)
                    self.assertEqual(self.cli('recover',self.project)['status'],'rolled_back')
                    remaining=self.files()
                    notes={n:v for n,v in remaining.items() if n.endswith('owner-note.txt')}
                    self.assertEqual(len(notes),int(owner_file))
                    self.assertEqual({n:v for n,v in remaining.items() if n not in notes},self.before,
                                     'Completed recovery must remove only journaled temporary files')
                    if not owner_file:self.assertFalse((self.project/'.flightcheck').exists())


if __name__ == '__main__':
    unittest.main()
