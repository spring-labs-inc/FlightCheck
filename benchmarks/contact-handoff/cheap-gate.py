import hashlib
import json
import subprocess
import time
from pathlib import Path

target = Path(".local/tmp/bench-cheap")
target.mkdir(parents=True, exist_ok=True)
commands = [
    ["git", "diff", "--check"],
    [".venv/bin/ruff", "check", "spring-web/authn/tests/test_contact.py"],
    [".venv/bin/python", "-B", "scripts/check_agent_policy.py"],
    [".venv/bin/python", "-B", ".venv/bin/flightcheck-check"],
]
checks = []
for index, command in enumerate(commands):
    start = time.monotonic()
    result = subprocess.run(command, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (target / f"cheap-{index}.log").write_bytes(result.stdout)
    print(f"{' '.join(command)} -> {result.returncode}", flush=True)
    print(result.stdout.decode(errors="replace"), flush=True)
    checks.append({"argv": command, "exit": result.returncode, "seconds": time.monotonic() - start,
                   "output_sha256": hashlib.sha256(result.stdout).hexdigest()})
(target / "cheap.json").write_text(json.dumps(checks, indent=2) + "\n")
raise SystemExit(int(any(check["exit"] != 0 for check in checks)))
