"""Validate configured adoption inputs, without requiring future native proofs."""

import hashlib
import json
import re
from pathlib import PurePosixPath

from handoff_schema import ID, TEXT, TESTS, coverage, fail, validate


def artifact(value, field):
    validate(value, TEXT, field)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        fail(field, "use a normalized relative artifact path inside the invocation report directory")
    return value


def spec_artifact(gate, field):
    native = gate.get("coverage", {})
    name = native.get("spec")
    alternatives = [item for item in gate["request"]["artifacts"] if item != native["artifact"]]
    # Compatibility for existing two-artifact callers; new examples declare spec.
    if name is None and len(alternatives) == 1:
        name = alternatives[0]
    if name is None or name == native["artifact"] or name not in alternatives:
        fail(field + ".coverage.spec", "declare a distinct retained test/fixture spec artifact in request.artifacts",
             "qualifying-expected-outcomes")
    return name


def validate_config(task, root):
    """Configuration errors fail now; omitted future receipts/controls stay pending."""
    gates = task.get("gates")
    if not isinstance(gates, list) or not gates:
        fail("task.gates", "expected a nonempty array of required gates")
    by_gate = {}
    for index, gate in enumerate(gates):
        field = f"task.gates[{index}]"
        if not isinstance(gate, dict):
            fail(field, "expected object")
        name = gate.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name in by_gate:
            fail(field + ".id", "expected a unique gate identifier")
        by_gate[name] = (gate, field)
        for key, choices in (("phase", ("cheap", "authoritative")), ("owner", ("controller", "worker"))):
            if key in gate:
                validate(gate[key], {"enum": list(choices)}, field + "." + key)
        request = gate.get("request")
        if not isinstance(request, dict):
            fail(field + ".request", "expected object")
        for key in ("command", "fingerprint_command"):
            value = request.get(key)
            if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
                fail(field + ".request." + key, "expected a nonempty string argument array")
        validate(request.get("scope"), TEXT, field + ".request.scope")
        artifacts = request.get("artifacts")
        if not isinstance(artifacts, list) or len(set(map(str, artifacts))) != len(artifacts):
            fail(field + ".request.artifacts", "expected a unique artifact path array")
        for number, value in enumerate(artifacts):
            artifact(value, f"{field}.request.artifacts[{number}]")
        if artifacts and request.get("isolated_reports") is not True:
            fail(field + ".request.isolated_reports", "must be true when retaining artifacts")
        if "coverage" not in gate:
            continue
        native = gate["coverage"]
        if not isinstance(native, dict):
            fail(field + ".coverage", "expected object")
        report = native.get("artifact")
        if report not in artifacts:
            fail(field + ".coverage.artifact", "must name a retained request.artifacts entry")
        reference = native.get("baseline")
        validate(reference, TEXT, field + ".coverage.baseline")
        path = (root / reference).resolve()
        if root not in path.parents or not path.is_file():
            fail(field + ".coverage.baseline", "must exist as a file contained in the private evidence root")
        expected = native.get("baseline_sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            fail(field + ".coverage.baseline_sha256", "expected a nonempty 64-character lowercase SHA-256 digest")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            fail(field + ".coverage.baseline_sha256", "does not match the baseline file bytes")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            fail(field + ".coverage.baseline", "expected JSON coverage with all four outcome arrays")
        coverage(data, field + ".coverage.baseline")
        if "spec" in native:
            spec_artifact(gate, field)
    acceptance = task.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        fail("task.acceptance", "expected a nonempty array")
    cases = {}
    for index, item in enumerate(acceptance):
        field = f"task.acceptance[{index}]"
        if not isinstance(item, dict):
            fail(field, "expected object")
        validate(item.get("id"), ID, field + ".id")
        validate(item.get("description"), TEXT, field + ".description")
        proofs = item.get("proofs")
        if not isinstance(proofs, list) or not proofs:
            fail(field + ".proofs", "expected a nonempty array")
        for number, proof in enumerate(proofs):
            where = f"{field}.proofs[{number}]"
            if not isinstance(proof, dict):
                fail(where, "expected object")
            if proof.get("kind") == "check":
                validate(proof.get("gate"), ID, where + ".gate")
                if proof.get("gate") not in by_gate:
                    fail(where + ".gate", "names an unconfigured gate")
                gate, _ = by_gate[proof["gate"]]
                if "coverage" in gate:
                    validate(proof.get("tests"), TESTS, where + ".tests")
        declared = item.get("cases", [])
        if not isinstance(declared, list):
            fail(field + ".cases", "expected array")
        for number, case in enumerate(declared):
            where = f"{field}.cases[{number}]"
            if not isinstance(case, dict):
                fail(where, "expected object")
            validate(case.get("id"), ID, where + ".id")
            if case["id"] in cases:
                fail(where + ".id", "must be unique across the flight")
            cases[case.get("id")] = case
            binding(case, where, by_gate)
    challenges = task.get("challenge_checks", {})
    if not isinstance(challenges, dict):
        fail("task.challenge_checks", "expected object")
    for name, value in challenges.items():
        binding(value, "task.challenge_checks." + name, by_gate)
    controls = task.get("case_controls", {})
    if not isinstance(controls, dict):
        fail("task.case_controls", "expected object")
    for name, control in controls.items():
        field = "task.case_controls." + name
        if not isinstance(control, dict):
            fail(field, "expected object")
        for key in ("receipt", "candidate", "source", "report", "spec"):
            validate(control.get(key), TEXT, field + "." + key)
        if control["source"] not in ("baseline", "mutation"):
            fail(field + ".source", "expected baseline or mutation")
        if control["spec"] == control["report"]:
            fail(field + ".spec", "test/fixture specification must be distinct from the native outcome report")
        case = cases.get(name) or task.get("challenge_checks", {}).get(name)
        if case:
            gate, where = by_gate[case["gate"]]
            if control["report"] != gate["coverage"]["artifact"] or control["spec"] != spec_artifact(gate, where):
                fail(field + ".spec", "control report/spec must match the witness gate's retained artifact names")


def binding(value, field, by_gate):
    if not isinstance(value, dict):
        fail(field, "expected object")
    validate(value.get("gate"), ID, field + ".gate")
    if value.get("gate") not in by_gate:
        fail(field + ".gate", "names an unconfigured native gate")
    gate, where = by_gate[value["gate"]]
    if "coverage" not in gate:
        fail(field + ".gate", "behavior requires configured native coverage")
    validate(value.get("tests"), TESTS, field + ".tests")
    spec_artifact(gate, where)
