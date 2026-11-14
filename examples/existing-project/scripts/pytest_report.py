"""Run serial pytest and retain genuine parent node outcomes and test specs."""

import argparse
import json
import os
from pathlib import Path
import sys

from evidence_inputs import manifest


class Reports:
    def __init__(self):
        self.collected = set()
        self.events = {}

    def pytest_collection_finish(self, session):
        self.collected = {item.nodeid for item in session.items}

    def pytest_configure(self, config):
        import pytest
        if config.getoption("numprocesses", None) or config.getoption("reruns", 0):
            raise pytest.UsageError("FlightCheck reference reporting supports serial, single-attempt pytest only")

    def pytest_runtest_logreport(self, report):
        # Native subtest reports share the parent's real nodeid. Do not invent
        # suffixes or count subtest messages as separately collected tests.
        subtest = hasattr(report, "context") or "subtest" in type(report).__name__.lower()
        self.events.setdefault(report.nodeid, []).append({
            "when": report.when, "outcome": report.outcome, "xfail": hasattr(report, "wasxfail"),
            "subtest": subtest, "context": repr(getattr(report, "context", None)) if subtest else None})

    def result(self):
        outcomes = {name: [] for name in ("passed", "skipped", "expected_failures", "failed")}
        incomplete = []
        for nodeid in sorted(self.collected | self.events.keys()):
            events = self.events.get(nodeid, [])
            ordinary = [event for event in events if not event["subtest"]]
            phases = {event["when"]: event for event in ordinary}
            unsupported = (len(phases) != len(ordinary) or
                           any(event["when"] not in {"setup", "call", "teardown"} or
                               event["outcome"] not in {"passed", "failed", "skipped"}
                               for event in events))
            if nodeid not in self.collected or unsupported:
                incomplete.append(nodeid)
            elif any(event["outcome"] == "failed" for event in events):
                outcomes["failed"].append(nodeid)
            elif any(event["outcome"] == "skipped" for event in phases.values()):
                skipped = [event for event in phases.values() if event["outcome"] == "skipped"]
                outcomes["expected_failures" if all(e["xfail"] for e in skipped) else "skipped"].append(nodeid)
            elif set(phases) == {"setup", "call", "teardown"} and all(e["outcome"] == "passed" for e in phases.values()):
                outcomes["passed"].append(nodeid)
            else:
                incomplete.append(nodeid)
        return outcomes, incomplete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", action="append", required=True, help="Required test/fixture path; exclude the product")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        output = Path(os.environ["FLIGHTCHECK_REPORT_DIR"])
        if not output.is_dir():
            raise ValueError("FLIGHTCHECK_REPORT_DIR must name this recorder invocation's report directory")
        before = manifest(Path.cwd(), args.spec)
        import pytest
        if pytest.version_tuple[:2] != (9, 2):
            raise ValueError("Reference adapter is qualified for pytest 9.2.x; qualify another version before use")
        reports = Reports()
        native_args = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
        sys.dont_write_bytecode = True
        code = int(pytest.main(native_args, plugins=[reports]))
        coverage, incomplete = reports.result()
        changed = before != manifest(Path.cwd(), args.spec)
        adapter_code = code or (3 if incomplete or changed else 0)
        (output / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
        (output / "spec.json").write_text(json.dumps(before, sort_keys=True, indent=2) + "\n")
        (output / "phases.json").write_text(json.dumps({"events": reports.events, "incomplete": incomplete,
                    "spec_changed": changed, "pytest_exit_code": code, "adapter_exit_code": adapter_code}, indent=2) + "\n")
        return adapter_code
    except (OSError, ValueError, KeyError, ImportError) as error:
        parser.exit(2, "Cannot report native pytest evidence: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
