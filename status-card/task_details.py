"""Validate and project optional details for the live task card."""

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
LINK_KINDS = ("epic", "issue", "pr")
CHECK_STATES = ("pending", "running", "passed", "failed", "interrupted", "unavailable")
CI_STATES = ("pending", "running", "passed", "failed", "cancelled", "skipped", "unavailable")
COUNT_NAMES = ("passed", "failed", "errors", "skipped", "warnings")
EVENT_KINDS = ("repair", "rerun", "review")
STAGE_NAMES = (
    "Plan", "Implement", "Cheap Tests", "Interactive UI Approval",
    "Independent Code Review", "Authoritative Gates", "Skeptical Evidence Review",
    "Final Verdict", "PR & Merge",
)
STAGE_STATES = ("completed", "current", "skipped", "pending")


def task_id(value):
    if not isinstance(value, str) or not TASK_ID.fullmatch(value):
        raise ValueError("Invalid task ID")
    return value


def short_text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("Expected a short, nonempty status field")
    return value


def choice(value, options):
    if value not in options:
        raise ValueError(f"Expected one of: {', '.join(options)}")
    return value


def https_url(value):
    value = short_text(value)
    if any(char.isspace() or ord(char) < 32 or char == "\\" for char in value):
        raise ValueError("Invalid status link")
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username is not None or url.query:
        raise ValueError("Status links must use HTTPS without credentials or query parameters")
    # Accessing port also rejects invalid and out-of-range ports.
    if url.port == 0:
        raise ValueError("Invalid status link port")
    return value


def timestamp(value):
    observed = datetime.fromisoformat(short_text(value).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("Status observation times require a timezone")
    try:
        return observed.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except OverflowError as error:
        raise ValueError("Invalid status observation time") from error


def link(row):
    result = {
        "kind": choice(row.get("kind"), LINK_KINDS),
        "label": short_text(row.get("label")),
        "url": https_url(row.get("url")),
    }
    for field in ("created_at", "updated_at"):
        if row.get(field) is not None:
            result[field] = timestamp(row[field])
    for field in ("title", "description"):
        if row.get(field) not in (None, ""):
            result[field] = short_text(row[field])
    if result["kind"] == "issue" and row.get("flight") is not None:
        result["flight"] = task_id(row["flight"])
    return result


def tracked_flight(value):
    if not isinstance(value, dict):
        raise ValueError("Expected a tracked flight observation")
    candidate = short_text(value.get("candidate"))
    result = {"candidate": candidate}
    if value.get("stage") is not None:
        stage = choice(value["stage"], STAGE_NAMES)
        if value.get("stage_candidate") == candidate:
            result.update(stage=stage, stage_candidate=candidate)
    return result


def issue_stages(snapshot):
    """Project current stages for flights explicitly linked to issues."""
    current = {flight: record.get("stage") for flight, record in snapshot.get("tracked_flights", {}).items()}
    main_stages = snapshot.get("stages", {}) if snapshot["candidate"] else {}
    current[snapshot["task"]] = next((name for name, state in main_stages.items() if state == "current"), None)

    issues = {}
    for row in snapshot.get("links", []):
        flight = row.get("flight")
        if current.get(flight):
            issues.setdefault(flight, set()).add(row["url"])
    return {flight: {"stage": current[flight], "shared": len(urls) > 1} for flight, urls in issues.items()}


def observation(row, states):
    stale = row.get("stale", False)
    if type(stale) is not bool:
        raise ValueError("Expected a boolean for stale status")
    result = {
        "name": short_text(row.get("name")),
        "state": choice(row.get("state"), states),
        "candidate": short_text(row.get("candidate")),
        "observed_at": timestamp(row.get("observed_at")),
        "stale": stale,
    }
    if row.get("updated_at") is not None:
        result["updated_at"] = timestamp(row["updated_at"])
    return result


def check(row):
    result = observation(row, CHECK_STATES)
    if row.get("reason") is not None:
        result["reason"] = short_text(row["reason"])
    counts = row.get("counts", {})
    if not isinstance(counts, dict) or any(
        key not in COUNT_NAMES or type(value) is not int or value < 0
        for key, value in counts.items()
    ):
        raise ValueError("Check counts must be known, nonnegative integers")
    return {**result, "counts": counts}


def ci_run(row):
    result = observation(row, CI_STATES)
    attempt = row.get("attempt")
    if attempt is not None and (type(attempt) is not int or attempt < 1):
        raise ValueError("CI attempt must be a positive integer")
    return {
        **result,
        "kind": choice(row.get("kind"), ("pr", "post-merge")),
        "commit": short_text(row.get("commit")),
        "url": https_url(row["url"]) if row.get("url") is not None else None,
        "attempt": attempt,
    }


def event(row):
    return {
        "id": short_text(row.get("id")),
        "kind": choice(row.get("kind"), EVENT_KINDS),
        "candidate": short_text(row.get("candidate")),
        "observed_at": timestamp(row.get("observed_at")),
        "summary": short_text(row.get("summary")),
    }


def rows(value, convert):
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("Expected a list of status objects")
    return [convert(row) for row in value]


def stages(value):
    if not isinstance(value, dict) or value.keys() - set(STAGE_NAMES):
        raise ValueError("Expected FlightCheck workflow stage names")
    result = {name: choice(value.get(name, "pending"), STAGE_STATES) for name in STAGE_NAMES}
    if sum(state == "current" for state in result.values()) > 1:
        raise ValueError("Only one workflow stage can be current")
    active = False
    for name, state in result.items():
        if active and state == "completed":
            result[name] = "pending"
        active = active or state == "current"
    return result


def latest_activity(row):
    return max(row.get(field, "") for field in ("observed_at", "updated_at", "created_at"))


def newest_first(items):
    return sorted(items, key=latest_activity, reverse=True)


def normalize_details(data):
    result = {}
    if "check_plan" in data:
        plan = data["check_plan"]
        if not isinstance(plan, list) or any(not isinstance(name, str) for name in plan):
            raise ValueError("check_plan must list applicable check names")
        result["check_plan"] = [short_text(name) for name in plan]
        if len(set(plan)) != len(plan):
            raise ValueError("check_plan names must be unique")
    if "checks_unavailable" in data:
        result["checks_unavailable"] = short_text(data["checks_unavailable"])
    if "links_unavailable" in data:
        missing = data["links_unavailable"]
        if not isinstance(missing, dict) or missing.keys() - {"issue", "pr"}:
            raise ValueError("links_unavailable must explain missing issue/PR links")
        result["links_unavailable"] = {kind: short_text(reason) for kind, reason in missing.items()}
    for key in ("branch", "worktree"):
        if data.get(key) is not None:
            result[key] = short_text(data[key])
    if "stages" in data:
        result["stages"] = stages(data["stages"])
        declared = data.get("stages_declared", list(data["stages"]))
        if not isinstance(declared, list) or any(name not in STAGE_NAMES for name in declared):
            raise ValueError("Expected declared FlightCheck stages")
        # A retained declaration cannot fill a stage removed from the snapshot.
        result["stages_declared"] = [name for name in declared if name in data["stages"]]
    if "stage_updated_at" in data:
        times = data["stage_updated_at"]
        if not isinstance(times, dict) or times.keys() - set(STAGE_NAMES):
            raise ValueError("Expected timestamps for FlightCheck workflow stages")
        result["stage_updated_at"] = {name: timestamp(value) for name, value in times.items()}
    if "tracked_flights" in data:
        flights = data["tracked_flights"]
        if not isinstance(flights, dict):
            raise ValueError("Expected a map of tracked flight observations")
        result["tracked_flights"] = {task_id(flight): tracked_flight(record) for flight, record in flights.items()}
    if "links" in data:
        result["links"] = newest_first(rows(data["links"], link))
    for key, convert in (("checks", check), ("ci", ci_run), ("history", event)):
        if key in data:
            result[key] = newest_first(rows(data[key], convert))
    return result


def update_details(previous, details, candidate):
    """Apply explicit section updates and append only new, recorded events."""
    if not isinstance(details, dict) or details.keys() - {
        "branch", "worktree", "links", "checks", "ci", "events", "stages", "stage_updated_at", "tracked_flights",
        "check_plan", "checks_unavailable", "links_unavailable",
    }:
        raise ValueError("Expected a details object with supported task status fields")
    update = normalize_details(details)
    result = normalize_details(previous)
    if "branch" in details or "worktree" in details:
        result.pop("branch", None)
        result.pop("worktree", None)
    result.update(update)
    if update.get("check_plan") and "checks_unavailable" not in update:
        result.pop("checks_unavailable", None)
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    if "stages" in update or "stage_updated_at" in update:
        times = {**previous.get("stage_updated_at", {}), **update.get("stage_updated_at", {})}
        for name, state in update.get("stages", {}).items():
            before = previous.get("stages", {}).get(name, "pending")
            if state != before and name not in update.get("stage_updated_at", {}):
                times[name] = now
        result["stage_updated_at"] = times
    if previous.get("candidate") != candidate and "stages" not in update:
        result.pop("stages", None)
        result.pop("stages_declared", None)
        result.pop("stage_updated_at", None)
    identities = {"links": ("kind", "url"), "checks": ("name", "candidate"),
                  "ci": ("kind", "name", "candidate", "commit", "attempt")}
    for key, fields in identities.items():
        prior = {tuple(row.get(field) for field in fields): row for row in previous.get(key, [])}
        for row in update.get(key, []):
            before = prior.get(tuple(row.get(field) for field in fields))
            if not before or "updated_at" in row:
                continue
            ignored = {"created_at", "updated_at", "observed_at"}
            content = {name: value for name, value in row.items() if name not in ignored}
            old_content = {name: value for name, value in before.items() if name not in ignored}
            if content != old_content and row.get("observed_at", "") <= before.get("observed_at", ""):
                row["updated_at"] = now
            elif "updated_at" in before:
                row["updated_at"] = before["updated_at"]
    for key in ("checks", "ci"):
        if key in result:
            for row in result[key]:
                if row["candidate"] != candidate or (key not in update and previous.get("candidate") != candidate):
                    row["stale"] = True
    if "events" in details:
        history = {row["id"]: row for row in result.get("history", [])}
        for row in rows(details["events"], event):
            if row["id"] in history and history[row["id"]] != row:
                raise ValueError("An existing history event cannot change")
            history[row["id"]] = row
        result["history"] = list(history.values())
    return normalize_details(result)
