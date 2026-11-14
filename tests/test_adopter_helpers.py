"""Exercise supplied evidence helpers through real pytest and disposable adopters."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = PRODUCT / "examples/existing-project/scripts"


class AdopterHelperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir(mode=0o700)
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")

    def run_script(self, script, *args, expected=0, data=None, env=None, cwd=None):
        result = subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *map(str,args)],
                                cwd=cwd or self.project, env=env or self.env, input=data,
                                capture_output=True, timeout=120)
        self.assertEqual(result.returncode, expected, result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
        return result

    def git(self, *args):
        return subprocess.check_output(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                '-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',*args],cwd=self.project,env=self.env).strip()

    def pytest(self, text, expected, *extra):
        path = self.project/'test_contract.py'
        path.write_text(text)
        output = self.root/('reports-'+str(time.time_ns()))
        output.mkdir()
        env=dict(self.env,FLIGHTCHECK_REPORT_DIR=str(output))
        self.run_script('pytest_report.py','--spec',path,'--','-q','-p','no:cacheprovider',*extra,str(path),expected=expected,env=env)
        return json.loads((output/'coverage.json').read_text()),json.loads((output/'phases.json').read_text())

    def test_pytest_reporting_preserves_native_phase_and_subtest_outcomes(self):
        report,phases=self.pytest('''import pytest
@pytest.fixture
def setup_bad(): raise RuntimeError('setup failure')
@pytest.fixture
def teardown_bad():
 yield
 raise RuntimeError('teardown failure')
def test_setup(setup_bad): pass
def test_teardown(teardown_bad): pass
def test_call(): assert False
def test_skip(): pytest.skip('native skip')
@pytest.mark.xfail(reason='native xfail')
def test_xfail(): assert False
@pytest.mark.xfail(strict=True,reason='strict xpass')
def test_xpass(): pass
@pytest.mark.parametrize('value',[1,2])
def test_param(value): assert value>0
@pytest.mark.parametrize('value',[1,2])
def test_subtests(value,subtests,request):
 with subtests.test(msg='identical', value=0): assert True
 with subtests.test(msg='skipped'): pytest.skip('subtest only')
 if value==2: request.addfinalizer(lambda: (_ for _ in ()).throw(RuntimeError('late teardown')))
def test_subfailure(subtests):
 with subtests.test(msg='failure'): assert False
''',1)
        prefix='test_contract.py::'
        self.assertEqual(set(report['passed']),{prefix+'test_param[1]',prefix+'test_param[2]',prefix+'test_subtests[1]'})
        self.assertEqual(set(report['failed']),{prefix+x for x in ('test_setup','test_teardown','test_call','test_xpass','test_subtests[2]','test_subfailure')})
        self.assertEqual(report['skipped'],[prefix+'test_skip'])
        self.assertEqual(report['expected_failures'],[prefix+'test_xfail'])
        flattened=[identity for values in report.values() for identity in values]
        self.assertEqual(len(flattened),len(set(flattened)))
        self.assertEqual(set(phases['events']),set(flattened))
        self.assertTrue(any(e['when']=='teardown' and e['outcome']=='failed' for e in phases['events'][prefix+'test_subtests[2]']))
        self.assertTrue(all(any(e['subtest'] for e in phases['events'][prefix+'test_subtests['+str(i)+']']) for i in (1,2)))
        incomplete,details=self.pytest('def test_not_run(): pass\n',3,'--setup-only')
        self.assertFalse(any(incomplete.values()))
        self.assertEqual(details['pytest_exit_code'],0)
        self.assertTrue(details['incomplete'])
        unit,detail=self.pytest('''import unittest
class Cases(unittest.TestCase):
 def test_native(self):
  for value in (1,2):
   with self.subTest(value=value): self.assertEqual(value,1)
''',1)
        self.assertEqual(unit['failed'],['test_contract.py::Cases::test_native'])
        self.assertEqual(unit['passed'],[])
        # Unsupported retries must not collapse into the final passing attempt.
        sys.path.insert(0,str(SCRIPTS))
        try:
            spec=importlib.util.spec_from_file_location('reference_report',SCRIPTS/'pytest_report.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        for invalid in ('duplicate','rerun','unknown-phase'):
            adapter=module.Reports();node='test_contract.py::test_param[1]'
            adapter.collected={node}
            events=[dict(event) for event in phases['events'][node]]
            event=dict(events[1])
            if invalid=='rerun':event['outcome']='rerun'
            if invalid=='unknown-phase':event['when']='retry'
            adapter.events[node]=[event,*events]
            outcomes,incomplete=adapter.result()
            self.assertEqual(outcomes['passed'],[],invalid)
            self.assertEqual(incomplete,[node],invalid)

    def test_fingerprints_bind_required_inputs_runtime_and_candidate(self):
        (self.project/'.gitignore').write_text('ignored/\n')
        (self.project/'source.py').write_text('VALUE=1\n')
        self.git('init','-q');self.git('add','.');self.git('commit','-qm','Fixture')
        required=self.project/'ignored';required.mkdir();fixture=required/'data';fixture.write_text('first')
        external=self.root/'external';external.write_text('outside')
        link=self.project/'linked';link.symlink_to(external)
        config=self.evidence/'inputs.json'
        value={'root':str(self.project),'python':sys.executable,'dependencies':['pytest'],
               'inputs':['source.py','ignored','linked'],'environment':['FC_HELPER_INPUT']}
        config.write_text(json.dumps(value))
        def fingerprint():return self.run_script('fingerprint.py','gate','--config',config).stdout
        first=fingerprint();self.assertEqual(first,fingerprint())
        git_candidate=self.run_script('fingerprint.py','candidate','--root',self.project).stdout
        # Default candidate identity agrees with the installed controller card.
        code='import sys;from pathlib import Path;sys.path.insert(0,'+repr(str(PRODUCT/'status-card'))+');import maintainer;print(maintainer.candidate(Path('+repr(str(self.project))+')))'
        actual=subprocess.check_output([sys.executable,'-B','-c',code],cwd=self.project,env=self.env)
        self.assertEqual(git_candidate,actual)
        configured=self.run_script('fingerprint.py','candidate','--config',config).stdout
        fixture.write_text('changed ignored input');self.assertNotEqual(first,fingerprint())
        before_link=self.run_script('fingerprint.py','candidate','--config',config).stdout
        external.write_text('changed target without changing link text')
        self.assertNotEqual(before_link,self.run_script('fingerprint.py','candidate','--config',config).stdout)
        external.unlink();self.run_script('fingerprint.py','gate','--config',config,expected=2)
        external.write_text('restored')
        changed=self.run_script('fingerprint.py','gate','--config',config,env=dict(self.env,FC_HELPER_INPUT='different')).stdout
        self.assertNotEqual(changed,fingerprint())
        value['dependencies']=['flightcheck-nonexistent-distribution'];config.write_text(json.dumps(value))
        self.run_script('fingerprint.py','gate','--config',config,expected=2)
        dependency=self.root/'dependencies';dependency.mkdir()
        package=dependency/'fixturedep.py';package.write_text('VALUE=1\n')
        metadata=dependency/'flightcheck_fixture_dep-1.0.dist-info';metadata.mkdir()
        (metadata/'METADATA').write_text('Metadata-Version: 2.1\nName: flightcheck-fixture-dep\nVersion: 1.0\n')
        (metadata/'RECORD').write_text('fixturedep.py,,\nflightcheck_fixture_dep-1.0.dist-info/METADATA,,\nflightcheck_fixture_dep-1.0.dist-info/RECORD,,\n')
        value['dependencies']=['flightcheck-fixture-dep'];config.write_text(json.dumps(value))
        env=dict(self.env,PYTHONPATH=str(dependency)+os.pathsep+self.env.get('PYTHONPATH',''))
        dependency_before=self.run_script('fingerprint.py','gate','--config',config,env=env).stdout
        package.write_text('VALUE=2\n')
        self.assertNotEqual(dependency_before,self.run_script('fingerprint.py','gate','--config',config,env=env).stdout)
        value['python']=str(self.root/'missing-python');config.write_text(json.dumps(value))
        self.run_script('fingerprint.py','gate','--config',config,expected=2)
        (self.project/'local-tool.py').write_text('print(1)\n')
        self.assertNotEqual(git_candidate,self.run_script('fingerprint.py','candidate','--root',self.project).stdout)

    def test_shared_contract_tests_use_configured_scripts_root(self):
        scripts=self.root/'configured scripts';shutil.copytree(SCRIPTS,scripts)
        tests=self.root/'portable tests';shutil.copytree(PRODUCT/'examples/existing-project/tests',tests)
        env=dict(self.env,FLIGHTCHECK_SCRIPTS_ROOT=str(scripts))
        env.pop('FLIGHTCHECK_PRODUCT_ROOT',None)
        result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(tests),'-v'],cwd=self.project,
                              env=env,capture_output=True,text=True,timeout=150)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Ran 56 tests',result.stderr)
        self.assertFalse((scripts.parent/'AGENTS.md').exists())
        self.assertFalse((scripts.parent/'CONTRIBUTING.md').exists())

    def test_controller_capture_retains_complete_original_bytes(self):
        variants=[b'{"candidate":"synthetic","role":"EVIDENCE"}\r\n',b'{\r\n "candidate": "partial",\xff',b'```json\n{}\n```\n',b'Note before JSON\n{}']
        for raw in variants:
            value=json.loads(self.run_script('capture_review.py','--evidence-dir',self.evidence,'--validate',data=raw,expected=2).stdout)
            path=Path(value['path'])
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(value['sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(json.loads(path.with_suffix('.json').read_text())['bytes'],len(raw))
            self.assertEqual(value['validation'],'invalid')
            self.assertEqual((self.evidence/'responses'/(value['sha256']+'.json')).read_bytes(),raw)
        original=self.root/'native-final.txt'
        raw=b' \r\n{"candidate":"synthetic-unit","role":"EVIDENCE","verdict":"REVISE","coverage":"Synthetic structural fixture, not final review","challenge":"","criteria":[],"findings":[],"test_requests":[]}\r\n'
        original.write_bytes(raw)
        valid=json.loads(self.run_script('capture_review.py','--evidence-dir',self.evidence,'--input',original,'--validate').stdout)
        self.assertEqual(valid['validation'],'valid-structure')
        self.assertEqual(Path(valid['path']).read_bytes(),raw)
        self.assertEqual(original.read_bytes(),raw)
        missing=json.loads(self.run_script('capture_review.py','--evidence-dir',self.evidence,'--input',self.root/'missing',expected=2).stdout)
        self.assertFalse(missing['complete'])
        self.assertEqual(Path(missing['path']).read_bytes(),b'')
        self.assertEqual(missing['sha256'],hashlib.sha256(b'').hexdigest())
        # Real pipe interruption retains actual partial bytes and rejects completion.
        process=subprocess.Popen([sys.executable,'-B',str(SCRIPTS/'capture_review.py'),'--evidence-dir',str(self.evidence)],
                                 cwd=self.project,env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        raw=b'{"partial":\r\n'
        try:
            process.stdin.write(raw);process.stdin.flush()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if any(p.stat().st_size==len(raw) for p in (self.evidence/'captures').glob('*.bin')):break
                time.sleep(.02)
            else:self.fail('Capture did not retain the pipe bytes')
            process.send_signal(signal.SIGTERM)
            output,error=process.communicate(timeout=5)
            self.assertEqual(process.returncode,143,error)
            value=json.loads(output);self.assertFalse(value['complete'])
            self.assertEqual(Path(value['path']).read_bytes(),raw)
            self.assertEqual(value['sha256'],hashlib.sha256(raw).hexdigest())
        finally:
            if process.poll() is None:process.kill();process.wait()
        self.assertFalse((self.evidence/'review-obligations.json').exists())

    def test_first_flight_uses_supplied_helpers_and_safe_refresh(self):
        project=self.root/'first-flight';evidence=self.root/'first-evidence'
        example=PRODUCT/'examples/existing-project/examples/first-flight/prepare.py'
        result=subprocess.run([sys.executable,'-B',str(example),'--project',str(project),'--evidence',str(evidence),
                               '--python',sys.executable,'--default-branch','main','--nit-tracker','Private rehearsal notes'],
                              cwd=self.project,env=self.env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        info=json.loads(result.stdout);task_path=evidence/'task.json';task=json.loads(task_path.read_text())
        def handoff(mode,*args,expected=0):
            result=self.run_script('handoff.py',mode,'--task',task_path,'--evidence-dir',evidence,*args,expected=expected,cwd=project)
            return json.loads(result.stdout) if result.stdout.strip() else {}
        handoff('preflight');frozen=(evidence/'acceptance-contract.json').read_bytes()
        gate=task['gates'][0];q=gate['request']
        command=[sys.executable,'-B',str(SCRIPTS/'capture_check.py'),'--evidence-dir',str(evidence),'--candidate',task['candidate'],
                 '--gate',gate['id'],'--scope',q['scope'],'--owner','controller','--fingerprint-command',json.dumps(q['fingerprint_command']),
                 '--isolated-reports',*[x for name in q['artifacts'] for x in ('--artifact',name)],'--',*q['command']]
        run=subprocess.run(command,cwd=project,env=self.env,capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        current=evidence/json.loads((evidence/'gate-project-tests.json').read_text());old=evidence/task['case_controls']['existing-label']['receipt']
        before=json.loads(old.read_text());after=json.loads((current/'run.json').read_text())
        self.assertEqual(before['artifacts']['spec.json'],after['artifacts']['spec.json'])
        self.assertEqual(json.loads((current/'artifact-0').read_text())['passed'],[info['native_witness']])
        packet=handoff('review',expected=1)
        self.assertTrue(packet['behavior_evidence']['cases'][0]['verified'])
        self.assertIn('independent challenge plan',packet['blockers'])
        # Refresh cannot amend acceptance or erase obligations/expected outcomes.
        (project/'local-tool.py').write_text('print("candidate change")\n')
        candidate=self.run_script('fingerprint.py','candidate','--root',project).stdout.decode().strip()
        obligations=evidence/'review-obligations.json';obligations.write_text('{"requests":{},"findings":{}}\n');original=obligations.read_bytes()
        handoff('refresh','--candidate',candidate)
        refreshed=json.loads(task_path.read_text());self.assertEqual(refreshed,{**task,'candidate':candidate})
        self.assertEqual((evidence/'acceptance-contract.json').read_bytes(),frozen)
        self.assertEqual(obligations.read_bytes(),original)
        self.assertTrue(handoff('resume')['candidate_changed'])
        refreshed['acceptance'][0]['description']='silently changed';task_path.write_text(json.dumps(refreshed));saved=task_path.read_bytes()
        handoff('refresh','--candidate','another',expected=2)
        self.assertEqual(task_path.read_bytes(),saved)
        self.assertEqual((evidence/'acceptance-contract.json').read_bytes(),frozen)
