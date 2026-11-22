"""Check adapter file contracts without claiming native Claude qualification."""

import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(os.environ.get('FLIGHTCHECK_PRODUCT_ROOT', Path(__file__).resolve().parents[1]))


class ClaudeSupportTests(unittest.TestCase):
    def test_entry_points_keep_maintainer_and_adopter_routing(self):
        self.assertEqual((ROOT/'CLAUDE.md').read_text().splitlines()[0], '@AGENTS.md')
        self.assertIn('Every implementation task', (ROOT/'AGENTS.md').read_text())
        workflow=(ROOT/'workflow/docs/development-workflow.md').read_text()
        self.assertNotIn('separate read-only Codex session', workflow)
        self.assertIn('separate read-only session in the selected client', workflow)
        for base in (ROOT, ROOT/'examples/existing-project'):
            wrapper=base/'.claude/skills/develop-change/SKILL.md'
            text=wrapper.read_text()
            self.assertIn('disable-model-invocation: true', text)
            target=re.search(r'\[shared develop-change procedure\]\(([^)]+)\)', text).group(1)
            self.assertEqual((wrapper.parent/target).resolve(), (ROOT/'workflow/skills/develop-change/SKILL.md').resolve())
            self.assertNotIn('allowed-tools:', text)
            self.assertNotIn('hooks:', text)
        self.assertIn('automatically selects', (ROOT/'.claude/skills/develop-change/SKILL.md').read_text())
        self.assertIn('explicitly', (ROOT/'examples/existing-project/.claude/skills/develop-change/SKILL.md').read_text())
        self.assertEqual((ROOT/'examples/existing-project/CLAUDE.md').read_text(), '@AGENTS.md\n')
        # The installed adapter must resolve inside an adopter, after the source
        # wrapper's directory layout has gone away.
        spec=importlib.util.spec_from_file_location('claude_install',ROOT/'setup/install.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        shared=ROOT/'workflow/skills/develop-change/SKILL.md'
        installed=installer.render(shared.read_bytes(),str(shared),'.claude/skills/develop-change/SKILL.md',{'activation':'opt-in'}).decode()
        self.assertIn('disable-model-invocation: true',installed)
        target=re.search(r'\[project workflow\]\(([^)]+)\)',installed).group(1)
        with tempfile.TemporaryDirectory() as temporary:
            project=Path(temporary);wrapper=project/'.claude/skills/develop-change/SKILL.md';wrapper.parent.mkdir(parents=True)
            guide=project/'.flightcheck/docs/development-workflow.md';guide.parent.mkdir(parents=True);guide.write_text('Adopter workflow\n')
            self.assertEqual((wrapper.parent/target).resolve(),guide.resolve())
            self.assertTrue((wrapper.parent/target).is_file())

    def test_reviewer_adapters_preserve_canonical_policy_and_tool_boundary(self):
        spec=importlib.util.spec_from_file_location('claude_policy_install',ROOT/'setup/install.py')
        installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
        for role in ('code','evidence'):
            source=ROOT/f'workflow/reviewers/workflow-{role}-reviewer.toml'
            canonical=source.read_text()
            body=ast.literal_eval(re.search(r'developer_instructions = (""".*""")\s*$', canonical, re.S).group(1)).strip()
            name=ast.literal_eval(re.search(r'^name = (".*")$',canonical,re.M).group(1))
            for required in ('Review read-only.', 'Do not edit, run tests, start services, access secrets',
                             'hooks must be disabled', 'Report candidate identity', 'native JSON'):
                self.assertIn(required,body)
            for base in (ROOT, ROOT/'examples/existing-project'):
                wrapper=base/f'.claude/agents/workflow-{role}-reviewer.md'
                text=wrapper.read_text();header, actual=text.split('---\n',2)[1:]
                self.assertIn('name: '+json.dumps(name),header)
                self.assertEqual(re.search(r'^tools: (.*)$',header,re.M).group(1),'Read, Grep, Glob')
                self.assertNotIn('hooks:',header);self.assertNotIn('model:',header)
                target=re.search(r'\[canonical reviewer instructions\]\(([^)]+)\)',actual).group(1)
                self.assertEqual((wrapper.parent/target).resolve(),source.resolve())
                self.assertNotIn(body,actual,'Discovery wrappers must not duplicate the production policy')
            expected=body.replace('workflow/docs/development-workflow.md','.flightcheck/docs/development-workflow.md')
            codex=installer.render(source.read_bytes(),str(source),f'.codex/agents/workflow-{role}-reviewer.toml',{'activation':'opt-in'}).decode()
            self.assertEqual(ast.literal_eval(re.search(r'developer_instructions = (""".*""")\s*$',codex,re.S).group(1)).strip(),expected)
            rendered=installer.render(source.read_bytes(),str(source),f'.claude/agents/workflow-{role}-reviewer.md',{'activation':'opt-in'}).decode()
            header,actual=rendered.split('---\n',2)[1:]
            self.assertEqual(re.search(r'^tools: (.*)$',header,re.M).group(1),'Read, Grep, Glob')
            self.assertNotIn('hooks:',header);self.assertNotIn('model:',header)
            self.assertEqual(actual.strip(),expected+'\n\nReturn the native JSON object as your entire final message. The controller retains the original response; do not write it yourself.')

    def test_trial_handoff_preserves_pending_native_requirements(self):
        # The committed status contract must never turn portable checks into a
        # Claude approval. These artifacts are validated independently by CODE/EVIDENCE.
        report=json.loads((ROOT/'docs/claude-trial-status.json').read_text())
        self.assertEqual(report['schema'],1)
        self.assertEqual(set(report['native_requirements']),{'discovery','tui_status','review_boundary','real_flight','repair_resume','failure_controls','accepted_report'})
        for entry in report['native_requirements'].values():
            self.assertIn(entry['state'],('pending','blocked','verified'))
            self.assertTrue(entry['evidence'] or entry['state']!='verified')
        if report['qualification']!='verified':
            self.assertTrue(any(x['state']!='verified' for x in report['native_requirements'].values()))
        else:
            self.assertTrue(all(x['state']=='verified' for x in report['native_requirements'].values()))
            self.assertTrue(report['claude_version'] and report['accepted_report'])
        guide=(ROOT/'setup/README.md').read_text()
        for reference in ('handoff.py refresh','next-action','--target final','capture_review.py','disable-model-invocation: true', 'BROKEN_WITNESS'):
            self.assertIn(reference,guide)
        for line in ('missing/inaccessible evidence','failed required check','stale candidate/verdict'):
            self.assertIn(line,guide)
        self.assertIn('managed hooks',guide)
        self.assertIn('browser rendering',guide)
        self.assertIn('current-candidate',guide)
