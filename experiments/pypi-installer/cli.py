"""Sandbox-only distribution prototype. It does not configure an agent client."""

import argparse
from contextlib import contextmanager
import hashlib
import io
from importlib import resources
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import subprocess
import tarfile

MARKER = ".flightcheck-prototype-sandbox"
MARKER_TEXT = "Disposable FlightCheck distribution sandbox\n"
STATE = ".flightcheck"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def asset_path(name):
    path = PurePosixPath(name)
    if (not isinstance(name, str) or path.is_absolute() or ".." in path.parts
            or str(path) != name or not path.parts):
        raise ValueError("Unsafe asset path")
    return path


def manifest_valid(manifest):
    if (manifest.get("schema") != 1 or manifest.get("prototype") is not True
            or not isinstance(manifest.get("version"), str)
            or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("source_revision", ""))
            or not isinstance(manifest.get("assets"), dict) or not manifest["assets"]):
        raise ValueError("Invalid prototype manifest")
    for name, digest in manifest["assets"].items():
        asset_path(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid asset digest")


def bundle():
    package = resources.files("flightcheck_prototype")
    manifest = json.loads(package.joinpath("manifest.json").read_text())
    manifest_valid(manifest)
    files = {}
    for name, digest in manifest["assets"].items():
        data = package.joinpath("assets", *asset_path(name).parts).read_bytes()
        if sha(data) != digest:
            raise ValueError("Packaged asset hash mismatch: " + name)
        files[name] = data
    if sha(package.joinpath("cli.py").read_bytes()) != manifest["cli_sha256"]:
        raise ValueError("Packaged CLI hash mismatch")
    return manifest, files


def no_links(path):
    # Reject links before traversal, including broken links and linked parents.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Symlink path is not supported: " + str(part))
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_symlink():
                raise ValueError("Symlink inside managed state: " + str(child))


@contextmanager
def sandbox(target):
    if os.name != "posix" or sys.version_info < (3, 9):
        raise ValueError("Prototype requires Python 3.9+ on POSIX; Windows is unsupported")
    import fcntl
    root = Path(os.path.abspath(target))
    no_links(root)
    marker = root / MARKER
    if not root.is_dir() or marker.read_text() != MARKER_TEXT:
        raise ValueError("Target must be an explicitly marked disposable sandbox")
    # Serialize cooperating prototype invocations without writing even a lock file
    # during dry-run. Production must also coordinate with the selected client.
    with marker.open("rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        no_links(root / STATE)
        yield root / STATE


def read_lock(state):
    lock = json.loads((state / "lock.json").read_text())
    if (set(lock) != {"schema", "prototype", "bundle", "manifest", "runtime"}
            or lock["schema"] != 1 or lock["prototype"] is not True
            or not isinstance(lock["bundle"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", lock["bundle"])):
        raise ValueError("Invalid prototype lock")
    manifest_valid(lock["manifest"])
    if sha(encoded(lock["manifest"])) != lock["bundle"]:
        raise ValueError("Lock does not match its pinned manifest")
    runtime = lock["runtime"]
    if (set(runtime) != {"executable", "sha256", "python"}
            or not Path(runtime["executable"]).is_absolute()
            or not re.fullmatch(r"[a-f0-9]{64}", runtime["sha256"])
            or not isinstance(runtime["python"], str) or not runtime["python"]):
        raise ValueError("Invalid runtime pin")
    return lock


def verify(state, lock):
    version = state / "versions" / lock["bundle"]
    expected = set(lock["manifest"]["assets"]) | {"manifest.json"}
    actual = {str(p.relative_to(version)) for p in version.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("Installed asset inventory mismatch")
    if (version / "manifest.json").read_bytes() != encoded(lock["manifest"]):
        raise ValueError("Installed manifest mismatch")
    for name, digest in lock["manifest"]["assets"].items():
        if sha((version / name).read_bytes()) != digest:
            raise ValueError("Modified installed asset: " + name)
    if sha(Path(lock["runtime"]["executable"]).read_bytes()) != lock["runtime"]["sha256"]:
        raise ValueError("Pinned runtime changed or is unavailable")


def ongoing(state):
    active = state / "active"
    return active.exists() and (not active.is_dir() or any(active.iterdir()))


def populate(destination, manifest, files):
    destination.mkdir()
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (destination / "manifest.json").write_bytes(encoded(manifest))


def install(state, command, apply, expected):
    manifest, files = bundle()
    identity = sha(encoded(manifest))
    old = None
    if state.exists():
        old = read_lock(state)
        verify(state, old)
    if command == "upgrade":
        if old is None or expected != old["bundle"]:
            raise ValueError("Upgrade requires --from matching the installed bundle")
        if ongoing(state):
            raise ValueError("Upgrade refused: an ongoing flight is pinned; finish it first")
    elif old is not None and old["bundle"] != identity:
        raise ValueError("A different bundle is installed; use explicit upgrade --from")
    if old is not None and old["bundle"] == identity:
        return {"action": "unchanged", "bundle": identity, "writes": []}
    runtime_path = Path(sys.executable).resolve()
    runtime = {"executable": str(runtime_path), "sha256": sha(runtime_path.read_bytes()),
               "python": sys.version}
    lock = {"schema": 1, "prototype": True, "bundle": identity,
            "manifest": manifest, "runtime": runtime}
    destination = state / "versions" / identity
    reused = destination.exists()
    if reused:
        # Retained versions and unmanaged collisions affect preview as well as
        # apply. A reused bundle must match the incoming manifest and all bytes.
        verify(state, lock)
    writes = [] if reused else [f"{STATE}/versions/{identity}/{name}" for name in sorted(files)]
    if not reused:
        writes.append(f"{STATE}/versions/{identity}/manifest.json")
    writes.append(f"{STATE}/lock.json")
    result = {"action": "apply" if apply else "dry-run", "from": old["bundle"] if old else None,
              "bundle": identity, "version": manifest["version"], "writes": writes,
              "reused_bundle": reused,
              "instruction_edits": [], "client_configuration": "not implemented"}
    if not apply:
        return result
    if old is None:
        # One rename publishes the first complete state. Failed staging is removed.
        with tempfile.TemporaryDirectory(prefix=".flightcheck-stage-", dir=state.parent) as scratch:
            pending = Path(scratch) / STATE
            (pending / "versions").mkdir(parents=True)
            populate(pending / "versions" / identity, manifest, files)
            (pending / "lock.json").write_bytes(encoded(lock))
            os.rename(pending, state)
    else:
        if destination.exists():
            verify(state, lock)
        with tempfile.TemporaryDirectory(prefix=".upgrade-", dir=state) as scratch:
            scratch = Path(scratch)
            fresh = not destination.exists()
            if fresh:
                populate(scratch / "bundle", manifest, files)
            (scratch / "lock.json").write_bytes(encoded(lock))
            try:
                if fresh:
                    os.rename(scratch / "bundle", destination)
                os.replace(scratch / "lock.json", state / "lock.json")
            except OSError:
                if fresh and destination.exists():
                    shutil.rmtree(destination)
                raise
    return result


def configure(state, agent, config, apply):
    """Run the canonical installer from its exact embedded Git tree.

    The shallow repository retains the real original commit/tree, not a synthetic
    commit for extracted files. No history, network, global Git config or hooks
    are needed. The canonical installer and its source checks remain unchanged.
    """
    if not agent or not config:
        raise ValueError("configure requires explicit --agent and --config")
    lock = read_lock(state)
    verify(state, lock)
    manifest, _ = bundle()
    if lock["bundle"] != sha(encoded(manifest)):
        raise ValueError("Explicit project upgrade is required before configuring another bundle")
    if ongoing(state):
        raise ValueError("Configuration refused: an ongoing flight is pinned")
    package = resources.files("flightcheck_prototype")
    archive = package.joinpath("source.tar").read_bytes()
    commit = package.joinpath("source-commit.txt").read_bytes()
    if sha(archive) != manifest["source_archive_sha256"] or sha(commit) != manifest["source_commit_sha256"]:
        raise ValueError("Embedded source provenance mismatch")
    with tempfile.TemporaryDirectory(prefix="flightcheck-source-") as scratch:
        source = Path(scratch) / "source"
        source.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            seen = set()
            for entry in stream.getmembers():
                name = str(asset_path(entry.name.rstrip("/")))
                if name in seen or ".git" in PurePosixPath(name).parts:
                    raise ValueError("Unsafe embedded source entry")
                seen.add(name)
                destination = source / name
                if entry.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif entry.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(stream.extractfile(entry).read())
                    destination.chmod(entry.mode & 0o777)
                else:
                    raise ValueError("Embedded source links/special files are unsupported")
        empty_template = Path(scratch) / "empty-template"
        empty_template.mkdir()
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")

        def git(*arguments, data=None):
            result = subprocess.run(["git", "--no-optional-locks", "-C", str(source), *arguments],
                                    input=data, capture_output=True, env=env, timeout=20)
            if result.returncode:
                raise ValueError("Embedded source Git verification failed: " + result.stderr.decode())
            return result.stdout.decode().strip()

        git("init", "-q", "--template=" + str(empty_template))
        git("config", "core.hooksPath", os.devnull)
        git("add", "--force", ".")
        if git("write-tree") != manifest["source_tree"]:
            raise ValueError("Embedded source tree differs from pinned original")
        revision = git("hash-object", "-t", "commit", "-w", "--stdin", data=commit)
        if revision != manifest["source_revision"]:
            raise ValueError("Embedded source commit differs from pinned original")
        (source / ".git/shallow").write_text(revision + "\n")
        git("update-ref", "HEAD", revision)
        result = subprocess.run([sys.executable, "-B", str(source / "setup/install.py"),
                                 "apply" if apply else "plan", "--target", str(state.parent),
                                 "--agent", agent, "--config", str(Path(config).absolute())],
                                capture_output=True, text=True, env=env, timeout=60)
        if result.returncode:
            raise ValueError("Complete workflow configuration failed: " + result.stdout + result.stderr)
        return {"action": "configure-apply" if apply else "configure-plan",
                "workflow": json.loads(result.stdout), "source_revision": revision,
                "client_qualification": "pending real fresh-session and browser observations"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "doctor", "status", "upgrade", "configure"])
    parser.add_argument("--sandbox", required=True, help="Explicitly marked disposable target only")
    parser.add_argument("--apply", action="store_true", help="Apply the printed write plan")
    parser.add_argument("--from", dest="expected", help="Expected installed bundle for upgrade")
    parser.add_argument("--agent", choices=["codex", "claude", "both"])
    parser.add_argument("--config", help="Reviewed project configuration JSON for configure")
    args = parser.parse_args()
    try:
        if args.command in {"doctor", "status"} and (args.apply or args.expected):
            raise ValueError("Read-only commands do not accept --apply or --from")
        with sandbox(args.sandbox) as state:
            if args.command == "configure":
                result = configure(state, args.agent, args.config, args.apply)
            elif args.command in {"init", "upgrade"}:
                result = install(state, args.command, args.apply, args.expected)
            else:
                lock = read_lock(state)
                verify(state, lock)
                result = {"action": args.command, "bundle": lock["bundle"],
                          "version": lock["manifest"]["version"], "runtime": lock["runtime"],
                          "ongoing_flight": bool(ongoing(state)), "prototype_integrity": "verified",
                          "client_configuration": "not implemented", "live_client_support": "unverified"}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error), "prototype": True}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
