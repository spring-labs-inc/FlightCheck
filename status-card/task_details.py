"""Validate and project optional details for the live task card."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

LINK_KINDS = ("issue", "epic", "pr")
CHECK_STATES = ("pending", "running", "passed", "failed", "interrupted", "unavailable")
CI_STATES = ("pending", "running", "passed", "failed", "cancelled", "skipped", "unavailable")
COUNT_NAMES = ("passed", "failed", "errors", "skipped", "warnings")
EVENT_KINDS = ("repair", "rerun", "review")


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
    return {
        "kind": choice(row.get("kind"), LINK_KINDS),
        "label": short_text(row.get("label")),
        "url": https_url(row.get("url")),
    }


def observation(row, states):
    stale = row.get("stale", False)
    if type(stale) is not bool:
        raise ValueError("Expected a boolean for stale status")
    return {
        "name": short_text(row.get("name")),
        "state": choice(row.get("state"), states),
        "candidate": short_text(row.get("candidate")),
        "observed_at": timestamp(row.get("observed_at")),
        "stale": stale,
    }


def check(row):
    result = observation(row, CHECK_STATES)
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


def normalize_details(data):
    result = {}
    for key, convert in (("links", link), ("checks", check), ("ci", ci_run), ("history", event)):
        if key in data:
            result[key] = rows(data[key], convert)
    return result


def update_details(previous, details, candidate):
    """Apply explicit section updates and append only new, recorded events."""
    if not isinstance(details, dict) or details.keys() - {"links", "checks", "ci", "events"}:
        raise ValueError("Expected a details object with links, checks, ci, or events")
    update = normalize_details(details)
    result = {**normalize_details(previous), **update}
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
        result["history"] = sorted(history.values(), key=lambda row: row["observed_at"], reverse=True)
    return result
