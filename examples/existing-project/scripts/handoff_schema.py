"""Published JSON Schema contracts and field-level structural diagnostics.

The stdlib validator implements only the keywords used by these exported schemas;
it does not judge whether an expectation is a grounded product requirement.
"""

import hashlib
import json
from pathlib import Path

GUIDE = str(Path(__file__).resolve().parent.parent / "docs/development-workflow.md")
TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
ID = {"type": "string", "pattern": r"^[a-zA-Z0-9_-]+$"}
TESTS = {"type": "array", "minItems": 1, "uniqueItems": True, "items": TEXT}


class InputError(ValueError):
    pass


def fail(field, message, section="acceptance-proof-and-handoff-preflight"):
    raise InputError(f"{field}: {message}. See {GUIDE}#{section}")


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required}


def array(items):
    return {"type": "array", "items": items}


def schema(kind):
    expectation = obj({"kind": {"enum": ["regression", "compatibility", "specification"]}, "reference": TEXT})
    case = obj({"id": ID, "criterion": ID, "dimension": TEXT, "input": TEXT,
                "observable": TEXT, "expected": TEXT, "expectation": expectation})
    if kind == "challenge":
        result = obj({"role": {"enum": ["CODE", "EVIDENCE"]},
                      "scope_sha256": {"type": "string", "pattern": r"^[a-f0-9]{64}$"},
                      "coverage": TEXT, "cases": {**array(case), "minItems": 1}})
    elif kind == "review":
        assessment = obj({"id": ID, "sufficient": {"type": "boolean"}, "reason": TEXT})
        withdrawal = obj({"kind": {"enum": ["functional-finding", "test-request", "challenge-case"]},
                          "id": ID, "proposal_sha256": TEXT, "reason": TEXT, "supersedes": TEXT},
                         ["kind", "id", "proposal_sha256", "reason"])
        properties = {"candidate": TEXT, "role": {"enum": ["CODE", "EVIDENCE"]},
                      "verdict": {"enum": ["APPROVE", "APPROVE_WITH_NITS", "APPROVE_WITH_OBSERVATIONS", "REVISE"]},
                      "coverage": TEXT, "challenge": {"type": "string"}, "criteria": array(assessment),
                      "findings": array(obj({"id": ID, "kind": {"enum": ["functional", "process", "nit"]},
                          "severity": {"enum": ["BLOCKER", "CONCERN", "NIT"]}, "reference": TEXT, "impact": TEXT})),
                      "test_requests": array(obj({"id": ID, "criterion": ID, "input": TEXT, "expected": TEXT, "reason": TEXT})),
                      "case_assessments": array(assessment), "withdrawals": array(withdrawal),
                      "phase": {"enum": [None, "code", "final", "disposition"]}}
        result = obj(properties, [key for key in properties if key not in ("case_assessments", "withdrawals", "phase")])
    elif kind == "coverage":
        result = obj({name: {"type": "array", "items": TEXT, "uniqueItems": True}
                      for name in ("passed", "skipped", "expected_failures", "failed")})
        result["additionalProperties"] = False
    else:
        fail("schema.kind", "expected challenge, review or coverage")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "FlightCheck " + kind, **result}


def validate(value, contract, field):
    import re
    types = {"object": dict, "array": list, "string": str, "boolean": bool}
    kind = contract.get("type")
    if kind and type(value) is not types[kind]:
        fail(field, "expected " + kind)
    if "enum" in contract and value not in contract["enum"]:
        fail(field, "expected one of " + ", ".join(json.dumps(item) for item in contract["enum"]))
    if isinstance(value, str):
        if len(value) < contract.get("minLength", 0) or ("pattern" in contract and not re.search(contract["pattern"], value)):
            fail(field, "expected a nonempty value matching " + contract.get("pattern", "the schema"))
    if isinstance(value, list):
        if len(value) < contract.get("minItems", 0):
            fail(field, "expected at least one item")
        if contract.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            fail(field, "items must be unique")
        for index, item in enumerate(value):
            validate(item, contract.get("items", {}), f"{field}[{index}]")
    if isinstance(value, dict):
        for key in contract.get("required", []):
            if key not in value:
                fail(field + "." + key, "required field is missing")
        for key, item in value.items():
            if key in contract.get("properties", {}):
                validate(item, contract["properties"][key], field + "." + key)
            elif contract.get("additionalProperties") is False:
                fail(field + "." + key, "unknown field")


def coverage(data, field):
    validate(data, schema("coverage"), field)
    seen = set()
    for name, tests in data.items():
        for index, test in enumerate(tests):
            if test in seen:
                fail(f"{field}.{name}[{index}]", "test identity occurs in more than one outcome")
            seen.add(test)
    return {test: outcome for outcome, tests in data.items() for test in tests}


def response(root, path, kind):
    """Retain exact bytes before parsing, including rejected native responses."""
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    directory = root / "responses"
    directory.mkdir(mode=0o700, exist_ok=True)
    retained = directory / (sha + ".json")
    if not retained.exists():
        retained.write_bytes(raw)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        fail(kind, f"invalid JSON ({error}); original retained at responses/{sha}.json")
    validate(data, schema(kind), kind)
    return raw, data, sha


def examples():
    return {"challenge": {"role": "EVIDENCE", "scope_sha256": "0" * 64,
                "coverage": "Scope-only review; no product execution",
                "cases": [{"id": "boundary", "criterion": "behavior", "dimension": "Input boundary",
                           "input": "An invalid input", "observable": "Returned result and caller state",
                           "expected": "The documented rejection", "expectation": {
                               "kind": "specification", "reference": "Owner acceptance requirement"}}]},
            "review": {"candidate": "CURRENT_CANDIDATE", "role": "EVIDENCE", "phase": "final",
                       "verdict": "REVISE", "coverage": "Describe evidence actually inspected",
                       "challenge": "Explain independent counterexamples", "criteria": [],
                       "case_assessments": [], "findings": [], "test_requests": [], "withdrawals": []}}


def brief_fields():
    return {"schemas": {name: schema(name) for name in ("challenge", "review")},
            "examples": examples(), "schema_guide": GUIDE + "#native-response-schemas"}
