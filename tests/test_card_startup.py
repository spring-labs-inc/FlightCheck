"""Public startup/forwarding witnesses; SSH process fixture uses real TCP relays.

These controlled SSH boundary tests do not qualify an owner's actual SSH account
or desktop browser. The release checklist requires that separate live rehearsal.
"""

import json
import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import unittest
import shutil
import tempfile

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))


class StartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "checkout with spaces"
        self.checkout.mkdir()
        shutil.copytree(PRODUCT / "status-card", self.checkout / "status-card")
        self.readme = self.checkout / "README.md"
        self.readme.write_text("Original fixture\n")
        self.state = self.root / "private state"
        self.draft = self.root / "reply.txt"
        self.env = {key: value for key, value in os.environ.items() if key not in
                    ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "CODESPACES", "REMOTE_CONTAINERS")}
        self.env.update(FLIGHTCHECK_STATE_DIR=str(self.state), PYTHONDONTWRITEBYTECODE="1")
        self.listeners = set()
        self.addCleanup(self.stop_listeners)
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "Disposable reply fixture")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
            cwd=self.checkout, env=self.env, text=True, stderr=subprocess.DEVNULL).strip()

    def stop_listeners(self):
        for pid in self.listeners:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def write_details(self):
        code = "import sys;from pathlib import Path;sys.path.insert(0,'status-card');import maintainer;print(maintainer.candidate(Path('.')))"
        current = subprocess.check_output([sys.executable, '-B', '-c', code], cwd=self.checkout, env=self.env, text=True).strip()
        stages = ('Plan','Implement','Cheap Tests','Interactive UI Approval','Independent Code Review',
                  'Authoritative Gates','Skeptical Evidence Review','Final Verdict','PR & Merge')
        details = {'stages':{name:'current' if name=='Plan' else 'pending' for name in stages},
                   'check_plan':['Fixture check'],
                   'checks':[{'name':'Fixture check','candidate':current,'state':'pending','counts':{},
                              'observed_at':'2026-01-01T00:00:00Z'}],
                   'links_unavailable':{'issue':'Disposable fixture.','pr':'No PR exists.'}}
        detail_path=self.root/'fixture-details.json';detail_path.write_text(json.dumps(details))
        return detail_path

    def api(self, command, *args, expected=0, env=None, cwd=None):
        if command == "prepare" and "--context" not in args:
            args=['--details',str(self.write_details()),*args]
        result = subprocess.run([sys.executable, "-B", str(self.checkout / "status-card/reply.py"),
                                 command, "--task", "test-change", *args],
                                cwd=cwd or self.checkout, env=env or self.env,
                                capture_output=True, text=True, timeout=20)
        for p in self.state.glob("*/tasks/*/endpoint.json"):
            self.listeners.add(json.loads(p.read_text())["pid"])
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def directory(self):
        directory, = self.state.glob("*/tasks/test-change")
        return directory

    def snapshot(self):
        return json.loads((self.directory() / "status.json").read_text())

    def endpoint(self):
        return json.loads((self.directory() / "endpoint.json").read_text())

    def check(self, text, phase="update", expected=0, *args):
        self.draft.write_text(text)
        return self.api("check", "--phase", phase, "--reply-file", str(self.draft), *args, expected=expected)

    def wait_stopped(self, port):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.1):
                    pass
            except OSError:
                return
            time.sleep(.02)
        self.fail("Listener did not stop")

    def test_local_startup_recovers_and_failure_has_no_clickable_footer(self):
        first = self.api('prepare')
        self.assertEqual(first['publication'], 'verified')
        self.assertIn(first['user_url'], first['footer'])
        endpoint = self.endpoint()
        os.kill(endpoint['pid'], signal.SIGTERM)
        self.wait_stopped(endpoint['port'])
        self.readme.write_text('New candidate while stopped\n')
        recovered = self.api('prepare')
        self.assertEqual(recovered['footer'], first['footer'])
        self.assertNotEqual(recovered['candidate'], first['candidate'])
        self.assertEqual(self.snapshot()['candidate'], recovered['candidate'])
        self.assertNotEqual(self.endpoint()['pid'], endpoint['pid'])
        # A first startup that never reports readiness offers no clickable card.
        (self.checkout / 'status-card/serve.py').write_text("import time\nprint('broken',flush=True)\ntime.sleep(20)\n")
        start = time.monotonic()
        failed = self.api('prepare', expected=1, env=dict(self.env, FLIGHTCHECK_STATE_DIR=str(self.root / 'failed-state')))
        self.assertLess(time.monotonic() - start, 9)
        self.assertEqual(failed['publication'], 'unavailable')
        self.assertNotIn('http', failed['footer'])

    def test_remote_entrypoints_never_offer_host_loopback(self):
        for marker in ('SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY', 'CODESPACES', 'REMOTE_CONTAINERS'):
            remote = self.api('prepare', expected=1, env=dict(self.env, **{marker:'fixture'}))
            self.assertEqual(remote['execution'], 'remote')
            self.assertEqual(remote['publication'], 'verified')
            self.assertNotIn('http', remote['footer'])
        for extra, env in (([],dict(self.env,SSH_CONNECTION='fixture')),(['--execution','remote'],self.env)):
            remote = self.api('prepare', *extra, env=env, expected=1)
            result = subprocess.run([sys.executable,'-B',str(self.checkout/'status-card/maintainer.py'),
                                     'card','--task','test-change','--title','Remote test',*extra],
                                    cwd=self.checkout,env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertNotIn('http',result.stdout)
            self.draft.write_text(remote['footer'])
            checked=self.api('check','--reply-file',str(self.draft),*extra,env=env,expected=1)
            self.assertNotIn('http',checked['footer'])
        supplied='http://127.0.0.1:43210/task/test-change/'
        declared=self.api('prepare','--execution','remote','--user-url',supplied)
        self.assertEqual(declared['browser_reachability'],'unobserved')
        self.assertEqual(declared['browser_rendering'],'unobserved')
        self.assertIn(supplied,declared['footer'])

    def fake_ssh(self):
        binary=self.root/'bin';binary.mkdir()
        script=binary/'ssh'
        script.write_text('#!'+sys.executable+'\n'+'''import json,os,socket,socketserver,subprocess,sys,threading
from pathlib import Path
args=sys.argv[1:]
with Path(os.environ['SSH_RECORDS']).open('a') as f:f.write(json.dumps({'pid':os.getpid(),'args':args})+'\\n')
if os.environ.get('SSH_FAILURE')=='auth':sys.exit(255)
if '-N' not in args:
 if os.environ.get('SSH_FAILURE')=='confirm' and ('--user-url' in args[-1] or 'confirm-connection' in args[-1]):sys.exit(255)
 r=subprocess.run(args[-1],shell=True,capture_output=True,text=True)
 if os.environ.get('SSH_FAILURE')=='identity':
  d=json.loads(r.stdout);d['task']='other-task';print(json.dumps(d));sys.exit(r.returncode)
 sys.stdout.write(r.stdout);sys.stderr.write(r.stderr);sys.exit(r.returncode)
if os.environ.get('SSH_FAILURE')=='forward':sys.exit(255)
_,local,_,remote=args[args.index('-L')+1].split(':')
class Relay(socketserver.BaseRequestHandler):
 def handle(self):
  try:up=socket.create_connection(('127.0.0.1',int(remote)),timeout=2)
  except OSError:return
  def pump(a,b):
   try:
    while True:
     block=a.recv(65536)
     if not block:break
     b.sendall(block)
   except OSError:pass
   finally:
    try:b.shutdown(socket.SHUT_WR)
    except OSError:pass
  t=threading.Thread(target=pump,args=(self.request,up),daemon=True);t.start();pump(up,self.request);t.join(2);up.close()
class Server(socketserver.ThreadingTCPServer):
 allow_reuse_address=True
 daemon_threads=True
with Server(('127.0.0.1',int(local)),Relay) as server:server.serve_forever()
''')
        script.chmod(0o755)
        self.records=self.root/'ssh-records.jsonl'
        self.connector_env=dict(self.env,PATH=str(binary)+os.pathsep+self.env.get('PATH',''),
                                SSH_RECORDS=str(self.records),FLIGHTCHECK_STATE_DIR=str(self.root/'connector-state'))
        self.addCleanup(self.stop_forwarders)

    def stop_monitors(self):
        for path in (self.root/'connector-state').glob('connections/*/connection.json'):
            record = json.loads(path.read_text())
            pid = record.get('supervisor_pid')
            if not pid:
                continue
            probe = subprocess.run(['ps', '-p', str(pid), '-o', 'uid=', '-o', 'args='],
                                   capture_output=True, text=True)
            fields = probe.stdout.strip().split(maxsplit=1)
            if (len(fields) == 2 and fields[0] == str(os.geteuid())
                    and str(Path(record.get('helper_directory') or self.root)/'connect.py') in fields[1]
                    and '--supervise ' in fields[1]):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 3
                with (path.parent/'monitor.lock').open('a') as lock:
                    while time.monotonic() < deadline:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            time.sleep(.02)

    def stop_forwarders(self):
        StartupTests.stop_monitors(self)
        if self.records.exists():
            for line in self.records.read_text().splitlines():
                record=json.loads(line)
                if '-N' in record['args']:
                    try:os.kill(record['pid'],signal.SIGTERM)
                    except ProcessLookupError:pass

    def connector(self,*extra,expected=0,env=None):
        with socket.socket() as free:
            free.bind(('127.0.0.1',0))
            free_port=free.getsockname()[1]
        if not hasattr(self,'local_port'):self.local_port=free_port
        command=[sys.executable,'-B',str(self.checkout/'status-card/connect.py'),'--ssh','worker-fixture',
                 '--checkout',str(self.checkout),'--card-dir','status-card','--remote-python',sys.executable,
                 '--remote-state-dir',str(self.state),'--task','test-change','--local-port',str(self.local_port),*extra]
        result=subprocess.run(command,cwd=self.root,env=env or self.connector_env,capture_output=True,text=True,timeout=40)
        for p in self.state.glob('*/tasks/*/endpoint.json'):
            self.listeners.add(json.loads(p.read_text())['pid'])
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        return json.loads(result.stdout)

    def test_connector_verifies_and_preserves_route(self):
        self.api('prepare','--execution','remote',expected=1)
        self.fake_ssh()
        first=self.connector()
        self.assertEqual(first['browser_reachability'],'verified')
        self.assertEqual(first['browser_rendering'],'unobserved')
        self.assertIn(first['user_url'],first['footer'])
        self.assertNotEqual(first['user_url'],first['host_url'])
        records=[json.loads(x) for x in self.records.read_text().splitlines()]
        forward=[x for x in records if '-N' in x['args']]
        self.assertEqual(len(forward),1)
        args=forward[0]['args'];self.assertIn('ExitOnForwardFailure=yes',args)
        self.assertTrue(args[args.index('-L')+1].startswith('127.0.0.1:'))
        second=self.connector()
        self.assertEqual(second['footer'],first['footer'])
        self.assertEqual(sum('-N' in json.loads(x)['args'] for x in self.records.read_text().splitlines()),1)
        # Restore a dead remote service and a changed candidate through the
        # existing forward; a previously valid snapshot must not satisfy it.
        endpoint=self.endpoint();os.kill(endpoint['pid'],signal.SIGTERM);self.wait_stopped(endpoint['port'])
        self.readme.write_text('Changed candidate after remote service stopped\n')
        # Writing details is not a lifecycle call. Only the connector can
        # restore the stopped worker service.
        details=self.write_details()
        resumed=self.connector('--details',str(details))
        self.assertEqual(resumed['footer'],first['footer'])
        self.assertNotEqual(resumed['candidate'],first['candidate'])
        self.assertEqual(resumed['candidate'],self.snapshot()['candidate'])
        self.assertNotEqual(self.endpoint()['pid'],endpoint['pid'])
        self.stop_forwarders();self.wait_stopped(self.local_port)
        restored=self.connector()
        self.assertEqual(restored['footer'],first['footer'])
        self.assertEqual(restored['candidate'],resumed['candidate'])
        forwards=[json.loads(x)['pid'] for x in self.records.read_text().splitlines() if '-N' in json.loads(x)['args']]
        self.assertNotEqual(forwards[-1],forwards[0])
        os.kill(forwards[-1],0)

    def test_reconnect_title_preservation(self):
        self.api('prepare', '--title', 'Owner descriptive title', '--execution', 'remote', expected=1)
        self.fake_ssh()
        first = self.connector()
        self.assertEqual(self.snapshot()['title'], 'Owner descriptive title')
        self.assertEqual(first['monitor'], 'active')
        resumed = self.connector()
        self.assertEqual(first['footer'], resumed['footer'])
        self.assertEqual(self.snapshot()['title'], 'Owner descriptive title')
        self.connector('--title', 'Explicit connector title')
        self.connector()
        self.assertEqual(self.snapshot()['title'], 'Explicit connector title')
        records = [json.loads(line) for line in self.records.read_text().splitlines()]
        prepares = [row['args'][-1] for row in records if '-N' not in row['args']
                    and ' prepare ' in row['args'][-1]]
        self.assertNotIn('--title', prepares[0])
        self.assertTrue(any("'Explicit connector title'" in command for command in prepares))

    def test_connector_failures_never_offer_a_link(self):
        self.api('prepare','--execution','remote',expected=1)
        self.fake_ssh()
        for failure in ('auth','identity','forward'):
            failed=self.connector(expected=1,env=dict(self.connector_env,SSH_FAILURE=failure))
            self.assertEqual(failed['status'],'unavailable')
            self.assertNotIn('http',failed['footer'])
        invalid=self.connector('--ssh','bad host',expected=1)
        self.assertNotIn('http',invalid['footer'])
        self.assert_forward_cleanup()

    def test_connector_occupied_route(self):
        self.api('prepare','--execution','remote',expected=1)
        self.fake_ssh()
        first=self.connector()
        record_path=next((self.root/'connector-state').glob('connections/*/connection.json'))
        original=record_path.read_bytes()
        self.stop_forwarders();self.wait_stopped(self.local_port)
        # An unrelated, syntactically valid card with the wrong task and
        # candidate owns the preserved port. Neither acceptance nor signalling
        # it is allowed, and the recorded route must not silently change.
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading
        class Other(BaseHTTPRequestHandler):
            def do_GET(inner):
                raw=json.dumps({'snapshot':'live','task':'other-task','candidate':'0'*64,
                                'publicationPort':self.endpoint()['port']}).encode()
                inner.send_response(200);inner.send_header('Content-Length',str(len(raw)));inner.end_headers();inner.wfile.write(raw)
            def log_message(*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',self.local_port),Other)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            failed=self.connector(expected=1)
            self.assertNotIn('http',failed['footer'])
            self.assertIn('occupied',failed['error'])
            self.assertEqual(record_path.read_bytes(),original)
            with socket.create_connection(server.server_address,timeout=1):pass
            self.assertIn(str(self.local_port),first['user_url'])
        finally:
            server.shutdown();server.server_close();thread.join()

    def assert_forward_cleanup(self):
        first=self.connector()
        record_path=next((self.root/'connector-state').glob('connections/*/connection.json'))
        self.stop_forwarders();self.wait_stopped(self.local_port)
        original=record_path.read_bytes()
        with socket.socket() as unrelated:
            unrelated.bind(('127.0.0.1',0));unrelated.listen()
            start=time.monotonic()
            failed=self.connector(expected=1,env=dict(self.connector_env,SSH_FAILURE='confirm'))
            self.assertLess(time.monotonic()-start,15)
            self.assertNotIn('http',failed['footer'])
            self.assertEqual(record_path.read_bytes(),original)
            forwards=[json.loads(x)['pid'] for x in self.records.read_text().splitlines() if '-N' in json.loads(x)['args']]
            # Second preparation failed only after a real forward was started
            # and the correct snapshot was reached through it.
            with self.assertRaises(ProcessLookupError):os.kill(forwards[-1],0)
            with socket.create_connection(unrelated.getsockname(),timeout=1):pass
            # A failure after reusing an already healthy route cannot own that
            # route's process, and therefore must leave it alive.
            healthy=self.connector()
            self.assertEqual(healthy['footer'],first['footer'])
            original=record_path.read_bytes()
            reused_pid=json.loads(original)['pid']
            failed=self.connector(expected=1,env=dict(self.connector_env,SSH_FAILURE='confirm'))
            self.assertNotIn('http',failed['footer'])
            self.assertEqual(record_path.read_bytes(),original)
            os.kill(reused_pid,0)


if __name__=='__main__':
    unittest.main()
