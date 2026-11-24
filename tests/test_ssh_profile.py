"""Exercise the connector with real OpenSSH connection sharing on loopback.

Synthetic keys, private configuration, restricted forwarding and a fixed command
keep this fixture independent of the user's SSH accounts and configuration.
"""

import getpass
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import test_card_startup as startup


class SSHProfileTests(unittest.TestCase):
    setUp = startup.StartupTests.setUp
    git = startup.StartupTests.git
    stop_listeners = startup.StartupTests.stop_listeners
    api = startup.StartupTests.api
    directory = startup.StartupTests.directory
    snapshot = startup.StartupTests.snapshot
    endpoint = startup.StartupTests.endpoint
    wait_stopped = startup.StartupTests.wait_stopped
    write_details = startup.StartupTests.write_details
    connector = startup.StartupTests.connector
    fake_ssh = startup.StartupTests.fake_ssh
    stop_forwarders = startup.StartupTests.stop_forwarders
    stop_monitors = startup.StartupTests.stop_monitors

    def real_ssh(self):
        if not all(Path(p).is_file() for p in ('/usr/bin/ssh', '/usr/bin/ssh-keygen', '/usr/sbin/sshd')):
            self.skipTest('Real OpenSSH client, keygen and server are required for this integration fixture')
        self.ssh_directory = self.root / 'real-ssh'
        self.ssh_directory.mkdir(mode=0o700)
        short = tempfile.TemporaryDirectory(prefix='fc-sock-', dir='/tmp')
        self.addCleanup(short.cleanup)
        control = Path(short.name) / 'c'
        d = self.ssh_directory
        for name in ('host', 'client'):
            subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(d/name)],
                           check=True, capture_output=True)
        (d/'authorized_keys').write_bytes((d/'client.pub').read_bytes())
        (d/'authorized_keys').chmod(0o600)
        with socket.socket() as free:
            free.bind(('127.0.0.1', 0))
            ssh_port = free.getsockname()[1]
        # The forced command executes only this fixture's exact card helper.
        # SSH_ORIGINAL_COMMAND is parsed to argv, never evaluated as a shell.
        forced = d/'command.py'
        forced.write_text('import os,shlex,subprocess,sys\n'
                          'args=shlex.split(os.environ.get("SSH_ORIGINAL_COMMAND",""))\n'
                          'if not args:sys.exit(0)\n'
                          'project='+repr(str(self.checkout))+'\n'
                          'state='+repr(str(self.state))+'\n'
                          'prefix=["cd",project,"&&","env","FLIGHTCHECK_STATE_DIR="+state,'
                          +repr(sys.executable)+',"-B","status-card/reply.py"]\n'
                          'if args[:len(prefix)]!=prefix:sys.exit(126)\n'
                          'env=dict(os.environ,FLIGHTCHECK_STATE_DIR=state)\n'
                          'sys.exit(subprocess.run(args[5:],cwd=project,env=env).returncode)\n')
        (d/'server.conf').write_text(
            f'Port {ssh_port}\nListenAddress 127.0.0.1\nHostKey {d/"host"}\nPidFile {d/"pid"}\n'
            f'AuthorizedKeysFile {d/"authorized_keys"}\nStrictModes no\nUsePAM no\n'
            'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitTTY no\n'
            'AllowTcpForwarding local\nAllowStreamLocalForwarding no\n'
            f'PermitOpen 127.0.0.1:{self.endpoint()["port"]}\n'
            'ForceCommand '+shlex.join([sys.executable, '-B', str(forced)])+'\nLogLevel ERROR\n')
        (d/'known_hosts').write_text(f'[127.0.0.1]:{ssh_port} '+(d/'host.pub').read_text())
        self.client_config = d/'client.conf'
        self.client_config.write_text(
            f'Host worker-fixture\n HostName 127.0.0.1\n Port {ssh_port}\n User {getpass.getuser()}\n'
            f' IdentityFile {d/"client"}\n IdentityAgent none\n IdentitiesOnly yes\n BatchMode yes\n'
            f' StrictHostKeyChecking yes\n UserKnownHostsFile {d/"known_hosts"}\n'
            f' GlobalKnownHostsFile /dev/null\n UpdateHostKeys no\n ControlMaster auto\n'
            f' ControlPath {control}\n ControlPersist no\n ForkAfterAuthentication no\n')
        self.processes = []
        self.addCleanup(self.stop_real_ssh)
        with (d/'server.log').open('wb') as log:
            server = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', str(d/'server.conf')],
                                      stdout=log, stderr=log)
        self.processes.append(server)
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            if server.poll() is not None:
                self.fail((d/'server.log').read_text())
            try:
                with socket.create_connection(('127.0.0.1', ssh_port), timeout=.1):
                    break
            except OSError:
                time.sleep(.05)
        with (d/'master.log').open('wb') as log:
            self.master = subprocess.Popen(['/usr/bin/ssh', '-F', str(self.client_config), '-M', '-N', '-T',
                                            'worker-fixture'], stdout=subprocess.DEVNULL, stderr=log)
        self.processes.append(self.master)
        deadline = time.monotonic()+5
        while time.monotonic()<deadline and not control.exists():
            if self.master.poll() is not None:
                self.fail((d/'master.log').read_text())
            time.sleep(.05)
        self.assertTrue(control.exists(), 'SSH master control socket did not appear')
        binary = self.root/'bin'
        binary.mkdir()
        wrapper = binary/'ssh'
        wrapper.write_text('#!/bin/sh\nexec /usr/bin/ssh -F '+shlex.quote(str(self.client_config))+' "$@"\n')
        wrapper.chmod(0o755)
        self.connector_env = dict(self.env, PATH=str(binary)+os.pathsep+self.env.get('PATH', ''),
                                  FLIGHTCHECK_STATE_DIR=str(self.root/'connector-state'))

    def stop_real_ssh(self):
        self.stop_monitors()
        # Only the managed child for our private test configuration is eligible.
        for path in (self.root/'connector-state').glob('connections/*/connection.json'):
            pid = json.loads(path.read_text()).get('pid')
            if pid:
                probe = subprocess.run(['ps', '-p', str(pid), '-o', 'uid=', '-o', 'args='],
                                       capture_output=True, text=True)
                fields = probe.stdout.strip().split(maxsplit=1)
                if (len(fields)==2 and fields[0]==str(os.geteuid())
                        and str(self.client_config) in fields[1]):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        for process in reversed(self.processes):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def test_shared_profile_keeps_tunnel_owned_and_master_usable(self):
        self.api('prepare', '--execution', 'remote', expected=1)
        self.real_ssh()
        config_before = self.client_config.read_bytes()
        first = self.connector()
        self.assertEqual(first['browser_reachability'], 'verified')
        self.assertEqual(first['browser_rendering'], 'unobserved')
        record_path = next((self.root/'connector-state').glob('connections/*/connection.json'))
        record = json.loads(record_path.read_text())
        self.assertNotEqual(record['pid'], self.master.pid)
        os.kill(record['pid'], 0)
        second = self.connector()
        self.assertEqual(first['footer'], second['footer'])
        self.assertEqual(json.loads(record_path.read_text())['pid'], record['pid'])
        self.assertIsNone(self.master.poll(), 'Existing shared SSH master was disturbed')
        check = subprocess.run(['/usr/bin/ssh', '-F', str(self.client_config), '-O', 'check', 'worker-fixture'],
                               capture_output=True, text=True, timeout=5)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(self.client_config.read_bytes(), config_before)
    def test_monitor_recovers_real_owned_ssh_tunnel(self):
        self.api('prepare', '--title', 'Real SSH monitor', '--execution', 'remote', expected=1)
        self.real_ssh()
        first = self.connector()
        record_path = next((self.root/'connector-state').glob('connections/*/connection.json'))
        original = json.loads(record_path.read_text())
        os.kill(original['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 18
        while time.monotonic() < deadline:
            record = json.loads(record_path.read_text())
            if record['pid'] != original['pid']:
                break
            time.sleep(.1)
        self.assertNotEqual(record['pid'], original['pid'])
        os.kill(record['pid'], 0)
        self.assertEqual(record['user_url'], first['user_url'])
        self.assertEqual(self.snapshot()['title'], 'Real SSH monitor')
        monitor = json.loads((record_path.parent/'monitor.json').read_text())
        self.assertEqual(monitor['transport'], 'verified')
        self.assertIsNone(self.master.poll())

    def test_shared_master_does_not_authorize_an_incorrect_forward(self):
        self.api('prepare', '--execution', 'remote', expected=1)
        self.real_ssh()
        first = self.connector()
        record_path = next((self.root/'connector-state').glob('connections/*/connection.json'))
        before = record_path.read_bytes()
        record = json.loads(before)
        os.kill(record['pid'], signal.SIGTERM)
        self.wait_stopped(self.local_port)
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from urllib.request import build_opener, ProxyHandler
        class Other(BaseHTTPRequestHandler):
            def do_GET(inner):
                raw=json.dumps({'snapshot':'live','task':'other-task','candidate':'0'*64,
                                'publicationPort':self.endpoint()['port']}).encode()
                inner.send_response(200);inner.send_header('Content-Length',str(len(raw)));inner.end_headers();inner.wfile.write(raw)
            def log_message(*args):pass
        other=ThreadingHTTPServer(('127.0.0.1',self.local_port),Other)
        worker=threading.Thread(target=other.serve_forever,daemon=True);worker.start()
        try:
            result=self.connector(expected=1)
            self.assertEqual(result['status'],'unavailable')
            self.assertNotIn('http',result['footer'])
            self.assertEqual(record_path.read_bytes(),before)
            with build_opener(ProxyHandler({})).open(first['user_url']+'status.json',timeout=2) as response:
                self.assertEqual(json.load(response)['task'],'other-task')
            self.assertIsNone(self.master.poll())
            check=subprocess.run(['/usr/bin/ssh','-F',str(self.client_config),'-O','check','worker-fixture'],
                                 capture_output=True,text=True,timeout=5)
            self.assertEqual(check.returncode,0,check.stderr)
        finally:
            other.shutdown();other.server_close();worker.join()

    def test_ssh_failure_reports_exit_status_and_stderr(self):
        self.api('prepare', '--execution', 'remote', expected=1)
        self.fake_ssh()
        ssh = self.root/'bin/ssh'
        source = ssh.read_text()
        source = source.replace("if os.environ.get('SSH_FAILURE')=='auth':sys.exit(255)",
                                "if os.environ.get('SSH_FAILURE')=='auth':\n sys.stderr.write('Synthetic authentication denied\\n');sys.exit(255)")
        source = source.replace("if os.environ.get('SSH_FAILURE')=='forward':sys.exit(255)",
                                "if os.environ.get('SSH_FAILURE')=='forward':\n sys.stderr.write('Synthetic forwarding denied\\n');sys.exit(255)")
        ssh.write_text(source)
        for mode, message in [('auth', 'Synthetic authentication denied'), ('forward', 'Synthetic forwarding denied')]:
            with self.subTest(mode=mode):
                result = self.connector(expected=1, env=dict(self.connector_env, SSH_FAILURE=mode))
                self.assertNotIn('http', result['footer'])
                self.assertIn('255', result['error'])
                self.assertIn(message, result['error'])


if __name__=='__main__':
    unittest.main()
