import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
here = Path(__file__).resolve().parent

def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()

paths = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
inputs = {}
for raw in sorted(set(paths.split(b"\0")) - {b""}):
    name = os.fsdecode(raw)
    path = root / name
    if path.is_symlink():
        inputs[name] = [os.readlink(path), sha(path)]
    else:
        inputs[name] = sha(path)

runtime = {
    "python": [sys.version, sha(Path(sys.executable))],
    "platform": platform.platform(),
    "dependencies": sorted(
        (dist.metadata["Name"], dist.version,
         hashlib.sha256((dist.read_text("RECORD") or "").encode()).hexdigest())
        for dist in importlib.metadata.distributions()
    ),
    "gate": sys.argv[1],
}
if sys.argv[1] == "native":
    runtime["postgres"] = [os.environ["SPRING_ISOLATED_TEST_PORT"], sha(Path(os.environ["SPRINGDEV_BENCH_DB_RECEIPT"]))]
elif sys.argv[1] == "visual":
    runtime["browser"] = sha(Path(os.environ["SPRINGDEV_CHROMIUM_BINARY"]))
    runtime["fixture"] = sha(here / "visual.py")

elif sys.argv[1] == "cheap":
    runtime["runner"] = sha(here / "cheap-gate.py")
    runtime["ruff"] = sha(root / ".venv/bin/ruff")
    runtime["workflow_checker"] = sha(root / ".venv/bin/flightcheck-check")
else:
    raise SystemExit("Expected cheap, native, or visual")

print(json.dumps({"inputs": inputs, "runtime": runtime}, sort_keys=True))
