"""PEP 517 staging backend, promoting #58's pinned-source wheel design.

Builds never generate resources in the checkout. Clean Git builds retain the
actual commit. Explicit development builds retain a separately labeled immutable
snapshot of uncommitted content; they never impersonate the upstream commit.
An sdist contains the frozen resources and uses setuptools directly offline.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args, cwd=ROOT, data=None):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(cwd), *args], input=data, env=env)


def payload():
    version = re.search(r'^version = "([^"]+)"$', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    base = git("rev-parse", "HEAD").decode().strip()
    dirty = bool(git("status", "--porcelain=v1", "--untracked-files=all"))
    if dirty and os.environ.get("FLIGHTCHECK_BUILD_DEVELOPMENT") != "1":
        raise ValueError("Build from clean Git, or explicitly set FLIGHTCHECK_BUILD_DEVELOPMENT=1 for an uncommitted review artifact")
    if dirty:
        names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
        with tempfile.TemporaryDirectory(prefix="flightcheck-build-source-") as scratch:
            source = Path(scratch)
            for name in sorted(set(names) - {""}):
                path = ROOT / name
                if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != ROOT.parent):
                    raise ValueError("Build input traverses a symlink: " + name)
                if not path.exists():
                    continue
                dest = source / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
                dest.chmod(path.stat().st_mode & 0o777)
            git("init", "-q", "--template=", cwd=source)
            git("config", "core.hooksPath", os.devnull, cwd=source)
            git("add", "--force", ".", cwd=source)
            tree = git("write-tree", cwd=source).decode().strip()
            epoch = git("show", "-s", "--format=%ct", "HEAD").decode().strip()
            commit = (f"tree {tree}\nparent {base}\nauthor FlightCheck review snapshot <snapshot@example.invalid> {epoch} +0000\n"
                      f"committer FlightCheck review snapshot <snapshot@example.invalid> {epoch} +0000\n\nUncommitted development snapshot; base {base}\n").encode()
            revision = git("hash-object", "-t", "commit", "-w", "--stdin", cwd=source, data=commit).decode().strip()
            (source / ".git/shallow").write_text(revision + "\n")
            git("update-ref", "HEAD", revision, cwd=source)
            archive = git("archive", "--format=tar", "HEAD", cwd=source)
    else:
        revision = base
        tree = git("rev-parse", "HEAD^{tree}").decode().strip()
        commit = git("cat-file", "commit", "HEAD")
        archive = git("archive", "--format=tar", "HEAD")
    # Reject archive links/special files instead of deferring unsafe extraction.
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for entry in stream.getmembers():
            if not (entry.isfile() or entry.isdir()):
                raise ValueError("Source archive contains links/special files: " + entry.name)
    cli = {p.name: sha(p.read_bytes()) for p in (ROOT / "flightcheck_cli").glob("*.py")}
    manifest = {"schema": 1, "distribution": "flightcheck-cli", "version": version,
                "origin": "https://github.com/spring-labs-inc/FlightCheck", "development": dirty,
                "base_revision": base, "source_revision": revision, "source_tree": tree,
                "source_archive_sha256": sha(archive), "source_commit_sha256": sha(commit), "cli_files": cli}
    return manifest, archive, commit


@contextmanager
def staged():
    manifest, archive, commit = payload()
    with tempfile.TemporaryDirectory(prefix="flightcheck-distribution-") as scratch:
        stage = Path(scratch)
        package = stage / "flightcheck_cli"
        package.mkdir()
        for path in (ROOT / "flightcheck_cli").glob("*.py"):
            shutil.copyfile(path, package / path.name)
        (package / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        (package / "source.tar").write_bytes(archive)
        (package / "source-commit.txt").write_bytes(commit)
        for name in ("README.md", "LICENSE"):
            shutil.copyfile(ROOT / name, stage / name)
        config = (ROOT / "pyproject.toml").read_text().replace('build-backend = "build_backend"', 'build-backend = "setuptools.build_meta"').replace('backend-path = ["."]\n', '')
        (stage / "pyproject.toml").write_text(config)
        previous = Path.cwd()
        os.chdir(stage)
        try:
            yield
        finally:
            os.chdir(previous)


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    from setuptools import build_meta
    destination = str(Path(metadata_directory).absolute())
    with staged():
        return build_meta.prepare_metadata_for_build_wheel(destination, config_settings)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    from setuptools import build_meta
    destination = str(Path(wheel_directory).absolute())
    metadata = str(Path(metadata_directory).absolute()) if metadata_directory else None
    with staged():
        return build_meta.build_wheel(destination, config_settings, metadata)


def build_sdist(sdist_directory, config_settings=None):
    from setuptools import build_meta
    destination = str(Path(sdist_directory).absolute())
    with staged():
        return build_meta.build_sdist(destination, config_settings)
