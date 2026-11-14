"""Reference Git candidate identity and explicitly configured gate fingerprint."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from evidence_inputs import manifest, sha


def git(root, *args):
    return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=root)


def candidate(root):
    # Match the bundled maintainer's default identity, including local untracked
    # tool files. Gate equivalence is a separate explicit input/runtime manifest.
    digest = hashlib.sha256()
    for args in (("rev-parse", "HEAD"),
                 ("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--"),
                 ("diff", "--cached", "--raw", "HEAD", "--")):
        digest.update(git(root, *args))
        digest.update(b"\0")
    for name in git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if name:
            metadata = (root / os.fsdecode(name)).lstat()
            digest.update(name + b"\0")
            digest.update(repr((metadata.st_mode, metadata.st_size, metadata.st_mtime_ns,
                                metadata.st_ctime_ns)).encode() + b"\0")
    return digest.hexdigest()


def gate(config):
    root = Path(config["root"])
    if not root.is_absolute():
        raise ValueError("root must be an explicit absolute project path")
    python = Path(config["python"])
    if not python.is_absolute() or not python.is_file():
        raise ValueError("python must name the selected absolute interpreter")
    dependencies = config.get("dependencies", [])
    if not isinstance(dependencies, list) or any(not isinstance(name, str) or not name for name in dependencies):
        raise ValueError("dependencies must list selected installed distributions")
    probe = """import hashlib,json,sys,importlib.metadata as m
from pathlib import Path
result={}
for name in json.loads(sys.argv[1]):
    distribution=m.distribution(name)
    if distribution.files is None: raise ValueError('Dependency has no installed file manifest: '+name)
    files={}
    for entry in distribution.files:
        if '__pycache__' in entry.parts or str(entry).endswith('.pyc'): continue
        path=Path(distribution.locate_file(entry))
        if not path.is_file(): raise ValueError('Missing dependency file: '+str(path))
        files[str(entry)]={'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    result[name]={'version':distribution.version,'files':files}
print(json.dumps({'executable':sys.executable,'version':sys.version,
                 'implementation':sys.implementation.name,'dependencies':result},sort_keys=True))
"""
    result = subprocess.run([str(python), "-B", "-c", probe, json.dumps(dependencies)],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError("Selected runtime/dependency probe failed: " + result.stderr.strip())
    runtime = json.loads(result.stdout)
    runtime["launcher"] = str(python)
    runtime["launcher_input"] = manifest(python.parent, [python.name])
    runtime["resolved_executable"] = manifest(root, [runtime["executable"]])
    environment = config.get("environment", [])
    if not isinstance(environment, list) or any(not isinstance(name, str) or not name for name in environment):
        raise ValueError("environment must list relevant variable names")
    return {"root": str(root.resolve()), "inputs": manifest(root, config["inputs"]),
            "runtime": runtime, "environment": {name: sha(os.environ[name].encode()) if name in os.environ else None
                                                  for name in environment},
            "helper": manifest(Path(__file__).parent, ["fingerprint.py", "evidence_inputs.py"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("candidate", "gate"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text()) if args.config else None
        if args.mode == "gate":
            if config is None:
                raise ValueError("gate requires --config with root, inputs, python and dependencies")
            print(json.dumps(gate(config), sort_keys=True))
        else:
            root = args.root or (Path(config["root"]) if config else None)
            if root is None:
                raise ValueError("candidate requires --root or --config")
            value = candidate(root.resolve())
            if config is not None:
                value = sha(json.dumps({"git_candidate": value, "gate": gate(config)}, sort_keys=True).encode())
            print(value)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(2, "Cannot fingerprint required inputs: " + str(error) + "\n")


if __name__ == "__main__":
    main()
