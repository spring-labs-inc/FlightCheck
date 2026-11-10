"""Choose a browser action for a task from a desktop tab inventory."""

import argparse
import json
import sys
from urllib.parse import urlsplit

from task_status import task_path


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
    args = parser.parse_args()
    try:
        browser = json.load(sys.stdin)
        if not isinstance(browser, dict):
            raise ValueError("Expected a browser inventory object")
        decision = decide(args.task, browser)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
