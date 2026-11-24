"""Bounded, task-owned progress publication; informational, never evidence proof."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime

from task_status import read_task, publish_locked, utc_time
from task_details import task_id, normalize_details

EVENT_SECONDS = 5
HEARTBEAT_SECONDS = 10
STALE_SECONDS = 30
OWNER_LEASE_SECONDS = 120
MAX_MONITOR_SECONDS = 28800
RECOVERY_ATTEMPTS = 3
RECOVERY_SECONDS = 15


class LeaseClock:
    """UTC timestamps describe observations; elapsed deadlines limit processes."""

    def __init__(self, monotonic=None):
        self.monotonic = time.monotonic if monotonic is None else monotonic
        self.lease = self.maximum = self.expiry = None

    def expired(self, freshness, started_at, wall):
        elapsed = self.monotonic()
        if self.maximum is None:
            self.maximum = elapsed + min(MAX_MONITOR_SECONDS, max(0, MAX_MONITOR_SECONDS - (wall - started_at)))
        expiry = freshness["owner_expires_at"]
        if expiry != self.expiry:
            self.expiry = expiry
            self.lease = elapsed + min(OWNER_LEASE_SECONDS, max(0, seconds(expiry) - wall))
        return elapsed >= self.lease, elapsed >= self.maximum


def seconds(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


@contextmanager
def locked(directory):
    directory = Path(directory)
    metadata = directory.stat()
    if directory.is_symlink() or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise ValueError("Progress storage must be private to the current user")
    with (directory / "card.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield directory


def snapshot(directory, task, candidate=None):
    data = read_task(Path(directory) / "status.json")
    if data["task"] != task_id(task) or (candidate is not None and data["candidate"] != candidate):
        raise ValueError("Progress belongs to another task or candidate")
    return data


def freshness_observation(data, now=None):
    """Compute ages on the serving host, without changing producer observations."""
    now = time.time() if now is None else now
    fresh = dict(data.get("freshness", {}))
    if not fresh:
        return None
    fresh.update(served_at=utc_time(now),
                 activity_age_seconds=now - seconds(fresh["activity_at"]),
                 publication_age_seconds=now - seconds(fresh["published_at"]),
                 heartbeat_age_seconds=now - seconds(fresh["publisher_heartbeat_at"]),
                 owner_remaining_seconds=seconds(fresh["owner_expires_at"]) - now)
    if fresh["state"] != "closed":
        if fresh["owner_remaining_seconds"] <= 0:
            fresh["state"] = "expired"
        elif fresh["heartbeat_age_seconds"] > STALE_SECONDS or min(fresh[key] for key in
                ("activity_age_seconds", "publication_age_seconds", "heartbeat_age_seconds")) < -.001:
            fresh["state"] = "stale"
    return fresh


def observe(directory, task, candidate=None, now=None):
    data = snapshot(directory, task, candidate)
    fresh = freshness_observation(data, now)
    if fresh is not None:
        data["freshness"] = fresh
    return data


def terminal(data):
    stages = data.get("stages", {})
    return (data.get("completeness", {}).get("ready") is True
            and stages.get("Final Verdict") == "completed" and len(stages) == 9
            and all(state in ("completed", "skipped") for state in stages.values())
            and not any(row["state"] == "running" and row["candidate"] == data["candidate"]
                        for row in data.get("activities", []))
            and not any(row["state"] in ("running", "pending", "failed", "interrupted", "unavailable")
                        and row["candidate"] == data["candidate"] for row in data.get("checks", [])))


def binding_key(checkout):
    return hashlib.sha256(os.fsencode(Path(checkout).resolve())).hexdigest()


def register(checkout, state, directory, task, details_source=None):
    """Remember explicitly prepared sources; never search an evidence archive."""
    import maintainer
    directory, checkout = Path(directory), Path(checkout).resolve()
    config_path = directory / "monitor.json"
    previous = maintainer.read_json(config_path)
    config = {"task": task_id(task), "checkout": str(checkout), "directory": str(directory),
              "token": previous.get("token") or uuid.uuid4().hex,
              "started_at": previous.get("started_at", time.time())}
    if details_source is not None:
        source = Path(details_source).resolve()
        if source == checkout or checkout in source.parents:
            raise ValueError("Progress details must remain outside the checkout")
        config["details_source"] = str(source)
        config["source_value"] = json.loads(source.read_text(encoding="utf-8"))
    else:
        for key in ("details_source", "source_value"):
            if key in previous:
                config[key] = previous[key]
    # Keep the same monitor for its bounded lifetime; resume after expiry starts
    # a new generation, rather than letting an old process adopt new ownership.
    if time.time() - config["started_at"] >= MAX_MONITOR_SECONDS:
        config.update(token=uuid.uuid4().hex, started_at=time.time())
    config["pid"] = previous.get("pid")
    maintainer.write_json(config_path, config)
    bindings = maintainer.private_dir(Path(state) / "active-checkouts")
    maintainer.write_json(bindings / (binding_key(checkout) + ".json"),
                          {"task": task, "directory": str(directory), "checkout": str(checkout)})
    return config


def start_monitor(directory):
    """Start only our recorded monitor generation, under card.lock."""
    import maintainer
    directory = Path(directory)
    config = maintainer.read_json(directory / "monitor.json")
    pid = config.get("pid")
    if type(pid) is int:
        process = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "uid=", "-o", "command="],
                                 capture_output=True, text=True)
        fields = process.stdout.strip().split(maxsplit=1)
        suffix = f"/status-card/progress.py monitor --directory {directory} --token {config['token']}"
        if len(fields) == 2 and fields[0] == str(os.geteuid()) and fields[1].endswith(suffix):
            return
    with (directory / "monitor.log").open("ab") as log:
        child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "monitor",
                                  "--directory", str(directory), "--token", config["token"]],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    config["pid"] = child.pid
    maintainer.write_json(directory / "monitor.json", config)


class Activity:
    """An explicit producer lease. Monitoring this record cannot renew it."""

    def __init__(self, directory, task, candidate, activity_id, kind, name, *, now=None):
        self.directory, self.task, self.candidate = Path(directory), task_id(task), candidate
        self.id, self.kind, self.name = activity_id, kind, name
        self.clock = time.time if now is None else now

    def _write(self, state=None, counts=None, summary=None):
        now = self.clock()
        with locked(self.directory):
            data = snapshot(self.directory, self.task, self.candidate)
            if data.get("freshness", {}).get("state") == "closed":
                raise ValueError("Resume the selected flight before registering work")
            activities = {row["id"]: row for row in data.get("activities", [])}
            prior = activities.get(self.id)
            if prior and (prior["kind"], prior["name"], prior["candidate"]) != (self.kind, self.name, self.candidate):
                raise ValueError("Activity identifier belongs to different work")
            if state is None and (not prior or prior["state"] != "running"):
                raise ValueError("Only a running activity can heartbeat")
            state = state or prior["state"]
            observed = utc_time(now) if not prior or prior["state"] != state or summary is not None else prior["observed_at"]
            activities[self.id] = dict(id=self.id, kind=self.kind, name=self.name, candidate=self.candidate,
                                       state=state, observed_at=observed, heartbeat_at=utc_time(now),
                                       expires_at=utc_time(now + OWNER_LEASE_SECONDS))
            if summary is not None or (prior and prior.get("summary")):
                activities[self.id]["summary"] = summary if summary is not None else prior["summary"]
            details = {}
            if self.kind == "check" and self.name in data.get("check_plan", []):
                rows = {(row["name"], row["candidate"]): row for row in data.get("checks", [])}
                current = rows.get((self.name, self.candidate), {})
                translated = {"completed": "passed", "failed": "failed", "interrupted": "interrupted",
                              "unavailable": "unavailable", "running": "running"}[state]
                row = dict(current, name=self.name, candidate=self.candidate, state=translated,
                           observed_at=observed, stale=False, counts=counts if counts is not None else current.get("counts", {}))
                if state == "unavailable":
                    row["reason"] = "Native check could not start."
                rows[(self.name, self.candidate)] = row
                details["checks"] = list(rows.values())
            publish_locked(self.directory / "status.json", data, details, now=now,
                           activities=list(activities.values()), heartbeat=True, renew_owner=True)
        return data

    def begin(self):
        return self._write("running")

    def heartbeat(self):
        return self._write()

    def update(self, summary):
        return self._write(summary=summary)

    def end(self, state="completed", counts=None):
        return self._write(state, counts)


def selected_activity(checkout, candidate, activity_id, name):
    """Find only an explicit prepare registration for this checkout."""
    import maintainer
    checkout = Path(checkout).resolve()
    selected = os.environ.get("FLIGHTCHECK_TASK_ID")
    try:
        common = maintainer.git_path(checkout, "--path-format=absolute", "--git-common-dir")
    except subprocess.SubprocessError:
        if selected:
            raise ValueError("The selected progress checkout is unavailable") from None
        return None
    base = Path(os.environ.get("FLIGHTCHECK_STATE_DIR") or
                Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "flightcheck")
    if os.environ.get("FLIGHTCHECK_STATE_DIR"):
        base = Path(os.environ["FLIGHTCHECK_STATE_DIR"])
    state = base.expanduser() / hashlib.sha256(os.fsencode(common)).hexdigest()[:24]
    if not state.is_dir():
        return None
    if selected:
        directory = state / "tasks" / task_id(selected)
    else:
        binding = maintainer.read_json(state / "active-checkouts" / (binding_key(checkout) + ".json"))
        if not binding or binding.get("checkout") != str(checkout):
            return None
        selected, directory = binding["task"], Path(binding["directory"])
    snapshot(directory, selected, candidate)
    return Activity(directory, selected, candidate, activity_id, "check", name)


def recover_listener(directory, task, expected_candidate=None, *, allow_incomplete=False):
    """Restore only the recorded endpoint. This never publishes or extends a lease."""
    import maintainer
    directory = Path(directory)
    deadline = time.monotonic() + RECOVERY_SECONDS
    expiry = None
    lease_deadline = None

    def authorized():
        nonlocal expiry, lease_deadline
        data = snapshot(directory, task, expected_candidate)
        fresh = freshness_observation(data)
        now = time.monotonic()
        if not fresh or fresh["state"] not in ("active", "closed") or fresh["owner_remaining_seconds"] <= 0:
            raise ValueError("Producer ownership expired or is unavailable. Run prepare to resume the preserved task route.")
        if fresh["owner_expires_at"] != expiry:
            expiry = fresh["owner_expires_at"]
            lease_deadline = now + min(OWNER_LEASE_SECONDS, fresh["owner_remaining_seconds"])
        if now >= lease_deadline:
            raise ValueError("Producer ownership expired. Run prepare to resume the preserved task route.")
        return data

    authorized()
    # Never hold card.lock while waiting for a service. Activity events retain
    # their independent publication latency during bounded listener recovery.
    with (directory / "listener.lock").open("a") as listener_lock:
        while True:
            authorized()
            try:
                fcntl.flock(listener_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("Listener recovery needs action on the preserved route: lifecycle lock timed out") from None
                time.sleep(min(.05, max(0, min(deadline, lease_deadline) - time.monotonic())))
        with locked(directory):
            data = authorized()
        endpoint = maintainer.read_json(directory / "endpoint.json")
        port = endpoint.get("port")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("No recorded listener route to recover")
        error = None
        for _ in range(RECOVERY_ATTEMPTS):
            data = authorized()
            if time.monotonic() >= deadline:
                break
            with locked(directory):
                data = authorized()
                endpoint = maintainer.read_json(directory / "endpoint.json")
            current = maintainer.current_card(task, port, data["candidate"],
                                             timeout=min(2, deadline - time.monotonic(), lease_deadline - time.monotonic()))
            data = authorized()
            if current and maintainer.card_matches(current, data):
                return endpoint
            if current:
                maintainer.stop_outdated_listener(directory / "status.json", data, endpoint)
            try:
                data = authorized()
                # start_listener never kills an existing port owner. A failed
                # bind preserves that owner and the recorded route.
                endpoint = maintainer.start_listener(directory / "status.json", data, port,
                                                     deadline=min(deadline, lease_deadline))
                with locked(directory):
                    authorized()
                    maintainer.write_json(directory / "endpoint.json", endpoint)
                return endpoint
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                error = exc
        raise ValueError("Listener recovery needs action on the preserved route: " + str(error or "deadline exceeded"))


class ListenerRecovery:
    """One bounded health worker, independent of the source publication clock."""

    def __init__(self, directory, token):
        self.directory, self.token = Path(directory), token
        self.thread = None
        self.exhausted = False

    def poll(self, task):
        if self.thread is not None and self.thread.is_alive():
            return
        if self.exhausted:
            import maintainer
            config = maintainer.read_json(self.directory / "monitor.json")
            if config.get("token") != self.token or config.get("recovery_error"):
                return
            # Explicit prepare clears the exhausted-attempt record. Monitoring
            # itself never clears it or grants another recovery budget.
            self.exhausted = False
        self.thread = threading.Thread(target=self._run, args=(task,), daemon=True, name="listener-recovery")
        self.thread.start()

    def _run(self, task):
        import maintainer
        try:
            recover_listener(self.directory, task)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.exhausted = True
            with locked(self.directory):
                config = maintainer.read_json(self.directory / "monitor.json")
                if config.get("token") != self.token:
                    return
                config["recovery_error"] = str(error)
                maintainer.write_json(self.directory / "monitor.json", config)
                data = snapshot(self.directory, task)
                fresh = freshness_observation(data)
                if fresh and fresh["state"] not in ("expired", "closed"):
                    publish_locked(self.directory / "status.json", data, {}, renew_owner=False,
                                   lifecycle="stale", action="Automatic listener recovery stopped. Run prepare to restore the preserved task route.")


class LinkPreparation:
    """One bounded lookup at a time, off the progress/heartbeat publication path."""

    def __init__(self):
        self.thread = None
        self.key = self.result = None
        self.started_at = None
        self.fetch_pending = False

    def poll(self, directory, checkout, task, candidate, links, *, fetch):
        from link_metadata import canonical, sha, prepare_publication
        key = sha(canonical([task, candidate, links]))
        # A newer source event can arrive while the previous batch is busy.
        # Retain its acquisition requirement until the latest batch starts.
        self.fetch_pending = self.fetch_pending or fetch
        if self.thread is not None and self.thread.is_alive():
            return None
        if self.key == key and not self.fetch_pending:
            result, self.result = self.result, None
            return result
        self.key, self.result = key, None
        self.started_at = time.time()
        acquire = self.fetch_pending

        def run():
            self.result = prepare_publication(Path(directory) / "status.json",
                {"mode": "flight", "task": task, "candidate": candidate},
                {"links": links}, checkout, fetch=acquire)["links"]

        self.thread = threading.Thread(target=run, daemon=True, name="link-metadata-preparation")
        self.thread.start()
        self.fetch_pending = False
        return None


def link_key(row):
    return tuple(row.get(k) for k in ("kind", "label", "url", "flight"))


def pending_links(rows, data, now):
    """Keep unchanged safe projections while new identities await preparation."""
    from link_metadata import bind, REASONS, iso, PREPARE_SECONDS
    prior = {link_key(row): row for row in data.get("links", [])}
    result = []
    for row in rows:
        old = prior.get(link_key(row))
        if old is not None:
            result.append(old)
        else:
            item = bind(row, data["task"], data["candidate"])
            if item["metadata"].get("identity"):
                item["metadata"].update(state="loading", ready=False, reason=REASONS["loading"],
                                        expires_at=iso(now + PREPARE_SECONDS + 0.2))
            result.append(item)
    return result


def completed_links(rows, data, started_at=None):
    """A late observation cannot replace a newer publication or erase safe bytes."""
    from link_metadata import seconds as metadata_seconds
    prior = {link_key(row): row for row in data.get("links", [])}
    result = []
    for item in rows:
        old = prior.get(link_key(item))
        old_meta = old.get("metadata", {}) if old else {}
        meta = item.get("metadata", {})
        # Candidate/content validation remains in normalize_details. Compare only
        # verified observation clocks for this exact item/task/candidate binding.
        incoming_at = metadata_seconds(meta["observed_at"]) if meta.get("observed_at") else started_at
        newer = (old_meta.get("candidate") == data["candidate"]
                 and old_meta.get("observed_at") and incoming_at is not None
                 and metadata_seconds(old_meta["observed_at"]) > incoming_at)
        if newer:
            item = old
        elif old and old.get("title") and not item.get("title"):
            item = dict(old)
            item["metadata"] = dict(old_meta, state="stale", ready=False,
                                    reason=meta.get("reason", "Last known details."), source="cache")
        result.append(item)
    return result


def monitor_step(directory, token, *, now=None, probe=True, runtime=None, recovery=None, metadata=None):
    """One deterministic observation tick; returns whether monitoring continues."""
    import maintainer
    directory = Path(directory)
    now = time.time() if now is None else now
    # Provider work never holds card.lock or delays ordinary progress/heartbeat.
    prepared = source_value = prepared_candidate = None
    if metadata is not None:
        observed = maintainer.read_json(directory / "monitor.json")
        if observed.get("token") == token and observed.get("details_source"):
            try:
                source_value = json.loads(Path(observed["details_source"]).read_text(encoding="utf-8"))
                if not isinstance(source_value, dict):
                    raise ValueError("Expected a details object")
                prior = observed.get("source_value", {})
                current = snapshot(directory, observed["task"])
                prepared_candidate = maintainer.candidate(Path(observed["checkout"]))
                links = source_value.get("links")
                if links is not None:
                    changed = links != prior.get("links")
                    pending = any(row.get("metadata", {}).get("candidate") != prepared_candidate
                                  for row in current.get("links", []))
                    if changed or pending or metadata.key is not None:
                        prepared = metadata.poll(directory, observed["checkout"], observed["task"],
                                                 prepared_candidate, links, fetch=changed)
            except (OSError, ValueError, TypeError, KeyError):
                source_value = None
    with locked(directory):
        config = maintainer.read_json(directory / "monitor.json")
        if config.get("token") != token:
            return False
        data = snapshot(directory, config["task"])
        fresh = data.get("freshness", {})
        expired = now >= seconds(fresh["owner_expires_at"])
        lifetime = now - config["started_at"] >= MAX_MONITOR_SECONDS
        if runtime is not None:
            lease_elapsed, max_elapsed = runtime.expired(fresh, config["started_at"], now)
            expired |= lease_elapsed
            lifetime |= max_elapsed
        if terminal(data):
            publish_locked(directory / "status.json", data, {}, now=now, renew_owner=False, lifecycle="closed")
            return False
        if expired or lifetime:
            publish_locked(directory / "status.json", data, {}, now=now, renew_owner=False, lifecycle="expired",
                           action="Run prepare to resume progress on the preserved task route.")
            return False
        details = {}
        current_candidate = maintainer.candidate(Path(config["checkout"]))
        candidate_changed = current_candidate != data["candidate"]
        if candidate_changed:
            data["candidate"] = current_candidate
        source = config.get("details_source")
        if source:
            try:
                value = json.loads(Path(source).read_text(encoding="utf-8"))
                before = config.get("source_value", {})
                details = {key: item for key, item in value.items() if before.get(key) != item}
                if "links" in details:
                    details["links"] = pending_links(details["links"], data, now)
                if (prepared is not None and current_candidate == prepared_candidate
                        and value.get("links") == (source_value or {}).get("links")):
                    normalized_links = normalize_details({"links": completed_links(prepared, data, metadata.started_at), "task": data["task"],
                                                           "candidate": current_candidate})["links"]
                    if normalized_links != data.get("links"):
                        details["links"] = completed_links(prepared, data, metadata.started_at)
                # Individual native results survive an unrelated source update.
                if "checks" in details:
                    old = {(row["name"], row["candidate"]): row for row in before.get("checks", [])}
                    current = {(row["name"], row["candidate"]): row for row in data.get("checks", [])}
                    for row in details["checks"]:
                        key = row["name"], row["candidate"]
                        if old.get(key) != row:
                            current[key] = row
                    details["checks"] = list(current.values())
                if details:
                    config["source_value"] = value
            except (OSError, ValueError, TypeError, KeyError):
                details = {}
        # Publish on the 8s source tick, leaving healthy processing margin
        # inside the 10s heartbeat bound instead of waiting for the 12s tick.
        heartbeat = now - seconds(fresh["publisher_heartbeat_at"]) >= HEARTBEAT_SECONDS - 2
        if details or heartbeat or candidate_changed:
            publish_locked(directory / "status.json", data, details, now=now, heartbeat=heartbeat, renew_owner=False,
                           action=fresh.get("action"))
            maintainer.write_json(directory / "monitor.json", config)
    if probe and recovery is not None:
        recovery.poll(config["task"])
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("monitor", "activity"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--token")
    parser.add_argument("--task")
    parser.add_argument("--candidate")
    parser.add_argument("--id")
    parser.add_argument("--kind", choices=("controller", "worker", "reviewer", "check"))
    parser.add_argument("--name")
    parser.add_argument("--state", choices=("running", "completed", "failed", "interrupted", "unavailable"))
    parser.add_argument("--summary")
    args = parser.parse_args()
    if args.command == "monitor":
        runtime = LeaseClock()
        recovery = ListenerRecovery(args.directory, args.token)
        metadata = LinkPreparation()
        # Leave one second of the event budget for healthy source/probe work.
        # Anchor ticks to elapsed time rather than adding that work to a 5s
        # sleep. Fault recovery has its separate bounded recovery deadline.
        cadence = max(1, EVENT_SECONDS - 1)
        next_tick = time.monotonic()
        while monitor_step(args.directory, args.token, runtime=runtime, recovery=recovery, metadata=metadata):
            next_tick += cadence
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                # After an outage, observe the source immediately without
                # replaying a backlog of missed health checks.
                next_tick = time.monotonic()
    else:
        if not all((args.task, args.candidate, args.id, args.kind, args.name, args.state)):
            parser.error("activity needs task, candidate, id, kind, name and state")
        activity = Activity(args.directory, args.task, args.candidate, args.id, args.kind, args.name)
        result = activity.begin() if args.state == "running" else activity.end(args.state)
        if args.summary:
            result = activity.update(args.summary) if args.state == "running" else result
        print(json.dumps({"task": result["task"], "candidate": result["candidate"], "freshness": result["freshness"]}))


if __name__ == "__main__":
    main()
