"""Start and verify an SSH card from the machine running the user's browser.

The remote worker cannot create a forward on this machine. Run this helper here;
it uses the existing SSH configuration and never changes it or exposes a bind.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
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
               "prepare", "--task", args.task, "--title", args.title or args.task,
               "--execution", "remote"]
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


def connect(args):
    validate(args)
    base = Path(os.environ.get("FLIGHTCHECK_STATE_DIR") or
                Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "flightcheck")
    if not base.is_absolute():
        raise ValueError("Connection state must use an absolute private directory")
    key = hashlib.sha256(json.dumps([args.ssh, args.checkout, args.card_dir, args.remote_state_dir, args.task]).encode()).hexdigest()[:24]
    directory = maintainer.private_dir(maintainer.private_dir(maintainer.private_dir(base) / "connections") / key)
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
                if not available(local_port):
                    raise ValueError("The preserved local port is occupied or serves the wrong task/candidate; leave its owner running and restore the recorded forward")
                forward = f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}"
                log_path = directory / "ssh.log"
                with log_path.open("ab") as log:
                    log_start = log.tell()
                    process = subprocess.Popen(
                        # A multiplex client can hand the forward to an existing
                        # master and exit 0. Backgrounding also loses ownership.
                        # Keep this tunnel a directly managed foreground child;
                        # preserve the host's authentication and proxy settings.
                        ["ssh", "-N", "-T", "-S", "none", "-o", "ControlMaster=no",
                         "-o", "ControlPersist=no", "-o", "ForkAfterAuthentication=no",
                         "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                         "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                         "-L", forward, "--", args.ssh],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True,
                    )
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
            })
            confirmed.update(status="published", user_url=url, footer="FlightCheck: [&lt; status /&gt;](" + url + ")",
                             browser_reachability="verified", browser_rendering="unobserved",
                             guidance="Forwarded task and candidate verified on this machine. Open the status link in your regular browser.")
            return confirmed
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
    raise SystemExit(main())
