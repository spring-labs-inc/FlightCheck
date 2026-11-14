# A small adoption flight

This disposable example adds one real behavior: trim a text label and reject non-text input. The original product is an unimplemented stub. The same native unittest and runner fail against that stub and pass against the proposed product. This is a **specification** control for new behavior, not a claim that the stub once implemented it.

From the FlightCheck checkout:

```sh
python3 -B examples/existing-project/examples/evidence-bootstrap/prepare.py \
  --project /private/tmp/flightcheck-toy --evidence /private/tmp/flightcheck-toy-evidence
```

For an installed project, use `.flightcheck/examples/evidence-bootstrap/prepare.py`. Pick unused disposable paths. The command prints the actual shared script paths and original/new product identities. It prepares a private empty four-outcome baseline with its real digest, a behavior criterion, exact native test ID, and distinct `coverage.json`/`spec.json` artifacts before the first freeze. It does not run reviews or invent receipts.

Run `handoff.py preflight --task EVIDENCE/task.json --evidence-dir EVIDENCE` with the printed paths. Obtain a real independent scope-only challenge using `challenge-brief`; use `challenge-review --review PROPOSAL` for early discussion of its grounding. Register the actual agreed proposal using `challenges`, then bind its IDs to the exact native witnesses. Keep the proposal original; do not fabricate a reviewer response to make this example green.

The following controller recipe records the original failure and proposed implementation with identical test fixtures. Run it after preparation, replacing only the two paths:

```python
import json, shutil, subprocess
from pathlib import Path

project = Path('/private/tmp/flightcheck-toy')
evidence = Path('/private/tmp/flightcheck-toy-evidence')
task_file = evidence / 'task.json'
task = json.loads(task_file.read_text())
# Use the shared scripts path printed by prepare.py.
scripts = Path('/absolute/path/to/shared/scripts')
request = task['gates'][0]['request']
python = request['command'][0]

def record(gate, candidate, expected):
    args = [python, '-B', str(scripts / 'capture_check.py'),
            '--evidence-dir', str(evidence), '--candidate', candidate,
            '--gate', gate, '--scope', request['scope'], '--owner', 'controller',
            '--fingerprint-command', json.dumps(request['fingerprint_command']),
            '--isolated-reports', '--artifact', 'coverage.json', '--artifact', 'spec.json',
            '--', *request['command']]
    result = subprocess.run(args, cwd=project)
    assert result.returncode == expected
    # A gate pointer contains a check-* directory name, not a run.json object.
    folder = evidence / json.loads((evidence / f'gate-{gate}.json').read_text())
    return folder / 'run.json'

before = record('original-control', task['baseline_candidate'], 1)
shutil.copyfile(project / 'proposed/product.py', project / 'product.py')
import hashlib
task['candidate'] = task['saved_candidate'] = 'new-' + hashlib.sha256(
    (project / 'product.py').read_bytes()).hexdigest()
after = record('labels', task['candidate'], 0)
task['case_controls'] = {'label-contract': {
    'receipt': str(before.relative_to(evidence)), 'candidate': task['baseline_candidate'],
    'source': 'baseline', 'report': 'coverage.json', 'spec': 'spec.json'}}
task_file.write_text(json.dumps(task, indent=2) + '\n')
```

Inspect both native logs and coverage reports. The exact ID is `test_contract.LabelTests.test_normalization`. `spec.json` hashes the **unchanged test and runner overlay**, excluding the product; each recorder fingerprint separately binds the actual product path/bytes, overlay and Python runtime. The original stub also survives under private `EVIDENCE/original/product.py`. For later reproductions set `EXAMPLE_PRODUCT_ROOT` to that retained original directory; keep the same current test overlay and recorder fingerprint command. Never relabel the repaired product as the original baseline.

The recorder retains `check-*/run.json`, `output.log`, positional `artifact-0` and `artifact-1`, and invocation-local `reports/coverage.json` and `reports/spec.json`. Use the receipt's artifact-name mapping to find the positional files. A valid configuration and a passing native run do not replace independent challenges, qualified controls or final review: `handoff.py review` stays blocked until those obligations are met.

For an additive task, prepare the genuine new behavior and spec declaration before freezing. Adding a distinct required gate without changing existing acceptance/gate definitions is supported by a new preflight; the old contract is archived and the added gate remains pending until its real run. Changing acceptance, weakening a gate or changing the original baseline requires the actual owner's scope instruction, an explicit `--amend-contract` decision and retained contract history. Do not turn behavior into policy to avoid native witnesses. See the [workflow guide](../../docs/development-workflow.md#bootstrap-and-additive-flights).
