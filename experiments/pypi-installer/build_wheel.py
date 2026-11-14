"""Stage canonical assets, then build a local wheel without checkout writes.

This is not a release job. The output records the actual asset hashes alongside
the Git revision, so a development build never masquerades as pristine Git.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(output, version=None):
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Build output must be outside the source checkout")
    paths = json.loads((HERE / "assets.json").read_text())
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate asset path")
    contents = {}
    for name in paths:
        path = ROOT / name
        if Path(name).is_absolute() or ".." in Path(name).parts or path.resolve() != path:
            raise ValueError("Unsafe asset path: " + name)
        contents[name] = path.read_bytes()
    config = (HERE / "pyproject.toml").read_text()
    if version is not None:
        # Only a deliberately narrow development-version override is needed here.
        import re
        if not re.fullmatch(r"0\.0\.0\.dev[0-9]+", version):
            raise ValueError("Only local 0.0.0.devN prototype versions are accepted")
        config = config.replace('version = "0.0.0.dev58"', 'version = "' + version + '"')
    selected = version or "0.0.0.dev58"
    source_archive = subprocess.check_output(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT)
    commit_object = subprocess.check_output(["git", "cat-file", "commit", "HEAD"], cwd=ROOT)
    # The embedded installer must come from the recorded, immutable source tree.
    # Development-only experiment assets are separately hashed below.
    for name, data in contents.items():
        if not name.startswith("experiments/"):
            original = subprocess.check_output(["git", "show", "HEAD:" + name], cwd=ROOT)
            if original != data:
                raise ValueError("Canonical installer asset differs from pinned source: " + name)
    manifest = {
        "schema": 1, "prototype": True, "version": selected,
        "origin": "https://github.com/spring-labs-inc/FlightCheck",
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT)),
        "assets": {name: digest(data) for name, data in contents.items()},
        "cli_sha256": digest((HERE / "cli.py").read_bytes()),
        "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
        "source_archive_sha256": digest(source_archive),
        "source_commit_sha256": digest(commit_object),
    }
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="flightcheck-wheel-") as scratch:
        stage = Path(scratch)
        package = stage / "flightcheck_prototype"
        package.mkdir()
        (stage / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
        (package / "__init__.py").write_text('"""Sandbox distribution experiment; no import side effects."""\n')
        shutil.copyfile(HERE / "cli.py", package / "cli.py")
        (package / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        (package / "source.tar").write_bytes(source_archive)
        (package / "source-commit.txt").write_bytes(commit_object)
        for name, data in contents.items():
            destination = package / "assets" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        # Explicit paths include dot-directories, which package-data globs miss.
        data_files = ["manifest.json", "source.tar", "source-commit.txt", *("assets/" + name for name in paths)]
        config += "\n[tool.setuptools.package-data]\nflightcheck_prototype = " + json.dumps(data_files) + "\n"
        (stage / "pyproject.toml").write_text(config)
        subprocess.run([sys.executable, "-B", "-m", "build", "--wheel", "--no-isolation",
                        "--outdir", str(output), str(stage)], check=True)
    return output / ("flightcheck_distribution_prototype-" + selected + "-py3-none-any.whl")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--version")
    args = parser.parse_args()
    print(build(args.output, args.version))
