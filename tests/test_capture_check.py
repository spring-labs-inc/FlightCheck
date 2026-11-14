"""Exercise the optional capture example with native commands and real pytest output."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])) / "examples/existing-project/scripts/capture_check.py"


class CaptureCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.project = root / "project"
        self.project.mkdir()
        self.evidence = root / "evidence"
        self.evidence.mkdir(mode=0o700)
        self.env = dict(os.environ, PYTEST_ADDOPTS="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")

    def invocation(self, command, *, pytest_summary=False):
        summary = ["--summary", "pytest"] if pytest_summary else []
        return [
            sys.executable, str(SCRIPT), "--evidence-dir", str(self.evidence),
            "--candidate", "fixture-candidate", "--scope", "isolated fixture",
            *summary, "--", *command,
        ]

    def read_run(self, display):
        marker = display.splitlines()[0].decode()
        self.assertTrue(marker.startswith("Check evidence: "))
        path = Path(marker.removeprefix("Check evidence: "))
        packet = json.loads((path / "run.json").read_text())
        log = (path / packet["output"]["path"]).read_bytes()
        self.assertEqual(packet["run_id"], path.name)
        self.assertEqual(packet["candidate"], "fixture-candidate")
        self.assertEqual(packet["output"]["sha256"], hashlib.sha256(log).hexdigest())
        self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        return packet, log

    def pytest_run(self, source, *flags):
        (self.project / "test_example.py").write_text(source)
        command = [sys.executable, "-m", "pytest", "-q", *flags]
        result = subprocess.run(
            self.invocation(command, pytest_summary=True), check=False, cwd=self.project, env=self.env,
            capture_output=True, timeout=20,
        )
        packet, log = self.read_run(result.stdout)
        self.assertEqual(packet["exit_code"], result.returncode)
        self.assertEqual(packet["command"], command)
        return packet, log

    def test_late_pytest_warning_survives_a_closed_display(self):
        (self.project / "test_example.py").write_text(
            "import os, warnings\n\n"
            "def test_noisy():\n"
            "    print('x' * 150000, flush=True)\n"
            "    os.write(2, b'native stderr\\n')\n"
            "    warnings.warn('warning beyond the display limit', UserWarning)\n"
        )
        command = [sys.executable, "-m", "pytest", "-q", "-s", "--color=yes"]
        with subprocess.Popen(
            self.invocation(command, pytest_summary=True), cwd=self.project, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        ) as process:
            with process.stdout as stream:
                display = stream.read(256)
            self.assertEqual(process.wait(timeout=20), 0)
        self.assertNotIn(b"warning beyond the display limit", display)
        packet, log = self.read_run(display)
        self.assertIn(b"warnings summary", log)
        self.assertIn(b"UserWarning: warning beyond the display limit", log)
        self.assertIn(b"native stderr", log)
        self.assertEqual(packet["command"], command)
        self.assertEqual(packet["coverage"]["reported"]["passed"], 1)
        self.assertEqual(packet["output"]["status"], "complete")
        self.assertEqual(packet["warnings"], {"status": "complete", "count": 1})

    def test_warning_states_and_actual_pytest_exit_statuses(self):
        passing = "def test_ok():\n    pass\n"
        warning = "import warnings\n\ndef test_ok():\n    warnings.warn('hidden warning')\n"
        cases = [
            (passing, [], 0, "complete", "none", 0),
            (warning, ["--disable-warnings"], 0, "complete", "unavailable", 1),
            ("def test_failed():\n    assert False\n", [], 1, "complete", "none", 0),
            ("def test_stop():\n    raise KeyboardInterrupt\n", [], 2, "incomplete", "incomplete", None),
        ]
        run_ids = set()
        for source, flags, code, capture, warning_status, count in cases:
            with self.subTest(code=code, flags=flags):
                packet, _ = self.pytest_run(source, *flags)
                self.assertEqual(packet["exit_code"], code)
                self.assertEqual(packet["output"]["status"], capture)
                self.assertEqual(packet["warnings"], {"status": warning_status, "count": count})
                run_ids.add(packet["run_id"])
        self.assertEqual(len(run_ids), len(cases))

    def test_generic_checks_capture_concurrent_runs_independently(self):
        commands = [
            [sys.executable, "-c", "import sys; print('check A'); sys.exit(7)"],
            [sys.executable, "-c", "import sys; print('check B', file=sys.stderr)"],
        ]
        with subprocess.Popen(
            self.invocation(commands[0]), cwd=self.project, stdout=subprocess.PIPE,
        ) as first:
            second = subprocess.run(
                self.invocation(commands[1]), check=False, cwd=self.project, capture_output=True, timeout=20,
            )
            first_output, _ = first.communicate(timeout=20)
        a, log_a = self.read_run(first_output)
        b, log_b = self.read_run(second.stdout)
        self.assertEqual((first.returncode, second.returncode), (7, 0))
        self.assertEqual((a["exit_code"], b["exit_code"]), (7, 0))
        self.assertEqual((log_a, log_b), (b"check A\n", b"check B\n"))
        self.assertNotEqual(a["run_id"], b["run_id"])
        self.assertEqual(b["warnings"], {"status": "unclassified", "count": None})

    def test_termination_preserves_partial_output_and_signal_status(self):
        command = [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(10)"]
        with subprocess.Popen(
            self.invocation(command), cwd=self.project, stdout=subprocess.PIPE,
        ) as process:
            marker = process.stdout.readline()
            run = Path(marker.decode().strip().removeprefix("Check evidence: "))
            log = run / "output.log"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if log.is_file() and log.read_bytes() == b"started\n":
                    break
                time.sleep(0.01)
            else:
                process.terminate()
                self.fail("The check did not write its start marker")
            process.terminate()
            replay, _ = process.communicate(timeout=5)
        packet, original = self.read_run(marker + replay)
        self.assertEqual(process.returncode, 128 + signal.SIGTERM)
        self.assertEqual(packet["exit_code"], -signal.SIGTERM)
        self.assertEqual(packet["status"], "interrupted")
        self.assertEqual(packet["output"]["status"], "incomplete")
        self.assertEqual(original, b"started\n")

    def run_reusable(self, *, refresh=False, fail=False):
        probe = [sys.executable, "-c", "from pathlib import Path; print(Path('inputs').read_text())"]
        script = (
            "import os, sys; from pathlib import Path; "
            "(Path(os.environ['FLIGHTCHECK_REPORT_DIR']) / 'report').write_text('original report'); "
            "print('native check ran'); sys.exit(int(os.environ['CHECK_FAIL']))"
        )
        command = [sys.executable, "-c", script]
        invocation = self.invocation(command)
        invocation[-len(command) - 1:-len(command) - 1] = [
            "--gate", "fixture", "--fingerprint-command", json.dumps(probe),
            "--artifact", "report", "--isolated-reports", *(["--refresh"] if refresh else []),
        ]
        return subprocess.run(
            invocation, check=False, cwd=self.project, env=dict(self.env, CHECK_FAIL=str(int(fail))),
            capture_output=True, timeout=20,
        )

    def test_matching_receipt_reuses_output_but_changed_inputs_run_again(self):
        inputs = self.project / "inputs"
        inputs.write_text("source A, runtime A")
        first = self.run_reusable()
        packet, _ = self.read_run(first.stdout)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(packet["inputs_before"], packet["inputs_after"])
        second = self.run_reusable()
        self.assertEqual(second.returncode, 0)
        self.assertIn(b"Check reused:", second.stdout)
        self.assertNotIn(b"native check ran", second.stdout)
        reuse_path, = self.evidence.glob("reuse-*/reuse.json")
        reuse = json.loads(reuse_path.read_text())
        self.assertEqual(reuse["source_run_id"], packet["run_id"])
        self.assertEqual(reuse["inputs"], packet["inputs_after"])

        inputs.write_text("source A, runtime B")
        third = self.run_reusable()
        self.assertIn(b"native check ran", third.stdout)
        self.assertNotIn(b"Check reused:", third.stdout)

    def test_newer_failure_and_damaged_artifact_each_force_a_run(self):
        (self.project / "inputs").write_text("stable inputs")
        first, _ = self.read_run(self.run_reusable().stdout)
        artifact = self.evidence / first["run_id"] / "artifact-0"
        artifact.write_text("changed report")
        self.assertIn(b"native check ran", self.run_reusable().stdout)

        failure = self.run_reusable(refresh=True, fail=True)
        self.assertEqual(failure.returncode, 1)
        self.assertIn(b"native check ran", self.run_reusable().stdout)

    def test_unavailable_fingerprint_cannot_validate_a_passing_run(self):
        result = self.run_reusable()
        packet, _ = self.read_run(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(packet["inputs_before"])
        self.assertIn(b"native check ran", self.run_reusable().stdout)

    def isolated(self, script, *extra):
        command = [sys.executable, "-c", script]
        invocation = self.invocation(command)
        at = invocation.index("--")
        invocation[at:at] = ["--gate", "isolated", "--owner", "controller", "--refresh",
            "--fingerprint-command", json.dumps([sys.executable, "-c", "print('stable fixture')"]),
            "--isolated-reports", "--artifact", "report", *extra]
        result = subprocess.run(invocation, cwd=self.project, env=self.env, capture_output=True, timeout=10)
        packet, output = self.read_run(result.stdout)
        return result, packet, output

    def test_stale_checkout_report_cannot_supply_a_new_invocations_artifact(self):
        (self.project / "report").write_text("old passing report")
        result, packet, _ = self.isolated("print('no report was produced')")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("report", packet["artifacts"])
        self.assertEqual(list(Path(packet["report_directory"]).iterdir()), [])

    def test_failed_reproduction_reports_are_retained_and_runs_are_isolated(self):
        script = ("import os, sys; from pathlib import Path; "
                  "(Path(os.environ['FLIGHTCHECK_REPORT_DIR'])/'report').write_text('observed failure'); sys.exit(1)")
        result, first, _ = self.isolated(script)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(first["inputs_before"], first["inputs_after"])
        retained = self.evidence / first["run_id"] / "artifact-0"
        self.assertEqual(retained.read_text(), "observed failure")
        _, second, _ = self.isolated(script.replace("observed failure", "second failure"))
        self.assertNotEqual(first["report_directory"], second["report_directory"])
        self.assertEqual(retained.read_text(), "observed failure")

    def test_report_symlink_cannot_import_an_old_or_external_report(self):
        (self.project / "report").write_text("old pass")
        script = ("import os; from pathlib import Path; "
                  "(Path(os.environ['FLIGHTCHECK_REPORT_DIR'])/'report').symlink_to(Path('report').resolve())")
        _, packet, _ = self.isolated(script)
        self.assertNotIn("report", packet["artifacts"])

    def test_private_directory_creation_and_nested_checkout_rejection(self):
        self.evidence.rmdir()
        result, packet, _ = self.isolated("print('probe')", "--create-evidence-dir")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.evidence.stat().st_mode & 0o777, 0o700)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True, capture_output=True)
        nested = self.project / "src"
        nested.mkdir()
        forbidden = self.project / "evidence"
        command = self.invocation([sys.executable, "-c", "print('must not run')"])
        command[command.index("--evidence-dir") + 1] = str(forbidden)
        command.insert(command.index("--"), "--create-evidence-dir")
        bad = subprocess.run(command, cwd=nested, capture_output=True, timeout=10)
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(forbidden.exists())


if __name__ == "__main__":
    unittest.main()
