"""Deterministic public progress observations, including an original-source control.

The compatibility path exercises the old publisher/runner when the original
product lacks automatic progress; assertions still concern observable behavior.
"""

import importlib.util
import fcntl
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PRODUCT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(PRODUCT / "status-card"))
import maintainer
import task_status
try:
    import progress
except ModuleNotFoundError:
    progress = None

spec = importlib.util.spec_from_file_location("progress_capture", PRODUCT / "workflow/scripts/capture_check.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class ProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        (self.checkout / "README").write_text("fixture\n")
        subprocess.run(["git", "init", "-q", str(self.checkout)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.checkout), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                        "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.checkout), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                        "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], check=True, capture_output=True)
        self.directory = self.root / "task"
        self.directory.mkdir(mode=0o700)
        self.candidate = maintainer.candidate(self.checkout)
        self.clock = 1800000000.0
        self.details = {"stages": {name: "current" if name == "Cheap Tests" else "pending" for name in task_status.STAGE_NAMES},
                        "check_plan": ["Native check"], "checks": [{"name": "Native check", "candidate": self.candidate,
                        "state": "pending", "counts": {}, "observed_at": task_status.utc_time(self.clock) if hasattr(task_status, "utc_time") else "2027-01-15T08:00:00+00:00"}],
                        "links_unavailable": {"issue": "Synthetic task.", "pr": "No PR."}}
        self.data = {"mode": "flight", "task": "test-change", "title": "Progress fixture", "summary": "", "candidate": self.candidate}
        self.publish(self.details)

    def publish(self, details, **kwargs):
        data = self.read() if (self.directory / "status.json").exists() else dict(self.data)
        if "now" in inspect.signature(task_status.publish).parameters or progress is not None:
            task_status.publish(self.directory / "status.json", data, details, now=self.clock, **kwargs)
        else:
            task_status.publish(self.directory / "status.json", data, details)

    def read(self):
        return task_status.read_task(self.directory / "status.json")

    def activity(self, identity, kind="controller", name=None):
        if progress is None:
            class LegacyActivity:
                def begin(self): return None
                def heartbeat(self): return None
                def update(self, *args): return None
                def end(self, *args, **kwargs): return None
            return LegacyActivity()
        return progress.Activity(self.directory, "test-change", self.candidate, identity, kind,
                                 name or identity, now=lambda: self.clock)

    def observe(self):
        return progress.observe(self.directory, "test-change", now=self.clock) if progress else self.read()

    def test_long_silent_check_and_controller_activity(self):
        native = self.activity("native-1", "check", "Native check")
        controller = self.activity("controller-1")
        controller.begin()
        native.begin()
        self.assertEqual(self.read()["checks"][0]["state"], "running")
        class Child:
            pid = 123456
            calls = 0
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def wait(child, timeout=None):
                child.calls += 1
                self.clock += 10
                if child.calls <= 4 and timeout is not None:
                    raise subprocess.TimeoutExpired(["silent"], timeout)
                return 0
        child = Child()
        with patch.object(capture.subprocess, "Popen", return_value=child), patch.object(capture.signal, "signal", return_value=None):
            with (self.root / "output").open("wb") as output:
                kwargs = {"activity": native} if "activity" in inspect.signature(capture.run_command).parameters else {}
                self.assertEqual(capture.run_command(["silent"], output, **kwargs), 0)
        self.assertGreaterEqual(child.calls, 5)
        data = self.observe()
        self.assertLessEqual(data["freshness"]["heartbeat_age_seconds"], 10)
        self.assertGreater(data["freshness"]["owner_remaining_seconds"], 0)
        native.end("completed", counts={"passed": 3})
        controller.end()
        self.assertEqual(self.read()["checks"][0]["counts"], {"passed": 3})
        # Also exercise the real recorder, explicit prepare binding and silent
        # child: a fake wait alone cannot establish the source/installed bridge.
        self.clock = time.time()
        self.publish({"checks": self.details["checks"]})
        environment = dict(os.environ, FLIGHTCHECK_STATE_DIR=str(self.root / "state"), PYTHONDONTWRITEBYTECODE="1")
        environment.pop("FLIGHTCHECK_TASK_ID", None)
        with patch.dict(os.environ, environment, clear=True):
            state = maintainer.state_dir(self.checkout)
            progress.register(self.checkout, state, self.directory, "test-change")
        evidence = self.root / "evidence"
        evidence.mkdir(mode=0o700)
        command = [sys.executable, "-B", str(PRODUCT / "workflow/scripts/capture_check.py"),
                   "--evidence-dir", str(evidence), "--candidate", self.candidate, "--scope", "Native check",
                   "--", sys.executable, "-c", "import time;time.sleep(11);print('native preserved')"]
        child = subprocess.Popen(command, cwd=self.checkout, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and self.read()["checks"][0]["state"] != "running":
                time.sleep(.02)
            self.assertEqual(self.read()["checks"][0]["state"], "running")
            active = next(row for row in self.read()["activities"] if row["kind"] == "check" and row["state"] == "running")
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                row = next(row for row in self.read()["activities"] if row["id"] == active["id"])
                if row["heartbeat_at"] != active["heartbeat_at"]:
                    break
                time.sleep(.05)
            self.assertEqual(row["state"], "running")
            self.assertNotEqual(row["heartbeat_at"], active["heartbeat_at"])
            stdout, stderr = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, stderr.decode())
            self.assertIn(b"native preserved", stdout)
            run, = evidence.glob("check-*")
            receipt = json.loads((run / "run.json").read_text())
            self.assertEqual(receipt["status"], "finished")
            self.assertEqual((run / "output.log").read_text(), "native preserved\n")
            self.assertNotIn("heartbeat_at", receipt)
        finally:
            if child.poll() is None:
                child.terminate()
                child.communicate(timeout=5)
        # Broken optional projection still retains the exact failing native run.
        broken_environment = dict(environment, FLIGHTCHECK_TASK_ID="not-selected-here")
        failed = subprocess.run([*command[:command.index("--") + 1], sys.executable, "-c",
                                 "import sys;sys.stdout.buffer.write(b'native failure bytes\\n');sys.exit(7)"],
                                cwd=self.checkout, env=broken_environment, capture_output=True, timeout=5)
        self.assertEqual(failed.returncode, 7)
        self.assertIn(b"Progress projection unavailable", failed.stderr)
        receipts = [json.loads(path.read_text()) for path in evidence.glob("check-*/run.json")]
        failing = next(row for row in receipts if row["exit_code"] == 7)
        self.assertEqual((evidence / failing["run_id"] / "output.log").read_bytes(), b"native failure bytes\n")
        class BrokenActivity:
            def begin(self): raise RuntimeError("projection bug")
        with patch.object(capture.sys, "stderr"):
            capture.project_activity(BrokenActivity(), "begin")

    def test_distinct_clocks_and_concurrent_updates(self):
        worker = self.activity("worker-1", "worker")
        reviewer = self.activity("review-1", "reviewer")
        worker.begin()
        reviewer.begin()
        first = self.read()
        self.clock += 20
        threads = [threading.Thread(target=lambda: worker.update("Implementation advanced")),
                   threading.Thread(target=lambda: reviewer.end("failed"))]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        data = self.observe()
        rows = {row["id"]: row for row in data.get("activities", [])}
        self.assertEqual(set(rows), {"worker-1", "review-1"})
        self.assertEqual(rows["review-1"]["state"], "failed")
        self.assertEqual(rows["worker-1"]["state"], "running")
        self.assertEqual(rows["worker-1"]["summary"], "Implementation advanced")
        self.assertEqual(rows["worker-1"]["heartbeat_at"], data["freshness"]["publisher_heartbeat_at"])
        self.assertGreater(data["freshness"]["revision"], first["freshness"]["revision"])
        activity_at = data["freshness"]["activity_at"]
        self.clock += 20
        worker.heartbeat()
        self.assertEqual(self.read()["freshness"]["activity_at"], activity_at)
        self.clock += 20
        self.assertEqual(self.observe()["freshness"]["state"], "active")
        self.clock += 11
        self.assertEqual(self.observe()["freshness"]["state"], "stale")
        # Opposite completion order retains both independent outcomes. A failed
        # review is an observation, never an invented workflow advancement.
        self.clock += 1
        worker.end()
        reviewer2 = self.activity("review-2", "reviewer")
        reviewer2.begin()
        reviewer2.end("failed")
        final = self.read()
        final_rows = {row["id"]: row for row in final["activities"]}
        self.assertEqual(final_rows["worker-1"]["state"], "completed")
        self.assertEqual(final_rows["review-1"]["state"], "failed")
        self.assertEqual(final_rows["review-2"]["state"], "failed")
        self.assertEqual(final["stages"]["PR & Merge"], "pending")
        self.assertEqual(final["checks"][0]["state"], "pending")

    def test_honest_closeout_and_lease_expiry(self):
        controller = self.activity("controller-1")
        controller.begin()
        controller.end()
        # Finishing an activity cannot cosmetically complete workflow stages.
        self.assertEqual(self.read()["stages"]["Cheap Tests"], "current")
        self.assertNotEqual(self.read().get("freshness", {}).get("state"), "closed")
        self.assertIn("freshness", self.read())
        config = {"task": "test-change", "checkout": str(self.checkout), "directory": str(self.directory),
                  "token": "fixture", "started_at": self.clock}
        maintainer.write_json(self.directory / "monitor.json", config)
        expiry = self.read()["freshness"]["owner_expires_at"]
        self.clock += 10
        self.assertTrue(progress.monitor_step(self.directory, "fixture", now=self.clock, probe=False))
        self.assertEqual(self.read()["freshness"]["owner_expires_at"], expiry)
        self.clock += 111
        self.assertFalse(progress.monitor_step(self.directory, "fixture", now=self.clock, probe=False))
        self.assertEqual(self.observe()["freshness"]["state"], "expired")
        terminal = {"stages": {name: "completed" for name in task_status.STAGE_NAMES},
                    "checks": [{**self.details["checks"][0], "state": "passed", "counts": {"passed": 1}}]}
        terminal["stages"]["Interactive UI Approval"] = "skipped"
        self.publish(dict(terminal, checks=[{**self.details["checks"][0], "state": "failed", "counts": {"failed": 1}}]))
        self.assertTrue(progress.monitor_step(self.directory, "fixture", now=self.clock, probe=False))
        self.assertNotEqual(self.read()["freshness"]["state"], "closed")
        self.assertEqual(self.read()["checks"][0]["state"], "failed")
        self.publish(terminal)
        self.assertFalse(progress.monitor_step(self.directory, "fixture", now=self.clock, probe=False))
        self.assertEqual(self.observe()["freshness"]["state"], "closed")
        self.assertEqual(self.read()["stages"]["Interactive UI Approval"], "skipped")
        before = (self.directory / "status.json").read_bytes()
        self.clock += 500
        self.assertEqual(self.observe()["freshness"]["state"], "closed")
        self.assertEqual((self.directory / "status.json").read_bytes(), before)
        # Moving UTC backwards cannot extend the detached process's lease.
        elapsed = [0.0]
        runtime = progress.LeaseClock(monotonic=lambda: elapsed[0])
        fresh = dict(self.read()["freshness"], owner_expires_at=task_status.utc_time(self.clock + 120))
        self.assertEqual(runtime.expired(fresh, self.clock, self.clock), (False, False))
        elapsed[0] = 121
        self.assertTrue(runtime.expired(fresh, self.clock, self.clock - 1000)[0])

    def test_task_candidate_route_boundaries(self):
        current = self.activity("worker-1", "worker")
        current.begin()
        self.assertEqual(len(self.read().get("activities", [])), 1)
        before = (self.directory / "status.json").read_bytes()
        for task, candidate in (("wrong-task", self.candidate), ("test-change", "wrong-candidate")):
            with self.subTest(task=task, candidate=candidate):
                with self.assertRaises(ValueError):
                    progress.Activity(self.directory, task, candidate, "wrong", "reviewer", "private-name").begin()
                self.assertEqual((self.directory / "status.json").read_bytes(), before)
        with patch.object(maintainer, "start_listener", side_effect=ValueError("port occupied")) as start:
            maintainer.write_json(self.directory / "endpoint.json", {"port": 31337, "pid": 123456})
            with patch.object(maintainer, "current_card", return_value=None), patch.object(progress.time, "time", return_value=self.clock):
                with self.assertRaisesRegex(ValueError, "preserved route"):
                    progress.recover_listener(self.directory, "test-change")
            self.assertEqual(start.call_count, 3)
            self.assertEqual((self.directory / "status.json").read_bytes(), before)
        self.assertNotIn(str(self.root), json.dumps(self.observe()))

    def test_source_publication_during_recovery(self):
        self.clock = time.time()
        self.publish(self.details)
        native = self.activity("native-observation", "check", "Native check")
        native.begin()
        native.end("completed", counts={"passed": 3})
        controller = self.activity("controller-observation")
        controller.begin()
        original = self.read()
        source = self.root / "details.json"
        maintainer.write_json(source, self.details)
        progress.register(self.checkout, self.root / "state", self.directory, "test-change", source)
        maintainer.write_json(self.directory / "endpoint.json", {"port": 31337, "pid": 999999})
        config = maintainer.read_json(self.directory / "monitor.json")
        source_read = threading.Event()
        errors = []
        read_text = Path.read_text

        def observed_read(path, *args, **kwargs):
            value = read_text(path, *args, **kwargs)
            if path.resolve() == source.resolve() and threading.current_thread() is runner:
                source_read.set()
            return value

        def run_monitor():
            try:
                progress.main()
            except BaseException as error:
                errors.append(error)

        def wait_for(predicate, timeout):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if predicate():
                    return True
                time.sleep(.02)
            return predicate()

        runner = threading.Thread(target=run_monitor, name="source-monitor")
        with (self.directory / "listener.lock").open("a") as lifecycle_lock:
            fcntl.flock(lifecycle_lock, fcntl.LOCK_EX)
            release = threading.Timer(10, lambda: fcntl.flock(lifecycle_lock, fcntl.LOCK_UN))
            release.start()
            try:
                with patch.object(Path, "read_text", observed_read), patch.object(sys, "argv", [
                        "progress.py", "monitor", "--directory", str(self.directory), "--token", config["token"]]), \
                        patch.object(maintainer, "current_card", return_value=None), \
                        patch.object(maintainer, "start_listener", side_effect=ValueError("Fixture listener unavailable")):
                    runner.start()
                    self.assertTrue(source_read.wait(2), "The registered source was not observed")
                    value = dict(self.details, links_unavailable={"issue": "Changed while recovery owns its lock", "pr": "No PR."})
                    started = time.monotonic()
                    maintainer.write_json(source, value)
                    with self.subTest(boundary="recovery lock held ten seconds"):
                        self.assertTrue(wait_for(lambda: self.read()["links_unavailable"] == value["links_unavailable"], 5),
                                        "Source publication exceeded five seconds during listener recovery")
                        self.assertLessEqual(time.monotonic() - started, 5)
                    self.assertEqual(self.read()["checks"][0]["counts"], {"passed": 3})
                    self.assertEqual(self.read()["stage_updated_at"], original["stage_updated_at"])
                    self.assertEqual({row["id"] for row in self.read()["activities"]},
                                     {"native-observation", "controller-observation"})
                    release.join(11)
                    self.assertTrue(wait_for(lambda: bool(maintainer.read_json(self.directory / "monitor.json").get("recovery_error")), 3))
                    value["links_unavailable"] = {"issue": "Changed after recovery exhausted", "pr": "No PR."}
                    maintainer.write_json(source, value)
                    with self.subTest(boundary="recovery exhausted"):
                        self.assertTrue(wait_for(lambda: self.read()["links_unavailable"] == value["links_unavailable"], 5),
                                        "Exhausted listener recovery stopped authorized source publication")
                    self.assertEqual(self.read()["checks"][0]["state"], "passed")
                    self.assertEqual(self.read()["stage_updated_at"], original["stage_updated_at"])
            finally:
                release.cancel()
                fcntl.flock(lifecycle_lock, fcntl.LOCK_UN)
                with progress.locked(self.directory):
                    stopped = maintainer.read_json(self.directory / "monitor.json")
                    stopped["token"] = "stopped"
                    maintainer.write_json(self.directory / "monitor.json", stopped)
                runner.join(16)
        self.assertFalse(runner.is_alive(), "Monitor did not stop after explicit generation invalidation")
        self.assertEqual(errors, [])

    def test_worker_listener_expiry_inside_recovery(self):
        for boundary in ("lifecycle lock", "read-only probe"):
            with self.subTest(boundary=boundary):
                clock = [1800000000.0]
                elapsed = [0.0]
                data = self.read()
                data["freshness"].update(owner_expires_at=task_status.utc_time(clock[0] + 1),
                                         publisher_heartbeat_at=task_status.utc_time(clock[0]),
                                         published_at=task_status.utc_time(clock[0]), activity_at=task_status.utc_time(clock[0]))
                maintainer.write_json(self.directory / "status.json", data)
                maintainer.write_json(self.directory / "endpoint.json", {"port": 31337, "pid": 999999})

                def advance(*args, **kwargs):
                    clock[0] += 5
                    elapsed[0] += 5
                    return None

                with (self.directory / "listener.lock").open("a") as lifecycle_lock:
                    if boundary == "lifecycle lock":
                        fcntl.flock(lifecycle_lock, fcntl.LOCK_EX)
                    try:
                        with patch.object(progress.time, "time", side_effect=lambda: clock[0]), \
                                patch.object(progress.time, "monotonic", side_effect=lambda: elapsed[0]), \
                                patch.object(progress.time, "sleep", side_effect=advance), \
                                patch.object(maintainer, "current_card", side_effect=advance), \
                                patch.object(maintainer, "start_listener", return_value={"port": 31337, "pid": 999998}) as start:
                            error = None
                            try:
                                progress.recover_listener(self.directory, "test-change")
                            except ValueError as caught:
                                error = str(caught)
                            self.assertEqual(start.call_count, 0, "Listener startup occurred after producer ownership expired")
                            self.assertIsNotNone(error, "Expired recovery unexpectedly reported success")
                            self.assertIn("expired", error.lower())
                            self.assertEqual(elapsed[0], 5, "Recovery continued waiting after ownership expired")
                    finally:
                        fcntl.flock(lifecycle_lock, fcntl.LOCK_UN)


if __name__ == "__main__":
    unittest.main()
