"""Verify/materialize #58's embedded immutable Git source; reuse setup/install.py."""
from contextlib import contextmanager
import hashlib
import importlib.util
from importlib import resources
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def safe_name(name):
    path = PurePosixPath(name)
    if not name or not path.parts or path.is_absolute() or ".." in path.parts or ".git" in path.parts or str(path) != name:
        raise ValueError("Unsafe packaged source path: " + name)
    return path


def bundle():
    package = resources.files("flightcheck_cli")
    raw = package.joinpath("manifest.json").read_bytes()
    value = json.loads(raw)
    if (value.get("schema") != 1 or value.get("distribution") != "flightcheck"
            or not isinstance(value.get("development"), bool)
            or not all(re.fullmatch(r"[a-f0-9]{40}", value.get(k, "")) for k in ("source_revision", "source_tree", "base_revision"))
            or not isinstance(value.get("cli_files"), dict) or not value["cli_files"]):
        raise ValueError("Invalid packaged provenance manifest")
    from importlib import metadata
    if metadata.version("flightcheck") != value["version"]:
        raise ValueError("Distribution metadata and packaged version disagree")
    for name, digest in value["cli_files"].items():
        if len(safe_name(name).parts) != 1 or sha(package.joinpath(name).read_bytes()) != digest:
            raise ValueError("Packaged CLI hash mismatch: " + name)
    archive = package.joinpath("source.tar").read_bytes()
    commit = package.joinpath("source-commit.txt").read_bytes()
    if sha(archive) != value["source_archive_sha256"] or sha(commit) != value["source_commit_sha256"]:
        raise ValueError("Packaged source hash mismatch")
    return value, sha(encoded(value)), archive, commit


def load_installer(path):
    spec = importlib.util.spec_from_file_location("flightcheck_shared_installer", path)
    module = importlib.util.module_from_spec(spec)
    # Execute verified source without writing __pycache__ into an adopter.
    exec(compile(Path(path).read_bytes(), str(path), "exec"), module.__dict__)
    return module


@contextmanager
def installer():
    manifest, identity, archive, commit = bundle()
    with tempfile.TemporaryDirectory(prefix="flightcheck-source-") as scratch:
        root = Path(scratch).resolve() / "source"
        root.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            seen = set()
            for entry in stream.getmembers():
                name = str(safe_name(entry.name.rstrip("/")))
                if name in seen:
                    raise ValueError("Duplicate packaged source path")
                seen.add(name)
                dest = root / name
                if entry.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif entry.isfile():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(stream.extractfile(entry).read())
                    dest.chmod(entry.mode & 0o777)
                else:
                    raise ValueError("Packaged links/special files are unsupported")
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        def git(*args, data=None):
            return subprocess.check_output(["git", "--no-optional-locks", "-C", str(root), *args], input=data, env=env, stderr=subprocess.PIPE).decode().strip()
        git("init", "-q", "--template=")
        git("config", "core.hooksPath", os.devnull)
        git("add", "--force", ".")
        if git("write-tree") != manifest["source_tree"]:
            raise ValueError("Packaged Git tree differs from its manifest")
        revision = git("hash-object", "-t", "commit", "-w", "--stdin", data=commit)
        if revision != manifest["source_revision"]:
            raise ValueError("Packaged commit differs from its manifest")
        (root / ".git/shallow").write_text(revision + "\n")
        git("update-ref", "HEAD", revision)
        yield load_installer(root / "setup/install.py"), root, manifest, identity
