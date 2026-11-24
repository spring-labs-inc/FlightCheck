"""Start and verify an SSH card from the machine running the user's browser.

The remote worker cannot create a forward on this machine. Run this helper here;
it uses the existing SSH configuration and never changes it or exposes a bind.
"""

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import select
import signal
import shutil
import tempfile
import shlex
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

import maintainer
from task_status import task_id, validate_task_url


def port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    return number


def remote_path(value):
    if not value.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Remote paths must be absolute paths without control characters")
    return value


def validate(args):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", args.ssh):
        raise ValueError("Use an SSH host alias or user@hostname, without SSH options")
    remote_path(args.checkout)
    if args.remote_state_dir:
        remote_path(args.remote_state_dir)
    if args.details:
        remote_path(args.details)
    path = PurePosixPath(args.card_dir)
    if path.is_absolute() or ".." in path.parts or str(path) != args.card_dir:
        raise ValueError("Card directory must be a normalized relative path in the remote checkout")
    if args.remote_python.startswith("/"):
        remote_path(args.remote_python)
    elif not re.fullmatch(r"[A-Za-z0-9_][\w.-]*", args.remote_python):
        raise ValueError("Use a remote Python executable name or absolute path")


def ssh_failure(phase, code, diagnostic="", log=None):
    detail = " ".join("".join(c if c.isprintable() else " " for c in diagnostic).split())[-1000:]
    message = (f"{phase} failed (SSH exit code {code})" if code is not None else
               f"{phase} did not verify the expected task and candidate before the timeout")
    if detail:
        message += ": " + detail
    if log:
        message += "; SSH log: " + str(log)
    return ValueError(message)


def prepare_remote(args, user_url=None):
    command = [args.remote_python, "-B", str(PurePosixPath(args.card_dir) / "reply.py"),
               "prepare", "--task", args.task, "--execution", "remote"]
    if args.title is not None:
        command += ["--title", args.title]
    if args.details:
        command += ["--details", args.details]
    if user_url:
        command += ["--user-url", user_url]
    if args.remote_state_dir:
        command = ["env", "FLIGHTCHECK_STATE_DIR=" + args.remote_state_dir, *command]
    script = "cd " + shlex.quote(args.checkout) + " && " + shlex.join(command)
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "--", args.ssh, script],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20,
    )
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise ssh_failure("Remote preparation", result.returncode,
                          result.stderr or "No valid startup JSON; check SSH access and the installed card helper") from None
    if not isinstance(data, dict):
        raise ssh_failure("Remote preparation", result.returncode, "Startup response must be a JSON object")
    if (result.returncode not in (0, 1) or data.get("task") != args.task
            or data.get("publication") != "verified"
            or not data.get("completeness", {}).get("ready")
            or not re.fullmatch(r"[a-f0-9]{64}", data.get("candidate", ""))):
        raise ValueError("Remote card is not ready: " + str(data.get("error") or data.get("guidance") or "SSH preparation failed"))
    validate_task_url(data.get("host_url", ""), args.task)
    return data


def available(number):
    with socket.socket() as probe:
        # SSH reuses a recently closed loopback listener. TIME_WAIT is not
        # an active port owner; use the same bind policy for this probe.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", number))
        except OSError:
            return False
    return True


def connection_directory(args):
    validate(args)
    base = Path(os.environ.get("FLIGHTCHECK_STATE_DIR") or
                Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "flightcheck")
    if not base.is_absolute():
        raise ValueError("Connection state must use an absolute private directory")
    if base.is_symlink():
        raise ValueError("Connection state cannot use a symlink directory")
    base = maintainer.private_dir(base).resolve()
    key = hashlib.sha256(json.dumps([args.ssh, args.checkout, args.card_dir, args.remote_state_dir, args.task]).encode()).hexdigest()[:24]
    directory = maintainer.private_dir(maintainer.private_dir(maintainer.private_dir(base) / "connections") / key)
    return directory


def establish(args, directory, allow_start=True):
    with (directory / "connection.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = maintainer.read_json(directory / "connection.json")
        remote = prepare_remote(args)
        remote_port = urlsplit(remote["host_url"]).port
        local_port = args.local_port or saved.get("local_port") or remote_port
        port(local_port)
        if saved and (saved.get("local_port") != local_port or saved.get("remote_port") != remote_port):
            raise ValueError("The recorded route changed; reconcile the saved connection explicitly")
        url = maintainer.card_url(args.task, local_port)
        process = None
        try:
            live = (maintainer.current_card(args.task, local_port, remote["candidate"], remote_port)
                    if saved else None)
            if not live:
                if not allow_start:
                    raise ValueError("The existing route monitor owns recovery; wait for it or restore the recorded forward")
                if not available(local_port):
                    raise ValueError("The preserved local port is occupied or serves the wrong task/candidate; leave its owner running and restore the recorded forward")
                log_path = directory / "ssh.log"
                log_start = log_path.stat().st_size if log_path.exists() else 0
                process = start_forward(args, directory, local_port, remote_port)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline and process.poll() is None:
                    live = maintainer.current_card(args.task, local_port, remote["candidate"], remote_port)
                    if live:
                        break
                    time.sleep(.05)
                if not live or process.poll() is not None:
                    with log_path.open("rb") as log:
                        log.seek(max(log_start, log_path.stat().st_size - 4096))
                        diagnostic = log.read(4096).decode("utf-8", errors="replace")
                    raise ssh_failure("SSH forward", process.poll(), diagnostic, log_path)
            confirmed = prepare_remote(args, url)
            if (confirmed.get("user_url") != url or confirmed["candidate"] != remote["candidate"]
                    or confirmed["host_url"] != remote["host_url"]
                    or not maintainer.current_card(args.task, local_port, remote["candidate"], remote_port)):
                raise ValueError("Remote card or forwarded route changed during verification; retry on the same route")
            maintainer.write_json(directory / "connection.json", {
                "task": args.task, "local_port": local_port, "remote_port": remote_port,
                "user_url": url, "candidate": remote["candidate"],
                "pid": process.pid if process else saved.get("pid"),
                "supervisor_pid": saved.get("supervisor_pid"),
                "helper_directory": saved.get("helper_directory"),
            })
            confirmed.update(status="published", user_url=url, footer="FlightCheck: [&lt; status /&gt;](" + url + ")",
                             browser_reachability="verified", browser_rendering="unobserved",
                             guidance="Forwarded task and candidate verified on this machine. Open the status link in your regular browser.")
            return confirmed, process
        except BaseException:
            # Only a process created by this attempt belongs to us. A reused
            # route or unrelated port owner must never be signalled by PID.
            if process:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise



MONITOR_INTERVAL = 5
MONITOR_LIFETIME = 8 * 60 * 60
OWNER_LEASE = 120
STALE_AFTER = 30
RECOVERY_ATTEMPTS = 3
RECOVERY_DEADLINE = 15


def stop_child(process):
    # A saved PID is never an ownership handle. Only this runtime's child is.
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def start_forward(args, directory, local_port, remote_port):
    forward = f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}"
    with (directory / "ssh.log").open("ab") as log:
        return subprocess.Popen(
            ["ssh", "-N", "-T", "-S", "none", "-o", "ControlMaster=no",
             "-o", "ControlPersist=no", "-o", "ForkAfterAuthentication=no",
             "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
             "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
             "-L", forward, "--", args.ssh], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)


class RouteMismatch(ValueError):
    pass


def remote_observation(args, recover=False, timeout=4.5):
    command = [args.remote_python, "-B", str(PurePosixPath(args.card_dir) / "reply.py"),
               "recover" if recover else "observe", "--task", args.task, "--execution", "remote"]
    if args.remote_state_dir:
        command = ["env", "FLIGHTCHECK_STATE_DIR=" + args.remote_state_dir, *command]
    script = "cd " + shlex.quote(args.checkout) + " && " + shlex.join(command)
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "--", args.ssh, script],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise ssh_failure("Remote observation", result.returncode, result.stderr) from None
    if isinstance(data, dict) and (data.get("error_code") == "wrong_task"
                                   or (data.get("task") is not None and data.get("task") != args.task)):
        raise RouteMismatch("Wrong remote task; leave its owner running")
    if result.returncode or not isinstance(data, dict) or data.get("task") != args.task:
        raise ValueError("Remote observation unavailable: " + str(data.get("error", "wrong task") if isinstance(data, dict) else "invalid response"))
    return data


def forward_snapshot(number, task, timeout=2):
    # Bound the whole response in a disposable read-only process, including
    # trickled bytes. The monitor must distinguish a wrong task from no HTTP.
    try:
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                 "--probe-forward", str(number), task], capture_output=True, text=True, timeout=timeout)
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class OwnerExpired(ValueError):
    pass


def observed_lease(observed, task, host_url, started, previous_expiry, previous_deadline):
    """Bind a remote freshness observation to elapsed time, never a new lease."""
    if observed.get("host_url") != host_url:
        raise ValueError("Worker route changed; restore the recorded task route")
    snapshot = observed.get("snapshot", {})
    if snapshot.get("task") != task:
        raise RouteMismatch("Wrong task; leave its owner running")
    freshness = snapshot.get("freshness", {})
    remaining = freshness.get("owner_remaining_seconds")
    age = freshness.get("heartbeat_age_seconds")
    if (not isinstance(remaining, (int, float)) or isinstance(remaining, bool)
            or not isinstance(age, (int, float)) or isinstance(age, bool)
            or not math.isfinite(remaining) or not math.isfinite(age)
            or freshness.get("state") not in ("active", "stale", "expired", "closed")):
        raise ValueError("Worker producer ownership/freshness is unavailable")
    expiry = freshness.get("owner_expires_at")
    if not isinstance(expiry, str) or not expiry:
        raise ValueError("Worker ownership expiry identity is unavailable")
    # The observation was made no earlier than request start. Counting from
    # response receipt would grant transport/recovery time as extra ownership.
    limit = started + min(OWNER_LEASE, max(0, remaining))
    if expiry == previous_expiry:
        limit = min(previous_deadline, limit)
    return snapshot, freshness, expiry, limit


def monitor(args, directory, initial, process, clock=time.monotonic, sleep=time.sleep,
            lifetime=MONITOR_LIFETIME, interval=MONITOR_INTERVAL):
    deadline = clock() + lifetime
    lease_deadline = clock() + OWNER_LEASE
    attempts = 0
    observed_expiry = None
    local_port = urlsplit(initial["user_url"]).port
    remote_port = urlsplit(initial["host_url"]).port
    state = {"task": args.task, "user_url": initial["user_url"], "status": "monitoring",
             "transport": "verified", "attempts": 0, "supervisor_pid": os.getpid()}

    def record(status, **fields):
        state.update(status=status, attempts=attempts, **fields)
        maintainer.write_json(directory / "monitor.json", state)

    def authorized_timeout(limit):
        remaining = min(deadline, lease_deadline) - clock()
        if remaining <= 0:
            raise OwnerExpired("Producer ownership lease ended; resume the selected flight")
        return min(limit, remaining)

    try:
        record("monitoring")
        while clock() < deadline:
            sleep(min(interval, max(0, min(deadline, lease_deadline) - clock())))
            if clock() >= deadline:
                break
            if clock() >= lease_deadline:
                record("producer_expired", error="Producer ownership lease ended; resume the selected flight")
                break
            observation_started = clock()
            try:
                observed = remote_observation(args, timeout=authorized_timeout(4.5))
            except RouteMismatch as error:
                record("unavailable", error=str(error))
                break
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                if clock() >= lease_deadline:
                    record("producer_expired", error="Producer ownership lease ended; resume the selected flight")
                    break
                attempts += 1
                record("disconnected", transport="disconnected", error=str(error))
                if attempts >= RECOVERY_ATTEMPTS or clock() >= lease_deadline:
                    break
                continue
            try:
                snapshot, freshness, observed_expiry, lease_deadline = observed_lease(
                    observed, args.task, initial["host_url"], observation_started, observed_expiry, lease_deadline)
            except ValueError as error:
                record("unavailable", error=str(error))
                break
            if freshness.get("state") == "closed":
                remaining = min(deadline, lease_deadline) - clock()
                # Closing ends active ownership. Retain an already owned final
                # route without starting a probe after the lease has ended.
                retained = (bool(maintainer.current_card(args.task, local_port, snapshot.get("candidate"), remote_port,
                                                         timeout=min(2, remaining))) if remaining > 0
                            else bool(process and process.poll() is None))
                record("producer_closed", transport="verified", forward_retained=retained,
                       ownership="relinquished" if retained else "ended")
                break
            if freshness.get("state") == "expired" or clock() >= lease_deadline:
                record("producer_expired", transport="verified",
                       error="Producer ownership lease ended; resume the selected flight")
                break
            if freshness.get("state") == "stale" or not 0 <= freshness["heartbeat_age_seconds"] <= STALE_AFTER or snapshot.get("candidate") != observed.get("candidate"):
                record("producer_stale", transport="verified")
                continue
            expected = snapshot["candidate"]
            try:
                authorized_timeout(RECOVERY_DEADLINE)
                if observed.get("publication") != "verified":
                    if attempts >= RECOVERY_ATTEMPTS:
                        record("unavailable", error="Worker listener recovery budget exhausted")
                        break
                    recovery_timeout = authorized_timeout(RECOVERY_DEADLINE)
                    attempts += 1
                    recovery_started = clock()
                    observed = remote_observation(args, recover=True, timeout=recovery_timeout)
                    snapshot, freshness, observed_expiry, lease_deadline = observed_lease(
                        observed, args.task, initial["host_url"], recovery_started, observed_expiry, lease_deadline)
                    if freshness["state"] == "expired":
                        raise OwnerExpired("Producer ownership lease ended; resume the selected flight")
                    if freshness["state"] == "closed":
                        record("producer_closed", transport="verified", forward_retained=bool(process and process.poll() is None),
                               ownership="relinquished")
                        break
                    authorized_timeout(RECOVERY_DEADLINE)
                    if (freshness["state"] == "stale" or not 0 <= freshness["heartbeat_age_seconds"] <= STALE_AFTER
                            or snapshot.get("candidate") != observed.get("candidate")):
                        record("producer_stale", transport="verified")
                        continue
                    expected = snapshot["candidate"]
                    if observed.get("publication") != "verified":
                        raise ValueError("Worker listener could not restore the recorded route")
                local = forward_snapshot(local_port, args.task, timeout=authorized_timeout(2))
                authorized_timeout(2)
                if local and (local.get("task") != args.task or local.get("publicationPort") != remote_port):
                    record("unavailable", error="Wrong forwarded task or publication port; leave its owner running")
                    break
                if local and local.get("candidate") != expected:
                    record("producer_stale", transport="verified")
                    continue
                live = maintainer.current_card(args.task, local_port, expected, remote_port,
                                               timeout=authorized_timeout(2))
                authorized_timeout(2)
                if not live:
                    if attempts >= RECOVERY_ATTEMPTS:
                        record("unavailable", error="SSH route recovery budget exhausted")
                        break
                    # Stop only our exact runtime child, never connection.json's PID.
                    authorized_timeout(RECOVERY_DEADLINE)
                    if process is None and not available(local_port):
                        record("unavailable", error="Ownership unavailable: restore or stop the recorded forward on the browser machine, then rerun the same connector command and port")
                        break
                    authorized_timeout(RECOVERY_DEADLINE)
                    attempts += 1
                    stop_child(process)
                    authorized_timeout(RECOVERY_DEADLINE)
                    if not available(local_port):
                        record("unavailable", error="Recorded local port remains occupied; leave its owner running")
                        break
                    authorized_timeout(RECOVERY_DEADLINE)
                    process = start_forward(args, directory, local_port, remote_port)
                    authorized_timeout(RECOVERY_DEADLINE)
                    recovery_end = min(deadline, lease_deadline, clock() + RECOVERY_DEADLINE)
                    while clock() < recovery_end and process.poll() is None:
                        ready = maintainer.current_card(args.task, local_port, expected, remote_port,
                                                        timeout=min(authorized_timeout(2), recovery_end - clock()))
                        authorized_timeout(2)
                        if ready:
                            break
                        sleep(min(.1, max(0, recovery_end - clock())))
                    else:
                        authorized_timeout(RECOVERY_DEADLINE)
                        raise ValueError("SSH route did not recover before its deadline")
                    if process.poll() is not None:
                        raise ValueError("Owned SSH forward exited during recovery")
                    with (directory / "connection.lock").open("a") as lock:
                        while True:
                            authorized_timeout(RECOVERY_DEADLINE)
                            try:
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                break
                            except BlockingIOError:
                                sleep(authorized_timeout(.05))
                        authorized_timeout(RECOVERY_DEADLINE)
                        saved = maintainer.read_json(directory / "connection.json")
                        authorized_timeout(RECOVERY_DEADLINE)
                        saved.update(pid=process.pid, candidate=expected)
                        maintainer.write_json(directory / "connection.json", saved)
                authorized_timeout(RECOVERY_DEADLINE)
                record("monitoring", transport="verified", candidate=expected, error=None)
            except OwnerExpired as error:
                record("producer_expired", error=str(error))
                break
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                if clock() >= lease_deadline:
                    record("producer_expired", error="Producer ownership lease ended; resume the selected flight")
                    break
                record("disconnected", transport="disconnected", error=str(error))
                if attempts >= RECOVERY_ATTEMPTS:
                    break
        if clock() >= deadline:
            record("expired", error="Monitor lifetime ended; rerun the connector to resume the same route")
        return state
    finally:
        if not state.get("forward_retained"):
            stop_child(process)


def supervise(args):
    directory = connection_directory(args)
    with (directory / "monitor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            owns_monitor = True
        except BlockingIOError:
            owns_monitor = False
        process = None
        retained = False
        try:
            result, process = establish(args, directory, allow_start=owns_monitor)
            result["monitor"] = "active" if owns_monitor else "existing"
            result["monitor_lifetime_seconds"] = MONITOR_LIFETIME
            if owns_monitor:
                saved = maintainer.read_json(directory / "connection.json")
                saved["supervisor_pid"] = os.getpid()
                saved["helper_directory"] = str(Path(__file__).resolve().parent)
                maintainer.write_json(directory / "connection.json", saved)
            print(json.dumps(result), flush=True)
            sys.stdout.close()
            if owns_monitor:
                final = monitor(args, directory, result, process)
                retained = final.get("forward_retained", False)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            if sys.stdout.closed:
                maintainer.write_json(directory / "monitor.json", {"task": args.task, "status": "unavailable",
                                      "transport": "unobserved", "error": str(error)})
            else:
                print(json.dumps({"status": "unavailable", "task": args.task,
                                  "footer": "FlightCheck: &lt; status /&gt;", "error": str(error),
                                  "browser_reachability": "unobserved", "browser_rendering": "unobserved"}), flush=True)
            return 1
        finally:
            if not retained:
                stop_child(process)
    return 0


def bind_helpers(directory):
    # Installed CLI source is materialized in a temporary directory. Bind only
    # the four imported Python helpers privately so later bounded probes survive
    # that directory disappearing; this is not a project installation.
    names = ("connect.py", "maintainer.py", "task_status.py", "task_details.py")
    sources = {name: Path(__file__).with_name(name).read_bytes() for name in names}
    identity = hashlib.sha256(json.dumps({name: hashlib.sha256(body).hexdigest()
                                         for name, body in sources.items()}, sort_keys=True).encode()).hexdigest()
    root = maintainer.private_dir(directory / "helpers")
    with (directory / "helpers.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = root / identity
        if target.exists() or target.is_symlink():
            maintainer.private_dir(target)
            if {path.name for path in target.iterdir()} != set(names):
                raise ValueError("Private connector helper binding changed; restore its exact source bytes")
            for name, body in sources.items():
                bound = target / name
                if bound.is_symlink() or not bound.is_file() or bound.read_bytes() != body:
                    raise ValueError("Private connector helper binding changed: " + name)
            return target
        pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
        try:
            for name, body in sources.items():
                (pending / name).write_bytes(body)
                (pending / name).chmod(0o600)
            pending.rename(target)
        finally:
            if pending.exists():
                shutil.rmtree(pending)
        return target


def connect(args):
    directory = connection_directory(args)
    helpers = bind_helpers(directory)
    fd, name = tempfile.mkstemp(prefix="supervisor-", suffix=".json", dir=directory)
    with os.fdopen(fd, "w") as stream:
        json.dump(vars(args), stream)
    with (directory / "monitor.log").open("ab") as log:
        child = subprocess.Popen([sys.executable, "-B", str(helpers / "connect.py"), "--supervise", name],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, start_new_session=True)
    try:
        deadline = time.monotonic() + 60
        line = b""
        while b"\n" not in line and len(line) < 1024 * 1024:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([child.stdout], [], [], remaining)[0]:
                raise ValueError("SSH route supervisor did not report startup before timeout")
            chunk = os.read(child.stdout.fileno(), 65536)
            if not chunk:
                raise ValueError("SSH route supervisor exited before reporting startup; inspect monitor.log")
            line += chunk
        return json.loads(line)
    except BaseException:
        stop_child(child)
        raise
    finally:
        child.stdout.close()
        Path(name).unlink(missing_ok=True)


def internal_main():
    if len(sys.argv) == 3 and sys.argv[1] == "--supervise":
        args = argparse.Namespace(**json.loads(Path(sys.argv[2]).read_text()))
        Path(sys.argv[2]).unlink(missing_ok=True)
        def interrupted(signum, frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        return supervise(args)
    if len(sys.argv) == 4 and sys.argv[1] == "--probe-forward":
        from http.client import HTTPConnection
        connection = HTTPConnection("127.0.0.1", port(sys.argv[2]), timeout=.75)
        try:
            connection.request("GET", "/task/" + task_id(sys.argv[3]) + "/status.json")
            response = connection.getresponse()
            print(json.dumps(json.loads(response.read(1024 * 1024))))
            return 0
        except (OSError, ValueError):
            print("null")
            return 1
        finally:
            connection.close()
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh", required=True, help="Existing SSH host alias, used from the browser machine")
    parser.add_argument("--checkout", required=True, help="Absolute project path on the SSH worker")
    parser.add_argument("--task", type=task_id, required=True)
    parser.add_argument("--title")
    parser.add_argument("--card-dir", default=".flightcheck/status-card")
    parser.add_argument("--remote-python", default="python3")
    parser.add_argument("--remote-state-dir")
    parser.add_argument("--details", help="Existing initialized private details file on the SSH worker")
    parser.add_argument("--local-port", type=port)
    args = parser.parse_args()
    try:
        result = connect(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {"status": "unavailable", "task": args.task, "footer": "FlightCheck: &lt; status /&gt;",
                  "error": str(error), "browser_reachability": "unobserved", "browser_rendering": "unobserved"}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "published" else 1


if __name__ == "__main__":
    internal = internal_main()
    raise SystemExit(main() if internal is None else internal)
