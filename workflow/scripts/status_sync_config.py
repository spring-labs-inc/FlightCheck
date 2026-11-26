"""Synchronization policy and status-only authority, without storage or I/O.

The common project configuration owns persistence, provenance and revision-safe
updates. Provider adapters resolve the opaque identities validated here.
"""

import copy
import hashlib
import json
import re


STATES = ("todo", "ready", "in_progress", "review", "done")


def _identity(value, name):
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Invalid status_sync identity: " + name)
    return value


def _provider(value):
    _identity(value, "provider")
    if not re.fullmatch(r"[a-z][a-z0-9._-]*", value):
        raise ValueError("Invalid status_sync provider identifier")
    return value


def normalize(supplied=None):
    """Return schema-1 policy; absence is disabled, never inferred authority.

    Unknown providers remain structurally valid so resolution can report an
    unsupported provider honestly. IDs are exact, opaque values, not labels.
    """
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, dict) or set(supplied) - {
            "schema", "mode", "provider", "project_id", "field_id", "options", "membership"}:
        raise ValueError("Invalid status_sync policy fields")
    value = copy.deepcopy(supplied)
    value.setdefault("schema", 1)
    value.setdefault("mode", "disabled")
    value.setdefault("provider", None)
    value.setdefault("project_id", None)
    value.setdefault("field_id", None)
    value.setdefault("options", {})
    value.setdefault("membership", "existing-only")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("Unsupported status_sync schema")
    if value["mode"] not in ("disabled", "advisory", "required"):
        raise ValueError("status_sync mode must be disabled, advisory or required")
    if value["membership"] != "existing-only":
        raise ValueError("status_sync membership supports existing-only; status authority cannot add items")
    for key in ("provider", "project_id", "field_id"):
        if value[key] is not None:
            (_provider if key == "provider" else lambda v: _identity(v, key))(value[key])
    options = value["options"]
    if not isinstance(options, dict) or (options and set(options) != set(STATES)):
        raise ValueError("status_sync options must map every logical state to its exact option ID")
    for key, option in options.items():
        _identity(option, "options." + key)
    if len(set(options.values())) != len(options):
        raise ValueError("status_sync option IDs must be distinct")
    if value["mode"] != "disabled" and (any(value[k] is None for k in ("provider", "project_id", "field_id"))
                                        or set(options) != set(STATES)):
        raise ValueError("Enabled status_sync requires provider, project, field and all option IDs")
    return value


def normalize_grant(supplied):
    """Validate one explicit exact-scope status grant, not other permissions."""
    fields = {"schema", "authority", "reference", "repository", "provider", "project_id",
              "field_id", "issues", "configuration_revision"}
    if not isinstance(supplied, dict) or set(supplied) != fields:
        raise ValueError("tracker_status grant requires exact status-only scope fields")
    value = copy.deepcopy(supplied)
    if type(value["schema"]) is not int or value["schema"] != 1 or value["authority"] != "owner":
        raise ValueError("tracker_status grant needs explicit owner authority and schema 1")
    for key in ("reference", "repository", "project_id", "field_id"):
        _identity(value[key], "grant." + key)
    _provider(value["provider"])
    issues = value["issues"]
    if (not isinstance(issues, list) or not issues
            or any(type(n) is not int or n <= 0 for n in issues) or len(set(issues)) != len(issues)):
        raise ValueError("tracker_status issues must be unique repository-qualified positive numbers")
    if (not isinstance(value["configuration_revision"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["configuration_revision"])):
        raise ValueError("tracker_status grant must bind the confirmed configuration revision")
    return value


def authorize(grant, repository, configuration, issue):
    """Report whether this status-only scope covers an active config snapshot.

    This pure check cannot write a provider, grant membership/closure/delivery,
    or turn project defaults into an active-flight decision.
    """
    try:
        authority = normalize_grant(grant)
    except ValueError as error:
        return {"authorized": False, "reason": "missing_authority", "detail": str(error)}
    if not isinstance(configuration, dict) or not isinstance(configuration.get("values"), dict):
        return {"authorized": False, "reason": "configuration_unconfirmed"}
    values = configuration["values"]
    try:
        policy = normalize(values.get("status_sync"))
    except ValueError as error:
        return {"authorized": False, "reason": "invalid_configuration", "detail": str(error)}
    if policy["mode"] == "disabled":
        return {"authorized": False, "reason": "disabled"}
    raw = (json.dumps(policy, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    metadata = values.get("_flightcheck", {})
    metadata = metadata.get("fields", {}) if isinstance(metadata, dict) else {}
    metadata = metadata.get("status_sync", {}) if isinstance(metadata, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    if (metadata.get("confirmed") is not True
            or metadata.get("value_sha256") != hashlib.sha256(raw).hexdigest()):
        return {"authorized": False, "reason": "configuration_unconfirmed"}
    if configuration.get("revision") != authority["configuration_revision"]:
        return {"authorized": False, "reason": "configuration_changed"}
    if (type(issue) is not int or issue not in authority["issues"] or repository != authority["repository"]
            or any(authority[k] != policy[k] for k in ("provider", "project_id", "field_id"))):
        return {"authorized": False, "reason": "scope_mismatch"}
    return {"authorized": True, "reason": "authorized"}
