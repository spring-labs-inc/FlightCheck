"""Choose a browser action for a task from a desktop tab inventory."""

import argparse
import json
import sys
from urllib.parse import urlsplit

from task_status import task_path, validate_task_url


def discover(task, candidate, browser, publication_port):
    """Consume actual adapter observations; a queued preview is not a route.

    The adapter reads status.json on the browser machine. Tab names and worker
    HTTP success cannot stand in for that observation. This helper neither opens
    tabs nor creates transports.
    """
    missing = {"action": "fallback", "user_url": None,
               "browser_reachability": "unobserved", "browser_rendering": "unobserved",
               "browser_visibility": "unobserved", "route_attempts": ["native"]}
    if not isinstance(browser, dict) or not isinstance(browser.get("tabs"), list):
        return dict(missing, reason="Browser inventory unavailable; use the existing browser-machine connector.")
    candidates = list(browser["tabs"])
    endpoints = browser.get("endpoints", [])
    if isinstance(endpoints, list):
        candidates += endpoints
    if isinstance(browser.get("saved_endpoint"), dict):
        missing["route_attempts"] = ["saved", "native"]
        candidates.insert(0, browser["saved_endpoint"])
    matches = []
    for tab in candidates:
        if not isinstance(tab, dict):
            continue
        try:
            validate_task_url(tab.get("url", ""), task)
        except (ValueError, TypeError):
            continue
        snapshot = tab.get("snapshot")
        if (tab.get("endpoint_reached") is True and isinstance(snapshot, dict)
                and snapshot.get("snapshot") == "live" and snapshot.get("task") == task
                and snapshot.get("candidate") == candidate
                and snapshot.get("publicationPort") == publication_port
                and isinstance(snapshot.get("completeness"), dict)
                and snapshot["completeness"].get("ready") is True):
            matches.append(tab)
    urls = {tab["url"] for tab in matches}
    if len(urls) != 1:
        reason = "Ambiguous browser routes" if urls else "No browser endpoint verified for this task and candidate"
        return dict(missing, reason=reason + "; use the existing connector or refresh the native observation.")
    tab_matches = [tab for tab in browser["tabs"] if tab in matches]
    if not tab_matches and any(isinstance(tab, dict) and tab.get("url") in urls for tab in browser["tabs"]):
        return dict(missing, reason="The existing tab needs a fresh candidate observation; do not open a duplicate.")
    decision = decide(task, dict(browser, tabs=tab_matches))
    selected = next((tab for tab in tab_matches if tab.get("visible") is True), matches[0])
    activation = browser.get("activation", {})
    if (isinstance(activation, dict) and activation.get("status") == "queued"
            and activation.get("url") == selected["url"] and not tab_matches):
        decision = {"action": "requested"}
    return dict(decision, user_url=selected["url"], browser_reachability="verified",
                route_attempts=missing["route_attempts"],
                browser_visibility="visible" if selected.get("visible") is True and tab_matches else "unobserved",
                browser_rendering="verified" if selected.get("rendered_candidate") == candidate else "unobserved")


def decide(task, browser):
    route = task_path(task)
    tabs = browser.get("tabs")
    if not isinstance(tabs, list):
        return {"action": "fallback"}

    matches = []
    inventory_complete = True
    for tab in tabs:
        if not isinstance(tab, dict) or not isinstance(tab.get("url"), str) or not tab["url"]:
            inventory_complete = False
            continue
        try:
            url = urlsplit(tab["url"])
        except ValueError:
            inventory_complete = False
            continue
        if (url.scheme in ("http", "https") and url.hostname in ("127.0.0.1", "::1", "localhost")
                and url.path == route):
            matches.append(tab)

    for tab in matches:
        if tab.get("visible") is True:
            return {"action": "keep"}
    for tab in matches:
        if tab.get("visible") is False and browser.get("can_reveal") is True and tab.get("id"):
            return {"action": "reveal", "tab_id": tab["id"]}
    if not matches and inventory_complete and browser.get("can_open") is True:
        return {"action": "open"}
    return {"action": "fallback"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--candidate", help="Discover a route from observed endpoint snapshots for this candidate")
    parser.add_argument("--publication-port", type=int)
    args = parser.parse_args()
    try:
        browser = json.load(sys.stdin)
        if not isinstance(browser, dict):
            raise ValueError("Expected a browser inventory object")
        if bool(args.candidate) != bool(args.publication_port):
            raise ValueError("Route discovery requires both --candidate and --publication-port")
        decision = (discover(args.task, args.candidate, browser, args.publication_port)
                    if args.candidate else decide(args.task, browser))
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
