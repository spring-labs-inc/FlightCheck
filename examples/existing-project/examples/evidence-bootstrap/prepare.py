"""Prepare a disposable new-behavior flight; never invent reviews or receipts."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

BASE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--project", type=Path, required=True)
parser.add_argument("--evidence", type=Path, required=True)
args = parser.parse_args()
project = args.project.resolve()
project.mkdir(mode=0o700, parents=True, exist_ok=False)
scripts = BASE.parent.parent / "scripts"
sys.path.insert(0, str(scripts))
from capture_check import evidence_directory

evidence = evidence_directory(args.evidence, project, create=True)
for name in ("run_gate.py", "test_contract.py"):
    shutil.copyfile(BASE / name, project / name)
shutil.copyfile(BASE / "original/product.py", project / "product.py")
(project / "proposed").mkdir()
shutil.copyfile(BASE / "product.py", project / "proposed/product.py")
(evidence / "original").mkdir(mode=0o700)
shutil.copyfile(BASE / "original/product.py", evidence / "original/product.py")
empty = {name: [] for name in ("passed", "skipped", "expected_failures", "failed")}
(evidence / "baseline.json").write_text(json.dumps(empty) + "\n")
original = "original-" + hashlib.sha256((project / "product.py").read_bytes()).hexdigest()
new = "new-" + hashlib.sha256((project / "proposed/product.py").read_bytes()).hexdigest()
identity = "test_contract.LabelTests.test_normalization"
request = {"command": [sys.executable, "-B", str(project / "run_gate.py"), "run"],
           "scope": "Trim label whitespace and reject non-text labels", "summary": None,
           "fingerprint_command": [sys.executable, "-B", str(project / "run_gate.py"), "fingerprint"],
           "artifacts": ["coverage.json", "spec.json"], "isolated_reports": True}
case = {"id": "label-contract", "dimension": "New input contract", "input": "Whitespace, empty text and non-text",
        "observable": "Returned label or exception", "expected": "Trim text; reject non-text",
        "expectation": {"kind": "specification", "reference": "Owner's new label-normalization requirement"},
        "gate": "labels", "tests": [identity]}
task = {"scope": "Add label normalization to a new project", "candidate": original, "saved_candidate": original,
        "baseline_candidate": original, "preview": None, "diff": "candidate.diff", "delivery": "Disposable local example only",
        "gates": [{"id": "labels", "phase": "cheap", "request": request,
                   "coverage": {"artifact": "coverage.json", "spec": "spec.json", "baseline": "baseline.json",
                                "baseline_sha256": hashlib.sha256((evidence / "baseline.json").read_bytes()).hexdigest()}}],
        "acceptance": [{"id": "labels", "kind": "behavior", "description": "Normalize labels under the new contract",
                        "proofs": [{"kind": "check", "gate": "labels", "tests": [identity],
                                    "assertion": "Native unittest asserts trimmed, empty and invalid input results"}], "cases": [case]}]}
(evidence / "candidate.diff").write_text("Proposed label normalization; keep the real diff with your task.\n")
(evidence / "task.json").write_text(json.dumps(task, indent=2) + "\n")
print(json.dumps({"task": str(evidence / "task.json"), "scripts": str(scripts),
                  "project": str(project), "original_candidate": original, "new_candidate": new,
                  "original_product": str(evidence / "original"), "native_test": identity,
                  "next": "Run preflight, obtain an independent scope-only challenge, then record the original control before copying proposed/product.py over product.py. No reviews or proofs have been fabricated."}, indent=2))
