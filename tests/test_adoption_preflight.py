"""Exercise adoption configuration through public CLI and actual native controls."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import test_workflow_contract as fixture

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))
SCRIPTS = PRODUCT / "examples/existing-project/scripts"


class AdoptionPreflightTests(unittest.TestCase):
    setUp = fixture.FlightFixture.setUp
    ctl = fixture.FlightFixture.ctl
    sha = staticmethod(fixture.FlightFixture.sha)
    record = fixture.FlightFixture.record
    case = fixture.FlightFixture.case
    proposal = fixture.FlightFixture.proposal
    submit_plan = fixture.FlightFixture.submit_plan
    native_review = fixture.FlightFixture.native_review

    def call(self, mode, *extra):
        self.manifest.write_text(json.dumps(self.task))
        return subprocess.run([sys.executable, "-B", str(SCRIPTS / "handoff.py"), mode,
                               "--task", str(self.manifest), "--evidence-dir", str(self.evidence), *extra],
                              cwd=self.checkout, capture_output=True, text=True, timeout=20)

    def fresh_behavior(self):
        (self.evidence / "acceptance-contract.json").unlink(missing_ok=True)
        self.task["acceptance"][0].update(kind="behavior", cases=[self.case(kind="specification")])
        self.gate["coverage"]["spec"] = "fixture.json"

    def test_preflight_rejects_bad_baselines_without_freezing(self):
        saved = copy.deepcopy(self.task)
        outside = self.root / "external.json"
        outside.write_text(json.dumps({name: [] for name in fixture.OUTCOMES}))
        link = self.evidence / "escape.json"
        link.symlink_to(outside)
        variants = [("missing.json", None, None, "baseline"),
                    ("escape.json", self.sha(outside), None, "baseline"),
                    (str(outside), self.sha(outside), None, "baseline"),
                    ("baseline.json", "", None, "baseline_sha256"),
                    ("baseline.json", "0" * 64, None, "baseline_sha256"),
                    ("bad.json", None, {"passed": []}, "baseline"),
                    ("bad.json", None, {**{k: [] for k in fixture.OUTCOMES}, "passed": ["a", "a"]}, "baseline.passed"),
                    ("bad.json", None, {**{k: [] for k in fixture.OUTCOMES}, "passed": ["a"], "failed": ["a"]}, "baseline.failed"),
                    ("bad.json", None, {**{k: [] for k in fixture.OUTCOMES}, "passed": "a"}, "baseline.passed")]
        for name, digest, content, field in variants:
            with self.subTest(name=name, field=field, content=content):
                self.task = copy.deepcopy(saved)
                (self.evidence / "acceptance-contract.json").unlink(missing_ok=True)
                if content is not None:
                    (self.evidence / name).write_text(json.dumps(content))
                    digest = self.sha(self.evidence / name)
                self.task["bootstrap"] = True
                self.task["gates"][0]["coverage"].update(baseline=name, baseline_sha256=digest or "")
                result = self.call("preflight")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("task.gates[0].coverage." + field, result.stderr)
                self.assertIn("development-workflow.md#", result.stderr)
                self.assertFalse((self.evidence / "acceptance-contract.json").exists())
        self.task = saved
        self.assertEqual(self.call("preflight").returncode, 0)
        original = (self.evidence / "acceptance-contract.json").read_bytes()
        self.task["gates"][0]["coverage"]["baseline_sha256"] = ""
        self.assertEqual(self.call("preflight").returncode, 2)
        self.assertEqual((self.evidence / "acceptance-contract.json").read_bytes(), original)

    def test_case_and_artifact_configuration_checked_before_runs(self):
        self.fresh_behavior()
        original = copy.deepcopy(self.task)
        def missing_spec(task):
            task['gates'][0]['request']['artifacts'] = ['coverage.json']
            task['gates'][0]['coverage'].pop('spec')
        variants = [(lambda t: t['acceptance'][0]['cases'][0].update(gate='unknown'), 'cases[0].gate'),
                    (lambda t: t['gates'][0]['request'].update(isolated_reports=False), 'request.isolated_reports'),
                    (lambda t: t['gates'][0]['coverage'].update(artifact='unretained.json'), 'coverage.artifact'),
                    (lambda t: t['gates'][0]['coverage'].update(spec='coverage.json'), 'coverage.spec'),
                    (missing_spec, 'coverage.spec'),
                    (lambda t: t['gates'][0]['request'].update(artifacts=['coverage.json','fixture.json','../escape']), 'request.artifacts[2]'),
                    (lambda t: t['acceptance'][0]['cases'][0].update(tests='case.a'), 'cases[0].tests'),
                    (lambda t: t.update(challenge_checks={'later':{'gate':'unknown','tests':['case.a']}}), 'challenge_checks.later.gate')]
        for edit, field in variants:
            with self.subTest(field=field):
                self.task = copy.deepcopy(original)
                edit(self.task)
                result = self.call('preflight')
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(field, result.stderr)
                self.assertFalse((self.evidence / 'acceptance-contract.json').exists())
        self.task = original
        self.assertEqual(self.call('preflight').returncode, 0)
        pending = self.ctl('review', 1)
        self.assertFalse(pending['ready_for_review'])
        self.assertEqual(pending['checks'][0]['status'], 'missing')
        # Missing proof is pending. Real run arrival verifies the gate, never
        # silently supplies an independent proposal or qualification control.
        self.record()
        after = self.ctl('review', 1)
        self.assertEqual(after['checks'][0]['status'], 'passed')
        self.assertIn('independent challenge plan', after['blockers'])
        self.assertIn('acceptance-case:first-case', after['blockers'])

    def test_malformed_binding_containers_preserve_contracts(self):
        self.fresh_behavior()
        original = copy.deepcopy(self.task)
        variants = [
            (lambda t: t.update(challenge_checks=None), 'task.challenge_checks'),
            (lambda t: t.update(challenge_checks=[]), 'task.challenge_checks'),
            (lambda t: t.update(case_controls=None), 'task.case_controls'),
            (lambda t: t.update(case_controls=[]), 'task.case_controls'),
            (lambda t: t['acceptance'][0]['cases'][0].update(id=[]), 'task.acceptance[0].cases[0].id'),
            (lambda t: t['acceptance'][0]['cases'][0].update(gate={}), 'task.acceptance[0].cases[0].gate'),
            (lambda t: t['acceptance'][0]['proofs'][0].update(gate={}), 'task.acceptance[0].proofs[0].gate'),
            (lambda t: t['acceptance'][0].update(cases=None), 'task.acceptance[0].cases'),
        ]
        for established in (False, True):
            for edit, field in variants:
                with self.subTest(established=established, field=field):
                    self.task = copy.deepcopy(original)
                    contract = self.evidence/'acceptance-contract.json'
                    contract.unlink(missing_ok=True)
                    before = None
                    if established:
                        self.assertEqual(self.call('preflight').returncode, 0)
                        before = contract.read_bytes()
                    edit(self.task)
                    result = self.call('preflight')
                    self.assertEqual(result.returncode, 2, result.stdout+result.stderr)
                    self.assertIn(field, result.stderr)
                    self.assertIn('development-workflow.md#', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    if established:
                        self.assertEqual(contract.read_bytes(), before)
                    else:
                        self.assertFalse(contract.exists())
        self.task = original
        self.assertEqual(self.call('preflight').returncode, 0)

    def test_published_schemas_diagnostics_and_retained_responses(self):
        for kind in ('challenge', 'review', 'coverage'):
            result = subprocess.run([sys.executable, '-B', str(SCRIPTS/'handoff.py'), 'schema', '--kind', kind],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            contract = json.loads(result.stdout)
            self.assertIn('properties', contract)
            self.assertTrue(contract['$schema'].startswith('https://json-schema.org/'))
        brief = self.ctl('brief')
        self.assertEqual(brief['schemas']['review']['properties']['test_requests']['type'], 'array')
        self.assertEqual(brief['examples']['challenge']['cases'][0]['expectation']['kind'], 'specification')
        proposal = self.proposal()
        proposal['cases'][0].pop('expected')
        review = json.loads(self.native_review().read_text())
        review['test_requests'] = [{'id':'bad','criterion':'operation','input':'x','expected':[], 'reason':'x'}]
        for mode, value, field in [('challenges', proposal, 'challenge.cases[0].expected'),
                                   ('requests', review, 'review.test_requests[0].expected'),
                                   ('verdict', {'candidate':'A'}, 'review.role')]:
            path = self.root/'raw-response.json'
            raw = json.dumps(value, indent=3).encode() + b'\n'
            path.write_bytes(raw)
            result = self.call(mode, '--review', str(path))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(field, result.stderr)
            self.assertIn('development-workflow.md#', result.stderr)
            retained = self.evidence/'responses'/(hashlib.sha256(raw).hexdigest()+'.json')
            self.assertEqual(retained.read_bytes(), raw)
            self.assertEqual(path.read_bytes(), raw)
        raw = b'{ not JSON\n'
        path.write_bytes(raw)
        result = self.call('requests', '--review', str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn('review', result.stderr)
        self.assertEqual((self.evidence/'responses'/(hashlib.sha256(raw).hexdigest()+'.json')).read_bytes(), raw)
        self.assertFalse((self.evidence/'review-obligations.json').exists())
        # Legacy callers may explicitly send null for an unspecified phase.
        self.ctl('requests', review=self.native_review(phase=None))

    def test_early_proposal_review_cannot_discard_registered_obligations(self):
        proposal = self.proposal()
        proposal['cases'][0]['expected'] = 'An ungrounded speculative expectation to discuss'
        path = self.root/'proposal.json'
        path.write_text(json.dumps(proposal))
        early = self.ctl('challenge-review', review=path)
        self.assertEqual(early['status'], 'proposal-only')
        self.assertEqual(early['registered_cases'], [])
        self.assertIn('not semantic correctness', early['instructions'])
        self.assertFalse((self.evidence/'challenge-plan.json').exists())
        # Structural success never establishes a product requirement or proves it.
        self.submit_plan(proposal)
        before = (self.evidence/'challenge-plan.json').read_bytes()
        proposal['cases'][0]['expected'] = 'Request removal by relabeling the registered challenge'
        path.write_text(json.dumps(proposal))
        revised = self.ctl('challenge-review', review=path)
        self.assertIn('independent-case', revised['registered_cases'])
        self.assertIn('qualified counterevidence', revised['instructions'])
        self.assertEqual((self.evidence/'challenge-plan.json').read_bytes(), before)
        self.assertIn('challenge-case:independent-case', self.ctl('review',1)['blockers'])
        self.assertEqual(self.call('challenges','--review',str(path)).returncode, 2)
        self.assertEqual((self.evidence/'challenge-plan.json').read_bytes(), before)
        # A falsely optimistic full review cannot clear the binding obligation.
        self.assertFalse(self.ctl('verdict',1,review=self.native_review())['ready_for_approval'])

    def test_bootstrap_and_additive_example_use_exact_native_controls(self):
        example = PRODUCT/'examples/existing-project/examples/evidence-bootstrap'
        project = self.root/'new-project'
        evidence = self.root/'new-evidence'
        prepared = subprocess.run([sys.executable,'-B',str(example/'prepare.py'),'--project',str(project),
                                   '--evidence',str(evidence)],capture_output=True,text=True,timeout=15)
        self.assertEqual(prepared.returncode,0,prepared.stdout+prepared.stderr)
        info=json.loads(prepared.stdout)
        task=json.loads((evidence/'task.json').read_text())
        def ctl(mode, expected=0):
            (evidence/'task.json').write_text(json.dumps(task))
            result=subprocess.run([sys.executable,'-B',str(SCRIPTS/'handoff.py'),mode,'--task',str(evidence/'task.json'),
                                   '--evidence-dir',str(evidence)],cwd=project,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
            return json.loads(result.stdout)
        def record(gate, candidate, expected):
            q=task['gates'][0]['request']
            args=[sys.executable,'-B',str(SCRIPTS/'capture_check.py'),'--evidence-dir',str(evidence),'--candidate',candidate,
                  '--gate',gate,'--scope',q['scope'],'--owner','controller','--fingerprint-command',json.dumps(q['fingerprint_command']),
                  '--isolated-reports','--artifact','coverage.json','--artifact','spec.json','--',*q['command']]
            result=subprocess.run(args,cwd=project,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
            folder=evidence/json.loads((evidence/('gate-'+gate+'.json')).read_text())
            return folder,json.loads((folder/'run.json').read_text())
        ctl('preflight')
        original, before=record('original-control', info['original_candidate'], 1)
        self.assertIn(info['native_test'],json.loads((original/'artifact-0').read_text())['failed'])
        shutil.copyfile(project/'proposed/product.py',project/'product.py')
        task['candidate']=task['saved_candidate']=info['new_candidate']
        current, after=record('labels',info['new_candidate'],0)
        self.assertEqual(before['artifacts']['spec.json'],after['artifacts']['spec.json'])
        self.assertNotEqual(before['inputs_before'],after['inputs_before'])
        task['case_controls']={'label-contract':{'receipt':str((original/'run.json').relative_to(evidence)),
                'candidate':info['original_candidate'],'source':'baseline','report':'coverage.json','spec':'spec.json'}}
        self.assertIn(info['native_test'],json.loads((current/'artifact-0').read_text())['passed'])
        packet=ctl('review',1)
        cases=packet['behavior_evidence']['cases']
        self.assertTrue(cases[0]['verified'],cases)
        self.assertIn('independent challenge plan',packet['blockers'])
        # A genuinely additional gate preserves earlier acceptance/gates and
        # requires its own run; it does not need a scope-weakening amendment.
        extra=copy.deepcopy(task['gates'][0]);extra['id']='additional-check'
        task['gates'].append(extra)
        ctl('preflight')
        self.assertEqual(ctl('review',1)['checks'][1]['status'],'missing')
        contract=json.loads((evidence/'acceptance-contract.json').read_text())
        self.assertEqual(contract['baseline_candidate'],info['original_candidate'])
        self.assertEqual(len(contract['required_gates']),2)
