"""Truthful complete initialization for disposable active-flight fixtures."""

import json
import subprocess
import sys

STAGES = ("Plan", "Implement", "Cheap Tests", "Interactive UI Approval",
          "Independent Code Review", "Authoritative Gates", "Skeptical Evidence Review",
          "Final Verdict", "PR & Merge")


def complete(candidate, stage="Plan"):
    return {"stages": {name: "current" if name == stage else "pending" for name in STAGES},
            "check_plan": ["Fixture check"],
            "checks": [{"name": "Fixture check", "candidate": candidate, "state": "pending",
                        "counts": {}, "observed_at": "2026-01-01T00:00:00Z"}],
            "links_unavailable": {"issue": "Disposable fixture has no issue.", "pr": "No PR exists."}}


def initialized_details(checkout, path, args, stage="Plan", card_path="status-card"):
    code = ("import sys;from pathlib import Path;sys.path.insert(0," + repr(card_path)
            + ");import maintainer;print(maintainer.candidate(Path('.')))")
    candidate = subprocess.check_output([sys.executable, "-B", "-c", code], cwd=checkout, text=True).strip()
    details = complete(candidate, stage)
    args = list(args)
    if "--details" in args:
        index = args.index("--details")
        from pathlib import Path
        update = json.loads(Path(args[index + 1]).read_text())
        if "stages" in update:
            update["stages"] = {name: update["stages"].get(name, "pending") for name in STAGES}
        details.update(update)
        del args[index:index + 2]
    for row in details.get("links", []):
        details["links_unavailable"].pop(row["kind"], None)
    path.write_text(json.dumps(details))
    return ["--details", str(path), *args]
