"""Prepare a portable flight card and check each controller reply before sending.

This explicit controller command is not a native message interception hook.
Ordinary/reviewer contexts return before accessing Git, state or reply content.
"""

import argparse
import copy
import fcntl
import json
import os
import re
import socket
import stat
import time
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


def route_record(previous, task, host_url, execution, supplied, context=None, reconcile=False, confirmed_reuse=False):
    if previous and previous.get("task") != task:
        raise ValueError("The prepared route belongs to another task")
    if previous.get("user_url"):
        browser_url(previous["user_url"], task)
    if supplied:
        browser_url(supplied, task)
        if previous.get("user_url") and previous["user_url"] != supplied and not reconcile:
            raise ValueError("The task already has a browser URL; preserve it and reconcile forwarding explicitly")
    # A loopback URL used on the checkout host does not establish forwarding
    # after the task moves to a remote session.
    compatible = (previous.get("execution") == execution
                  and (context is None or previous.get("context") == context or confirmed_reuse))
    approved = supplied or (previous.get("user_url") if compatible else None)
    user_url = approved or (host_url if execution == "local" else None)
    retained = bool(not supplied and not compatible and previous.get("user_url") and execution == "remote")
    if retained:
        # A failed handoff must not erase the only known browser route or move
        # its ownership. The caller gets unavailable until reconciliation.
        user_url, context = previous["user_url"], previous.get("context")
    return {"task": task, "host_url": host_url, "user_url": user_url, "execution": execution,
            **({"context": context} if context is not None else {}),
            **({"manual_route": previous["manual_route"]} if previous.get("manual_route") else {}),
            **({"route_verification": previous["route_verification"]}
               if (compatible or retained) and previous.get("route_verification") and not supplied else {}),
            **({"route_unverified": True} if retained or compatible and previous.get("route_unverified") and not supplied else {})}


def verified_route(record, candidate):
    proof = record.get("route_verification", {})
    if not isinstance(proof, dict):
        return False
    if record.get("route_unverified"):
        return False
    # An explicitly confirmed manual destination is connection configuration,
    # never a fresh browser observation. Scope/session checks remain mandatory.
    if proof.get("source") == "declared" and isinstance(record.get("manual_route"), dict):
        return True
    stamp = proof.get("observed_at")
    return (proof.get("candidate") == candidate and type(stamp) in (int, float)
            and -5 <= time.time() - stamp <= 30 and not record.get("route_unverified"))


def route_context(checkout, session):
    return {"host": socket.gethostname(),
            "repository": str(maintainer.git_path(checkout, "--path-format=absolute", "--git-common-dir")),
            "session": session}


def manual_configuration(record, context, checkout, directory):
    """Read only this task's confirmed destination and explicit route callers.

    This grants no checkout editing or transport/process ownership. Fresh native
    and connector observations never become reusable manual configuration.
    """
    proof, prior = record.get("route_verification", {}), record.get("context", {})
    if (not isinstance(proof, dict) or proof.get("source") != "declared"
            or not isinstance(prior, dict) or not record.get("user_url")
            or any(prior.get(key) != context.get(key) for key in ("host", "repository"))
            or read_object(directory / "monitor.json").get("checkout") != str(checkout.resolve())):
        return None
    cfg = record.get("manual_route")
    if cfg is None:
        # Explicit compatibility reconciliation retains a legacy declaration's
        # original source context/time; publication does not refresh that fact.
        cfg = {"schema": 1, "task": record["task"], "url": record["user_url"],
               "checkout": str(checkout.resolve()), "source_context": prior,
               "configured_at": proof.get("observed_at"), "sessions": [prior.get("session")], "handoffs": []}
    if (not isinstance(cfg, dict) or cfg.get("schema") != 1 or cfg.get("task") != record.get("task")
            or cfg.get("url") != record["user_url"] or cfg.get("checkout") != str(checkout.resolve())
            or not isinstance(cfg.get("source_context"), dict)
            or any(cfg["source_context"].get(key) != context.get(key) for key in ("host", "repository"))
            or not isinstance(cfg.get("sessions"), list) or not cfg["sessions"]
            or not isinstance(cfg.get("handoffs"), list)):
        return None
    return copy.deepcopy(cfg)


def route_caller_matches(record, context, checkout, directory):
    if read_object(directory / "monitor.json").get("checkout") != str(checkout.resolve()):
        return False
    proof = record.get("route_verification", {})
    if isinstance(proof, dict) and proof.get("source") == "declared" and record.get("manual_route"):
        cfg = manual_configuration(record, context, checkout, directory)
        return bool(cfg and context.get("session") in cfg["sessions"])
    return record.get("context") == context


def browser_observation(path, context):
    """A private, fresh native API result, never an owner URL interview."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Browser observation must be a private regular file")
    metadata = path.stat()
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("Browser observation must be private to the current user")
    value = read_object(path)
    stamp = value.get("observed_at")
    if (value.get("schema") != 1 or value.get("context") != context
            or type(stamp) not in (int, float) or not -5 <= time.time() - stamp <= 30):
        raise ValueError("Browser observation is stale or belongs to another host, repository or session; refresh supported native controls")
    return value


def observation(record, candidate, publication, verdict="Pending"):
    url = record.get("user_url")
    remote_pending = record["execution"] == "remote" and (not record.get("user_url") or not verified_route(record, candidate))
    ready = bool(publication and publication.get("completeness", {}).get("ready"))
    result = {"task": record["task"], "candidate": candidate,
              "status": "published" if ready and not remote_pending else "incomplete" if publication and not ready else "unavailable",
              "publication": "verified" if publication else "unavailable",
              "verdict": verdict if ready else "Pending",
              "completeness": publication.get("completeness") if publication else None,
              "execution": record["execution"], "host_url": record.get("host_url"),
              "user_url": record.get("user_url"), "footer": footer(url if ready and not remote_pending else None),
              "browser_reachability": "unobserved", "browser_rendering": "unobserved"}
    if remote_pending:
        port = urlsplit(record["host_url"]).port if record.get("host_url") else "HOST_PORT"
        result["guidance"] = ("Browser route unavailable. First refresh supported native browser controls and pass their private "
                              "observation with --browser-observation. If unavailable, run the existing status-card/connect.py "
                              "on the browser machine with --checkout and --task; its compatible saved profile supplies SSH configuration. "
                              "For a first connection only, include --ssh with an existing host alias. "
                              "The connector starts/restores the remote service and verifies the forwarded task before offering a link. "
                              "For client-managed forwarding, prepare again with --user-url and the observed forwarded task URL. "
                              "The checkout-host URL alone is not a reachable browser route.")
    else:
        result["guidance"] = ("Open the live card in your regular browser at " + str(url)
                              + ". Continue terminal work independently; a text card is unnecessary. "
                              "Host HTTP publication does not prove browser reachability or rendering. "
                              "An explicit --user-url is a client-supplied route, not a browser verification by this worker.")
    if not publication:
        result["guidance"] = ("Card publication unavailable; run prepare to restore the same listener. "
                              "The recorded route is retained in user_url/host_url for recovery; no working link is offered. "
                              "Browser reachability and rendering remain unobserved.")
    elif not ready:
        result["guidance"] = ("Incomplete active-flight card; prepare again with complete --details. "
                              + " ".join(publication["completeness"]["issues"])
                              + " The route is retained for recovery; no ready card link is offered.")
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
        context = route_context(checkout, args.session)
        flight_binding = read_object(directory / "monitor.json")
        if (flight_binding.get("checkout") not in (None, str(checkout.resolve()))
                and (getattr(args, "connection_adapter", False) or not getattr(args, "reconcile_route", False))):
            raise ValueError("The task belongs to another recorded checkout; reconcile the actual flight before publication")
        if getattr(args, "connection_adapter", False) and previous.get("context"):
            # The browser-machine connector is an alternate route caller, not
            # a handoff of the selected implementation/controller session.
            saved = previous["context"]
            if not isinstance(saved, dict) or any(saved.get(key) != context.get(key) for key in ("host", "repository")):
                raise ValueError("Connection adapter belongs to another host or repository")
            context = saved
        confirmation = None
        if getattr(args, "connection_adapter", False) and args.user_url:
            try:
                confirmation = json.loads(getattr(args, "connection_confirmation", None) or "null")
            except ValueError:
                raise ValueError("Invalid connector confirmation") from None
            expected = {"candidate": maintainer.candidate(checkout), "host_url": host_url, "context": context}
            if confirmation != expected:
                raise ValueError("Connector candidate or route changed before confirmation; no route was adopted")
        cfg = manual_configuration(previous, context, checkout, directory)
        if cfg and getattr(args, "reconcile_route", False) and not args.user_url:
            if context.get("session") not in cfg["sessions"]:
                cfg["handoffs"].append({"session": context.get("session"), "at": time.time(),
                                        "reference": "Explicit same-flight --reconcile-route"})
                cfg["sessions"].append(context.get("session"))
            previous = dict(previous, manual_route=cfg)
        confirmed_reuse = bool(cfg and context.get("session") in cfg["sessions"])
        if cfg and not confirmed_reuse and not args.user_url:
            raise ValueError("Known manual route retained; use --reconcile-route for an authorized same-flight controller handoff")
        # Reject conflicting routes before publication or state changes.
        record = route_record(previous, args.task, host_url, mode, args.user_url, context,
                              getattr(args, "reconcile_route", False), confirmed_reuse)
        try:
            maintainer.show_card(checkout, state, argparse.Namespace(
                task=args.task, title=args.title,
                summary=args.summary, details=args.details, verdict=args.verdict,
                verdict_candidate=args.verdict_candidate, session=args.session))
            endpoint = read_object(directory / "endpoint.json")
            record = route_record(previous, args.task, maintainer.card_url(args.task, endpoint["port"]), mode, args.user_url,
                                  context, getattr(args, "reconcile_route", False), confirmed_reuse)
            current = maintainer.candidate(checkout)
            live = published_card(args.task, endpoint["port"], current)
            if confirmation is not None and confirmation != {"candidate": current, "host_url": record["host_url"], "context": context}:
                raise ValueError("Connector candidate or route changed during confirmation; no route was adopted")
            if args.user_url:
                record["route_verification"] = {"candidate": current, "observed_at": time.time(),
                                                "source": "connector" if getattr(args, "connection_adapter", False) else "declared"}
                if not getattr(args, "connection_adapter", False):
                    if not cfg or cfg["url"] != args.user_url:
                        cfg = {"schema": 1, "task": args.task, "url": args.user_url, "checkout": str(checkout.resolve()),
                               "source_context": context, "configured_at": time.time(),
                               "sessions": [context.get("session")], "handoffs": []}
                    elif context.get("session") not in cfg["sessions"]:
                        cfg["handoffs"].append({"session": context.get("session"), "at": time.time(),
                                                "reference": "Explicit owner route declaration"})
                        cfg["sessions"].append(context.get("session"))
                    record["manual_route"] = cfg
            elif confirmed_reuse:
                record["manual_route"] = cfg
            native = None
            if getattr(args, "browser_observation", None):
                from task_tab import discover
                try:
                    observed = browser_observation(args.browser_observation, context)
                    native = discover(args.task, current, observed, endpoint["port"])
                    if native["user_url"]:
                        record = route_record(previous, args.task, record["host_url"], mode, native["user_url"], context,
                                              getattr(args, "reconcile_route", False))
                        record["route_verification"] = {"candidate": current, "observed_at": observed["observed_at"], "source": "native"}
                    else:
                        record["route_unverified"] = True
                except ValueError as error:
                    record["route_unverified"] = True
                    native = {"action": "fallback", "reason": str(error)}
            maintainer.write_json(directory / "reply-route.json", record)
            result = observation(record, current, live, live["verdict"] if live else "Pending")
            result["context"] = context
            if native:
                result["browser_action"] = native["action"]
                result["route_attempts"] = native.get("route_attempts", ["native"])
                result["browser_visibility"] = native.get("browser_visibility", "unobserved")
                if native.get("tab_id"):
                    result["tab_id"] = native["tab_id"]
                if native.get("user_url") and not record.get("route_unverified"):
                    for key in ("browser_reachability", "browser_rendering"):
                        result[key] = native[key]
                elif native.get("reason"):
                    result["guidance"] = native["reason"] + " " + result["guidance"]
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
    if not route_caller_matches(record, route_context(checkout, args.session), checkout, directory):
        raise ValueError("Host, repository or session changed; prepare and verify this connection before replying")
    if args.user_url and args.user_url != record.get("user_url"):
        raise ValueError("Use the prepared task's exact browser URL")
    current = maintainer.candidate(checkout)
    published = published_card(args.task, endpoint.get("port"), current)
    result = observation(record, current, published, published["verdict"] if published else "Pending")
    if not args.reply_file:
        raise ValueError("check requires --reply-file with the exact controller reply")
    text = args.reply_file.read_text(encoding="utf-8")
    if not maintainer.has_footer(text, result["footer"]):
        result.update(status="blocked", error="Put the exact task footer last, in its own paragraph outside fences; put verdicts above it")
    elif any(value.strip() != result["verdict"] for value in re.findall(r"^Verdict:([^\n]+)$", text, re.M)):
        result.update(status="blocked", error="The reply verdict must match the current candidate's recorded verdict")
    result["phase"] = args.phase
    return result


class WrongTask(ValueError):
    pass


def observe(checkout, state, args, recover=False):
    # Observation/recovery never republishes a snapshot or renews its producer.
    import progress
    directory = state / "tasks" / args.task
    if read_object(directory / "status.json").get("task") != args.task:
        raise WrongTask("The recorded worker snapshot belongs to another task")
    if recover:
        progress.recover_listener(directory, args.task)
    snapshot = progress.observe(directory, args.task)
    endpoint = read_object(directory / "endpoint.json")
    number = endpoint.get("port")
    if type(number) is not int or not 1 <= number <= 65535:
        raise ValueError("No valid recorded worker publication port")
    current = maintainer.candidate(checkout)
    live = published_card(args.task, number, snapshot["candidate"])
    return {"status": "observed", "task": args.task, "candidate": current,
            "context": route_context(checkout, args.session),
            "host_url": maintainer.card_url(args.task, number),
            "publication": "verified" if live else "unavailable", "snapshot": snapshot}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "check", "observe", "recover", "identify"))
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
    parser.add_argument("--browser-observation", type=Path, help="Private fresh browser API inventory and endpoint observations")
    parser.add_argument("--reconcile-route", action="store_true", help="Reconcile a browser route or authorized same-flight route caller")
    parser.add_argument("--connection-adapter", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--connection-confirmation", help=argparse.SUPPRESS)
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
        if args.command == "identify":
            # Read-only profile compatibility probe: no state directory, task
            # publication, monitor, listener or configuration is created.
            result = {"status": "identified", "task": args.task, "context": route_context(checkout, args.session)}
        else:
            state = maintainer.state_dir(checkout)
        if args.command == "identify":
            pass
        elif args.command in ("observe", "recover"):
            result = observe(checkout, state, args, args.command == "recover")
        else:
            result = prepare(checkout, state, args) if args.command == "prepare" else check(checkout, state, args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        known_url = None
        try:
            known = read_object(state / "tasks" / args.task / "reply-route.json") if "state" in locals() else {}
            value = known.get("user_url") or known.get("host_url")
            known_url = browser_url(value, args.task) if value else None
        except (OSError, ValueError, TypeError):
            pass
        result = {"status": "unavailable", "error": str(error),
                  "error_code": "wrong_task" if isinstance(error, WrongTask) else "unavailable",
                  "footer": footer(None), "known_url": known_url,
                  "publication": "unavailable", "browser_reachability": "unobserved", "browser_rendering": "unobserved"}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("published", "observed", "identified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
