"""Prepare a portable flight card and check each controller reply before sending.

This explicit controller command is not a native message interception hook.
Ordinary/reviewer contexts return before accessing Git, state or reply content.
"""

import argparse
import fcntl
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

import maintainer
from task_status import task_id, validate_task_url

PHASES = ("start", "update", "approval", "blocker", "repair", "resume", "end")


def published_card(task, port, candidate):
    return maintainer.current_card(task, port, candidate) if port else None


def read_object(path):
    value = maintainer.read_json(path)
    if not isinstance(value, dict):
        raise ValueError("Expected a private state object: " + path.name)
    return value


def execution_mode(requested):
    if requested != "auto":
        return requested
    return "remote" if any(os.environ.get(key) for key in
                           ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "CODESPACES", "REMOTE_CONTAINERS")) else "local"


def browser_url(value, task):
    return validate_task_url(value, task)


def footer(url):
    label = "&lt; status /&gt;"
    return "FlightCheck: " + (f"[{label}]({url})" if url else label)


def route_record(previous, task, host_url, execution, supplied):
    if previous and previous.get("task") != task:
        raise ValueError("The prepared route belongs to another task")
    if previous.get("user_url"):
        browser_url(previous["user_url"], task)
    if supplied:
        browser_url(supplied, task)
        if previous.get("user_url") and previous["user_url"] != supplied:
            raise ValueError("The task already has a browser URL; preserve it and reconcile forwarding explicitly")
    # A loopback URL used on the checkout host does not establish forwarding
    # after the task moves to a remote session.
    approved = supplied or (previous.get("user_url") if previous.get("execution") == execution else None)
    user_url = approved or (host_url if execution == "local" else None)
    return {"task": task, "host_url": host_url, "user_url": user_url, "execution": execution}


def observation(record, candidate, publication, verdict="Pending"):
    url = record.get("user_url") or record.get("host_url")
    remote_pending = record["execution"] == "remote" and not record.get("user_url")
    result = {"task": record["task"], "candidate": candidate,
              "status": "published" if publication and not remote_pending else "unavailable",
              "publication": "verified" if publication else "unavailable",
              "verdict": verdict if publication else "Pending",
              "execution": record["execution"], "host_url": record.get("host_url"),
              "user_url": record.get("user_url"), "footer": footer(url),
              "browser_reachability": "unobserved", "browser_rendering": "unobserved"}
    if remote_pending:
        port = urlsplit(record["host_url"]).port if record.get("host_url") else "HOST_PORT"
        result["guidance"] = ("The card is on the remote checkout host. Arrange approved loopback forwarding, "
                              f"for example ssh -N -L 127.0.0.1:LOCAL_PORT:127.0.0.1:{port} HOST, "
                              "then prepare again with --user-url and the forwarded task URL. "
                              "The checkout-host URL alone is not a reachable browser route.")
    else:
        result["guidance"] = ("Open the live card in your regular browser at " + str(url)
                              + ". Continue terminal work independently; a text card is unnecessary. "
                              "Host HTTP publication does not prove browser reachability or rendering.")
    if not publication:
        result["guidance"] = ("Card publication unavailable; run prepare to restore the same listener. "
                              "Keep the known task link while reporting this blocker; browser reachability and rendering remain unobserved.")
    return result


def prepare(checkout, state, args):
    directory = maintainer.task_dir(state, args.task)
    with (directory / "reply.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_object(directory / "reply-route.json")
        endpoint = read_object(directory / "endpoint.json")
        if endpoint and (type(endpoint.get("port")) is not int or not 1 <= endpoint["port"] <= 65535):
            raise ValueError("Invalid private task publication port")
        host_url = maintainer.card_url(args.task, endpoint["port"]) if endpoint.get("port") else None
        mode = execution_mode(args.execution)
        # Reject conflicting routes before publication or state changes.
        record = route_record(previous, args.task, host_url, mode, args.user_url)
        try:
            maintainer.show_card(checkout, state, argparse.Namespace(
                task=args.task, title=args.title or "FlightCheck " + args.task,
                summary=args.summary, details=args.details, verdict=args.verdict,
                verdict_candidate=args.verdict_candidate, session=args.session))
            endpoint = read_object(directory / "endpoint.json")
            record = route_record(previous, args.task, maintainer.card_url(args.task, endpoint["port"]), mode, args.user_url)
            maintainer.write_json(directory / "reply-route.json", record)
            current = maintainer.candidate(checkout)
            live = published_card(args.task, endpoint["port"], current)
            result = observation(record, current, bool(live), live["verdict"] if live else "Pending")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            result = observation(record, maintainer.candidate(checkout), False)
            result["error"] = str(error)
        return result


def check(checkout, state, args):
    directory = maintainer.task_dir(state, args.task)
    endpoint = read_object(directory / "endpoint.json")
    record = read_object(directory / "reply-route.json")
    if not record or record.get("task") != args.task:
        raise ValueError("No prepared task route; run prepare for this selected flight")
    browser_url(record["host_url"], args.task)
    if record["host_url"] != maintainer.card_url(args.task, endpoint.get("port")):
        raise ValueError("Prepared route differs from the task's publication endpoint")
    if record.get("user_url"):
        browser_url(record["user_url"], args.task)
    mode = execution_mode(args.execution)
    if mode != record["execution"]:
        raise ValueError("Execution context changed; prepare the route again before replying")
    if args.user_url and args.user_url != record.get("user_url"):
        raise ValueError("Use the prepared task's exact browser URL")
    current = maintainer.candidate(checkout)
    published = published_card(args.task, endpoint.get("port"), current)
    result = observation(record, current, bool(published), published["verdict"] if published else "Pending")
    if not args.reply_file:
        raise ValueError("check requires --reply-file with the exact controller reply")
    text = args.reply_file.read_text(encoding="utf-8")
    if not maintainer.has_footer(text, result["footer"]):
        result.update(status="blocked", error="Put the exact task footer last, in its own paragraph outside fences; put verdicts above it")
    elif any(value.strip() != result["verdict"] for value in re.findall(r"^Verdict:([^\n]+)$", text, re.M)):
        result.update(status="blocked", error="The reply verdict must match the current candidate's recorded verdict")
    result["phase"] = args.phase
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "check"))
    parser.add_argument("--context", choices=("controller", "ordinary", "reviewer"), default="controller")
    parser.add_argument("--task", type=task_id)
    parser.add_argument("--title")
    parser.add_argument("--session", default=os.environ.get("CODEX_THREAD_ID"),
                        help="Associate an existing compatible controller turn; does not enable hooks")
    parser.add_argument("--summary")
    parser.add_argument("--details", type=Path)
    parser.add_argument("--verdict", choices=maintainer.VERDICTS)
    parser.add_argument("--verdict-candidate")
    parser.add_argument("--phase", choices=PHASES, default="update")
    parser.add_argument("--execution", choices=("auto", "local", "remote"), default="auto")
    parser.add_argument("--user-url", help="Explicit approved browser-facing loopback forward; does not claim a render")
    parser.add_argument("--reply-file", type=Path)
    args = parser.parse_args()
    # Do not even read a draft, resolve the checkout, or create private state for
    # ordinary chat/reviewers. Their replies remain the caller's original bytes.
    if args.context != "controller":
        print(json.dumps({"status": "bypassed", "context": args.context}))
        return 0
    result = None
    try:
        if not args.task:
            raise ValueError("Select an active flight with --task")
        if bool(args.verdict) != bool(args.verdict_candidate):
            raise ValueError("Pass --verdict and --verdict-candidate together")
        if args.user_url:
            browser_url(args.user_url, args.task)
        checkout = maintainer.git_path(Path.cwd(), "--show-toplevel")
        state = maintainer.state_dir(checkout)
        result = prepare(checkout, state, args) if args.command == "prepare" else check(checkout, state, args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        known_url = None
        try:
            known = read_object(state / "tasks" / args.task / "reply-route.json") if "state" in locals() else {}
            value = known.get("user_url") or known.get("host_url")
            known_url = browser_url(value, args.task) if value else None
        except (OSError, ValueError, TypeError):
            pass
        result = {"status": "unavailable", "error": str(error), "footer": footer(known_url),
                  "publication": "unavailable", "browser_reachability": "unobserved", "browser_rendering": "unobserved"}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "published" else 1


if __name__ == "__main__":
    raise SystemExit(main())
