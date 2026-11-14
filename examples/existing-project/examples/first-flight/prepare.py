"""Prepare a disposable Python first flight using shipped evidence helpers."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

BASE = Path(__file__).resolve().parent
SCRIPTS = BASE.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
from capture_check import evidence_directory

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--project", type=Path, required=True)
parser.add_argument("--evidence", type=Path, required=True)
parser.add_argument("--python", required=True)
parser.add_argument("--default-branch", required=True)
parser.add_argument("--nit-tracker", required=True)
args = parser.parse_args()
if not Path(args.python).is_absolute() or not Path(args.python).is_file() or not args.nit_tracker.strip():
    parser.error("Choose an absolute interpreter and nonempty nit tracker")
subprocess.run(["git", "check-ref-format", "--branch", args.default_branch], check=True, stdout=subprocess.DEVNULL)
project = args.project.resolve()
project.mkdir(mode=0o700, parents=True, exist_ok=False)
evidence = evidence_directory(args.evidence, project, create=True)
shutil.copyfile(BASE.parent / "evidence-bootstrap/product.py", project / "product.py")
shutil.copyfile(BASE / "test_existing.py", project / "test_existing.py")
(project / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")

def git(*arguments):
    return subprocess.check_output(["git", "-c", "user.name=FlightCheck example", "-c", "user.email=example@example.invalid",
        "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *arguments], cwd=project)

git("init", "-q", "-b", args.default_branch)
git("add", ".")
git("commit", "-qm", "Disposable existing behavioral witness")
candidate = subprocess.check_output([args.python, "-B", str(SCRIPTS / "fingerprint.py"), "candidate", "--root", str(project)], text=True).strip()
config = evidence / "gate-inputs.json"
config.write_text(json.dumps({"root": str(project), "python": args.python, "dependencies": ["pytest"],
    "inputs": ["product.py", "test_existing.py", str(SCRIPTS / "pytest_report.py"), str(SCRIPTS / "evidence_inputs.py")],
    "environment": []}, indent=2) + "\n")
command = [args.python, "-B", str(SCRIPTS / "pytest_report.py"), "--spec", str(project / "test_existing.py"),
           "--spec", str(SCRIPTS / "pytest_report.py"), "--spec", str(SCRIPTS / "evidence_inputs.py"),
           "--", "-q", "-p", "no:cacheprovider", "test_existing.py"]
fingerprint = [args.python, "-B", str(SCRIPTS / "fingerprint.py"), "gate", "--config", str(config)]
request = {"command": command, "scope": "Existing label-normalization behavior", "summary": None,
           "fingerprint_command": fingerprint, "artifacts": ["coverage.json", "spec.json", "phases.json"], "isolated_reports": True}
record = [args.python, "-B", str(SCRIPTS / "capture_check.py"), "--evidence-dir", str(evidence),
          "--candidate", candidate, "--gate", "original-control", "--scope", request["scope"], "--owner", "controller",
          "--fingerprint-command", json.dumps(fingerprint), "--isolated-reports", "--artifact", "coverage.json",
          "--artifact", "spec.json", "--artifact", "phases.json", "--", *command]
result = subprocess.run(record, cwd=project, capture_output=True, text=True)
if result.returncode:
    parser.exit(2, "Existing native witness failed; actual baseline receipt retained:\n" + result.stdout + result.stderr)
folder = evidence / json.loads((evidence / "gate-original-control.json").read_text())
shutil.copyfile(folder / "artifact-0", evidence / "baseline.json")
identity = "test_existing.py::test_normalization"
case = {"id": "existing-label", "dimension": "Existing public behavior", "input": "Whitespace, empty and non-text labels",
        "observable": "Normalized result or exception", "expected": "Preserve existing normalization",
        "expectation": {"kind": "compatibility", "reference": "Existing witness in the original product"},
        "gate": "project-tests", "tests": [identity]}
task = {"scope": "Rehearse a real first flight preserving existing label behavior", "candidate": candidate,
        "saved_candidate": candidate, "baseline_candidate": candidate, "preview": None, "diff": "candidate.diff", "delivery": "Local disposable trial; no provider writes",
        "project_decisions": {"python": args.python, "default_branch": args.default_branch, "nit_tracker": args.nit_tracker},
        "gates": [{"id": "project-tests", "phase": "cheap", "owner": "controller", "request": request,
                   "coverage": {"artifact": "coverage.json", "spec": "spec.json", "baseline": "baseline.json",
                                "baseline_sha256": hashlib.sha256((evidence / "baseline.json").read_bytes()).hexdigest()}}],
        "acceptance": [{"id": "labels", "kind": "behavior", "description": "Preserve the existing label contract",
                        "proofs": [{"kind": "check", "gate": "project-tests", "tests": [identity],
                                    "assertion": "Native pytest checks normal, empty and invalid inputs"}], "cases": [case]}],
        "case_controls": {case["id"]: {"receipt": str((folder / "run.json").relative_to(evidence)), "candidate": candidate,
                                       "source": "baseline", "report": "coverage.json", "spec": "spec.json"}}}
archive = git("archive", "HEAD")
(evidence / "original-product.tar").write_bytes(archive)
observed_inputs = subprocess.check_output(fingerprint, cwd=project)
(evidence / "gate-inputs.manifest.json").write_bytes(observed_inputs)
(evidence / "provenance.json").write_text(json.dumps({"candidate": candidate,
    "git_head": git("rev-parse", "HEAD").decode().strip(), "git_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
    "original_archive_sha256": hashlib.sha256(archive).hexdigest(),
    "gate_manifest_sha256": hashlib.sha256(observed_inputs).hexdigest(), "baseline_receipt": str(folder / "run.json")}, indent=2) + "\n")
(evidence / "candidate.diff").write_text("Disposable first flight; retain your actual scoped diff here.\n")
(evidence / "task.json").write_text(json.dumps(task, indent=2) + "\n")
print(json.dumps({"project": str(project), "evidence": str(evidence), "scripts": str(SCRIPTS),
                  "candidate": candidate, "task": str(evidence / "task.json"), "baseline_receipt": str(folder / "run.json"),
                  "native_witness": identity, "next": "Preflight, independent scope-only challenge, actual fresh witness and separate real final review; no review has been fabricated."}, indent=2))
