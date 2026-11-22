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

def reviewer_pointer(wrapper, source):
    target = os.path.relpath(source, wrapper.parent)
    return ('Read and follow the [canonical reviewer instructions](' + target + '). '
            'Apply its developer_instructions and complete native response schema. '
            'This discovery adapter adds no permissions, hooks or separate review policy. '
            'Review read-only; never execute controller commands.')


def source_layout_errors(root):
    """Bound source examples and adapters without copying production policy."""
    allowed_examples = {
        'existing-project/.agents/skills/develop-change/SKILL.md',
        'existing-project/.claude/agents/workflow-code-reviewer.md',
        'existing-project/.claude/agents/workflow-evidence-reviewer.md',
        'existing-project/.claude/skills/develop-change/SKILL.md',
        'existing-project/.codex/agents/workflow-code-reviewer.toml',
        'existing-project/.codex/agents/workflow-evidence-reviewer.toml',
        'existing-project/.codex/hooks.json',
        'existing-project/.codex/rules/github-reads.rules',
        'existing-project/AGENTS.md', 'existing-project/CLAUDE.md',
        'existing-project/README.md', 'existing-project/docs/first-flight.md',
        'existing-project/examples/evidence-bootstrap/README.md',
        'existing-project/examples/evidence-bootstrap/original/product.py',
        'existing-project/examples/evidence-bootstrap/prepare.py',
        'existing-project/examples/evidence-bootstrap/product.py',
        'existing-project/examples/evidence-bootstrap/run_gate.py',
        'existing-project/examples/evidence-bootstrap/test_contract.py',
        'existing-project/examples/first-flight/prepare.py',
        'existing-project/examples/first-flight/test_existing.py',
        'existing-project/requirements.dev.txt',
    }
    errors = []
    # Adding a genuine example requires declaring its purpose here. Renaming a
    # competing production document/script must not evade the source boundary.
    for file in sorted((root/'examples').rglob('*')):
        if file.is_file() and file.suffix in ('.md', '.toml', '.py'):
            if str(file.relative_to(root/'examples')) not in allowed_examples:
                errors.append('Competing workflow source: ' + str(file.relative_to(root)))
    def target(file, value, expected):
        if (file.parent/value).resolve() != expected.resolve() or not expected.is_file():
            errors.append('Adapter target is not canonical: ' + str(file.relative_to(root)))
    for base in (root, root/'examples/existing-project'):
        for role in ('code', 'evidence'):
            file = base/f'.claude/agents/workflow-{role}-reviewer.md'
            text = file.read_text(); body = text.split('---\n', 2)[-1].strip()
            expected = root/f'workflow/reviewers/workflow-{role}-reviewer.toml'
            match = re.search(r'\[canonical reviewer instructions\]\(([^)]+)\)', body)
            if not match:
                errors.append('Missing canonical reviewer target: ' + str(file.relative_to(root)))
            else:
                target(file, match.group(1), expected)
            if body != reviewer_pointer(file, expected):
                errors.append('Competing policy in discovery wrapper: ' + str(file.relative_to(root)))
        file = base/'.claude/skills/develop-change/SKILL.md'
        body = file.read_text().split('---\n', 2)[-1].strip()
        expected = root/'workflow/skills/develop-change/SKILL.md'
        path = os.path.relpath(expected, file.parent)
        preface = ('Root AGENTS.md automatically selects the workflow for implementation; ordinary questions and reviews use their normal entry points.'
                   if base == root else 'Select or resume a bounded flight explicitly; ordinary questions and reviews use their normal entry points.')
        pointer = (preface + '\n\nRead and follow the [shared develop-change procedure](' + path + '). '
                   'Its linked workflow and status instructions are authoritative. This adapter adds no permissions, hooks, delivery grant or separate policy. '
                   'Use the complete installer in `setup/README.md` for another repository; this source wrapper alone is not an installation.')
        if body != pointer:
            errors.append('Competing policy in skill adapter: ' + str(file.relative_to(root)))
        match = re.search(r'\[shared develop-change procedure\]\(([^)]+)\)', body)
        if not match:
            errors.append('Missing canonical skill target: ' + str(file.relative_to(root)))
        else:
            target(file, match.group(1), expected)
    base = root/'examples/existing-project'
    for role in ('code', 'evidence'):
        file = base/f'.codex/agents/workflow-{role}-reviewer.toml'
        match = re.search(r'developer_instructions = (""".*""")\s*$', file.read_text(), re.S)
        if not match:
            errors.append('Missing reviewer delegation: ' + str(file.relative_to(root))); continue
        body = ast.literal_eval(match.group(1)).strip()
        expected = root/f'workflow/reviewers/workflow-{role}-reviewer.toml'
        path = os.path.relpath(expected, file.parent)
        pointer = ('Read and follow ' + path + ' and its developer_instructions. Return its complete native response schema. '
                   'This discovery adapter adds no permissions, hooks or separate policy. Never execute controller commands.')
        if body != pointer:
            errors.append('Competing policy or wrong target in adapter: ' + str(file.relative_to(root)))
        actual = re.search(r'^Read and follow (\S+) and its developer_instructions\.', body)
        if not actual:
            errors.append('Missing canonical reviewer target: ' + str(file.relative_to(root)))
        else:
            target(file, actual.group(1), expected)
    file = base/'.agents/skills/develop-change/SKILL.md'
    expected = root/'workflow/skills/develop-change/SKILL.md'
    path = os.path.relpath(expected, file.parent)
    body = file.read_text().split('---\n', 2)[-1].strip()
    pointer = ('Read the [shared develop-change procedure](' + path + '). This source-layout example delegates all policy to the canonical workflow. '
               'Install the complete adapter into another repository using `setup/README.md`; preserve its existing policy.')
    if body != pointer:
        errors.append('Competing policy or wrong target in adapter: ' + str(file.relative_to(root)))
    actual = re.search(r'\[shared develop-change procedure\]\(([^)]+)\)', body)
    if not actual:
        errors.append('Missing canonical skill target: ' + str(file.relative_to(root)))
    else:
        target(file, actual.group(1), expected)
    return errors


class ClaudeSupportTests(unittest.TestCase):
    def test_source_layout_keeps_examples_and_all_adapters_thin(self):
        errors=source_layout_errors(ROOT)
        self.assertFalse(errors,'\n'.join(errors))

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
                self.assertEqual(actual.strip(),reviewer_pointer(wrapper,source),'Competing policy in discovery wrapper: '+str(wrapper.relative_to(ROOT)))
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
