"""Exercise the real installed wheel's card commands and retained project helpers."""

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import unittest

import test_card_startup as startup
import test_terminal_installer as terminal


class CardCliTests(unittest.TestCase):
    setUpClass = classmethod(terminal.TerminalInstallerTests.setUpClass.__func__)
    install_tool = classmethod(terminal.TerminalInstallerTests.install_tool.__func__)
    git = terminal.TerminalInstallerTests.git
    save_config = terminal.TerminalInstallerTests.save_config
    files = terminal.TerminalInstallerTests.files
    cli = terminal.TerminalInstallerTests.cli
    plan = terminal.TerminalInstallerTests.plan
    apply = terminal.TerminalInstallerTests.apply
    fake_ssh = startup.StartupTests.fake_ssh
    stop_forwarders = startup.StartupTests.stop_forwarders

    def setUp(self):
        terminal.TerminalInstallerTests.setUp(self)
        self.addCleanup(self.stop_cards)

    def stop_cards(self):
        for path in Path(self.values['evidence_dir']).glob('status-card/*/tasks/*/endpoint.json'):
            try:
                os.kill(json.loads(path.read_text())['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass

    def details(self):
        code="import sys;from pathlib import Path;sys.path.insert(0,'.flightcheck/status-card');import maintainer;print(maintainer.candidate(Path('.')))"
        candidate=subprocess.check_output([terminal.BASE_PYTHON,'-B','-c',code],cwd=self.project,env=self.environ,text=True).strip()
        stages=('Plan','Implement','Cheap Tests','Interactive UI Approval','Independent Code Review',
                'Authoritative Gates','Skeptical Evidence Review','Final Verdict','PR & Merge')
        data={'stages':{n:'current' if n=='Plan' else 'pending' for n in stages},'check_plan':['Native check'],
              'checks':[{'name':'Native check','candidate':candidate,'state':'pending','counts':{},'observed_at':'2026-11-16T00:00:00Z'}],
              'links_unavailable':{'issue':'Disposable artifact fixture.','pr':'No PR exists.'}}
        path=self.root/'details.json';path.write_text(json.dumps(data));return path

    def test_installed_local_cli_verifies_before_link_and_rejects_tampering(self):
        self.plan();self.apply()
        installed=self.files()
        prepared=self.cli('card','--project',self.project,'--task','test-change','--title','Installed wheel card',
                          '--details',self.details(),'--execution','local')
        self.assertEqual(prepared['publication'],'verified')
        self.assertIn(prepared['user_url'],prepared['footer'])
        self.assertEqual(self.files(),installed)
        draft=self.root/'reply.txt';draft.write_text('Artifact check.\n\n'+prepared['footer'])
        checked=self.cli('card','check','--project',self.project,'--task','test-change','--execution','local','--reply-file',draft)
        self.assertEqual(checked['status'],'published')
        self.environ['SSH_CONNECTION']='controlled SSH worker context'
        unavailable=self.cli('card','--project',self.project,'--task','test-change',expected=1)
        self.assertEqual(unavailable['publication'],'verified')
        self.assertNotIn('http',unavailable['footer'])
        helper=self.project/'.flightcheck/status-card/reply.py'
        helper.write_text(helper.read_text()+"\nraise RuntimeError('must not execute modified helper')\n")
        rejected=self.cli('card','--project',self.project,'--task','test-change',expected=1)
        self.assertIn('Modified required status-card component',rejected['error'])
        self.assertNotIn('http',rejected['footer'])

    def test_installed_connect_needs_no_local_project_and_survives_cli_removal(self):
        self.plan();self.apply()
        details=self.details()
        self.fake_ssh()
        state=Path(self.values['evidence_dir'])/'status-card'
        self.environ.update(PATH=self.connector_env['PATH'],SSH_RECORDS=str(self.records),
                            FLIGHTCHECK_STATE_DIR=str(self.root/'connector-state'))
        removable=self.root/'removable-cli';self.install_tool(removable,self.wheel)
        import socket
        with socket.socket() as free:
            free.bind(('127.0.0.1',0));local_port=free.getsockname()[1]
        # The command runs in a directory without any local installation. Only
        # the remote project path is passed to the packaged SSH connector.
        command=[str(removable/'bin/flightcheck'),'card','connect','--ssh','worker-fixture',
                 '--checkout',str(self.project),'--task','test-change','--remote-python',terminal.BASE_PYTHON,
                 '--remote-state-dir',str(state),'--details',str(details),'--local-port',str(local_port),'--json']
        run=subprocess.run(command,cwd=self.root,env=self.environ,capture_output=True,text=True,timeout=60)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        connected=json.loads(run.stdout)
        self.assertEqual(connected['browser_reachability'],'verified')
        self.assertEqual(connected['browser_rendering'],'unobserved')
        subprocess.run([str(removable/'bin/python'),'-B','-m','pip','uninstall','-y','flightcheck'],
                       env=self.environ,check=True,capture_output=True)
        self.assertFalse((removable/'bin/flightcheck').exists())
        record_path = next((self.root/'connector-state').glob('connections/*/connection.json'))
        record = json.loads(record_path.read_text())
        helpers = Path(record['helper_directory'])
        self.assertTrue((helpers/'connect.py').is_file())
        # The packaged temporary source and CLI package are gone. The default
        # supervisor must still execute its bounded probes and own recovery.
        os.kill(record['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            recovered = json.loads(record_path.read_text())
            if recovered['pid'] != record['pid']:
                break
            time.sleep(.1)
        self.assertNotEqual(recovered['pid'], record['pid'])
        self.assertEqual(recovered['user_url'], connected['user_url'])
        os.kill(recovered['pid'], 0)
        env=dict(self.environ,FLIGHTCHECK_STATE_DIR=str(state))
        run=subprocess.run([terminal.BASE_PYTHON,'-B',str(self.project/'.flightcheck/status-card/reply.py'),
                            'prepare','--task','test-change','--execution','remote'],
                           cwd=self.project,env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(json.loads(run.stdout)['footer'],connected['footer'])
        self.assertTrue((self.project/'.flightcheck/status-card/connect.py').is_file())


if __name__=='__main__':
    unittest.main()
