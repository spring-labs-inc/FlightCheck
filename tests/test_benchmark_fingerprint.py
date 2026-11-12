"""External benchmark inputs must invalidate real recorder/handoff reuse."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "examples/existing-project/scripts"
FINGERPRINT = ROOT / "benchmarks/fingerprint.py"


class BenchmarkFingerprintTests(unittest.TestCase):
    def test_binary_contents_cannot_shift_adjacent_file_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "a", root / "b"
            manifest = root / "inputs.json"
            manifest.write_text(json.dumps({"files": [str(first), str(second)], "trees": []}))
            command = [sys.executable, "-B", str(FINGERPRINT), str(manifest)]
            marker = b"\0" + str(second).encode() + b"\0"
            first.write_bytes(b"x" + marker + b"y")
            second.write_bytes(b"z")
            before = subprocess.check_output(command)
            first.write_bytes(b"x")
            second.write_bytes(b"y" + marker + b"z")
            self.assertNotEqual(before, subprocess.check_output(command))

    def test_external_mutations_and_deletions_cannot_reuse_a_qualification_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            checkout.mkdir()
            evidence = root / "evidence"
            evidence.mkdir(mode=0o700)
            source = root / "product"
            source.mkdir()
            source_file = source / "implementation.py"
            source_file.write_text("original product")
            files = [root / name for name in ["native.log", "binary", "baseline.json", "original-result.json"]]
            for path in files:
                path.write_text("original " + path.name)
            manifest = root / "inputs.json"
            manifest.write_text(json.dumps({"files": [str(p) for p in files],
                                            "trees": [{"path": str(source), "exclude": []}]}))
            probe = [sys.executable, "-B", str(FINGERPRINT), str(manifest)]
            command = [sys.executable, "-c", "print('qualification pass')"]
            request = {"command": command, "scope": "qualification", "summary": None,
                       "fingerprint_command": probe, "artifacts": []}
            task = {"candidate": "unchanged", "saved_candidate": "unchanged", "preview": None,
                    "gates": [{"id": "qualification", "request": request}], "diff": "candidate.diff",
                    "acceptance": [{"id": "behavior", "description": "Qualified external inputs",
                        "proofs": [{"kind": "check", "gate": "qualification", "assertion": "Native qualification assertions"}]}],
                    "delivery": "local only"}
            (evidence / "candidate.diff").write_text("frozen")
            task_path = root / "task.json"
            task_path.write_text(json.dumps(task))

            def handoff(mode):
                return subprocess.run([sys.executable, "-B", str(SCRIPTS / "handoff.py"), mode,
                    "--task", str(task_path), "--evidence-dir", str(evidence)], cwd=checkout, capture_output=True)

            self.assertEqual(handoff("preflight").returncode, 0)
            args = [sys.executable, "-B", str(SCRIPTS / "capture_check.py"), "--evidence-dir", str(evidence),
                    "--candidate", "unchanged", "--gate", "qualification", "--owner", "controller",
                    "--scope", "qualification", "--fingerprint-command", json.dumps(probe), "--", *command]
            self.assertEqual(subprocess.run(args, cwd=checkout, capture_output=True).returncode, 0)
            for path in [*files, source_file]:
                original = path.read_bytes()
                for remove in (False, True):
                    with self.subTest(input=path.name, remove=remove):
                        # The unchanged control reuses; fingerprinting does not touch inputs.
                        unchanged = subprocess.run(args, cwd=checkout, capture_output=True)
                        self.assertIn(b"Check reused:", unchanged.stdout)
                        if remove:
                            path.unlink()
                        else:
                            path.write_bytes(b"changed input")
                        packet = json.loads(handoff("review").stdout)
                        self.assertFalse(packet["ready_for_review"])
                        attempted = subprocess.run(args, cwd=checkout, capture_output=True)
                        self.assertNotIn(b"Check reused:", attempted.stdout)
                        path.write_bytes(original)
                        # Restore the governing receipt for the next independent mutation.
                        self.assertEqual(subprocess.run(args, cwd=checkout, capture_output=True).returncode, 0)
            # New source files and changed manifest scope also invalidate the receipt.
            (source / "new.py").write_text("new product input")
            self.assertFalse(json.loads(handoff("review").stdout)["ready_for_review"])
            (source / "new.py").unlink()
            manifest.write_text(json.dumps({"files": [str(files[0])], "trees": []}))
            self.assertFalse(json.loads(handoff("review").stdout)["ready_for_review"])


if __name__ == "__main__":
    unittest.main()
