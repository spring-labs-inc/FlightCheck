"""Prepare and verify FlightCheck releases. This program never uploads packages.

Maintainer tooling requires Python 3.11+. The installed application keeps its
separate Python requirement. GitHub's protected publishing job owns any upload.
"""
import argparse
import base64
from configparser import ConfigParser
import csv
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "spring-labs-inc/FlightCheck"
WORKFLOW = ".github/workflows/release.yml"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def safe_name(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or ".." in path.parts or ".git" in path.parts or str(path) != name:
        raise ValueError("Unsafe archive path: " + name)
    return name


def ordinary(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink paths are not accepted: " + str(path))
    return path


def project():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def git(*args):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(ROOT), *args]).decode().strip()


def tar_files(raw):
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for entry in archive.getmembers():
            name = safe_name(entry.name.rstrip("/"))
            if entry.isdir():
                continue
            if not entry.isfile() or name in result:
                raise ValueError("Duplicate or special archive member: " + name)
            result[name] = (archive.extractfile(entry).read(), 0o755 if entry.mode & 0o111 else 0o644)
    return result


def git_tree(files):
    tree = {}
    for name, (data, mode) in files.items():
        current = tree
        parts = name.split("/")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
            if not isinstance(current, dict):
                raise ValueError("Archive file/directory collision")
        if parts[-1] in current:
            raise ValueError("Archive file/directory collision")
        current[parts[-1]] = (data, mode)

    def object_id(kind, data):
        return hashlib.sha1(kind + b" " + str(len(data)).encode() + b"\0" + data).digest()

    def directory(entries):
        body = b""
        for name, item in sorted(entries.items(), key=lambda row: row[0].encode() + (b"/" if isinstance(row[1], dict) else b"")):
            if isinstance(item, dict):
                mode, identity = b"40000", directory(item)
            else:
                data, permissions = item
                mode = b"100755" if permissions & 0o111 else b"100644"
                identity = object_id(b"blob", data)
            body += mode + b" " + name.encode() + b"\0" + identity
        return object_id(b"tree", body)
    return directory(tree).hex()


def source_payload(files, distribution, version):
    package = {name.removeprefix("flightcheck_cli/"): data for name, data in files.items()
               if name.startswith("flightcheck_cli/")}
    manifest = json.loads(package["manifest.json"])
    archive, commit = package["source.tar"], package["source-commit.txt"]
    if manifest["distribution"] != distribution or manifest["version"] != version:
        raise ValueError("Packaged distribution/version disagree")
    if sha(archive) != manifest["source_archive_sha256"] or sha(commit) != manifest["source_commit_sha256"]:
        raise ValueError("Embedded source hash mismatch")
    revision = hashlib.sha1(b"commit " + str(len(commit)).encode() + b"\0" + commit).hexdigest()
    source = tar_files(archive)
    tree = git_tree(source)
    if (revision != manifest["source_revision"] or tree != manifest["source_tree"]
            or not commit.startswith(("tree " + tree + "\n").encode())):
        raise ValueError("Embedded Git commit/tree mismatch")
    expected_cli = {name.split("/")[-1]: sha(data) for name, (data, _) in source.items()
                    if name.startswith("flightcheck_cli/") and name.count("/") == 1 and name.endswith(".py")}
    if expected_cli != manifest["cli_files"]:
        raise ValueError("Incomplete CLI source inventory")
    expected = set(expected_cli) | {"manifest.json", "source.tar", "source-commit.txt"}
    if set(package) != expected:
        raise ValueError("Unexpected or missing packaged CLI resources")
    for name, digest in expected_cli.items():
        if sha(package[name]) != digest:
            raise ValueError("Packaged CLI bytes differ: " + name)
    # Independently require every canonical installer input, including hidden adapters.
    setup = json.loads(source["setup/manifest.json"][0])
    for component in setup["files"]:
        if component[0] not in source:
            raise ValueError("Incomplete installer source: " + component[0])
    return manifest, source


def metadata_check(raw, name, version, source):
    metadata = BytesParser().parsebytes(raw)
    config = tomllib.loads(source["pyproject.toml"][0].decode())["project"]
    expected = {
        "Metadata-Version": ["2.4"], "Name": [name], "Version": [version],
        "Summary": [config["description"]], "Requires-Python": [config["requires-python"]],
        "Description-Content-Type": ["text/markdown"], "License-Expression": [config["license"]],
        "License-File": config["license-files"], "Dynamic": ["license-file"],
        "Classifier": config["classifiers"],
        "Project-URL": [key + ", " + value for key, value in config["urls"].items()],
    }
    if (config["license"] != "FSL-1.1-MIT"
            or {key.lower() for key in metadata.keys()} != {key.lower() for key in expected}
            or any(metadata.get_all(key) != values for key, values in expected.items())):
        raise ValueError("Distribution metadata differs from reviewed packaging configuration")
    _, separator, body = raw.replace(b"\r\n", b"\n").partition(b"\n\n")
    if not separator or body.rstrip(b"\n") != source["README.md"][0].replace(b"\r\n", b"\n").rstrip(b"\n"):
        raise ValueError("Distribution description differs from reviewed README")


def entry_points(raw):
    entries = ConfigParser()
    entries.read_string(raw.decode())
    if (entries.sections() != ["console_scripts"]
            or dict(entries["console_scripts"]) != {"flightcheck": "flightcheck_cli.cli:main"}):
        raise ValueError("Unexpected executable entry points")


def verify_record(archive, names, prefix):
    rows = list(csv.reader(io.StringIO(archive.read(prefix + "RECORD").decode())))
    if (any(len(row) != 3 for row in rows) or len(rows) != len(names)
            or {row[0] for row in rows} != set(names)):
        raise ValueError("Wheel RECORD inventory differs")
    for name, digest, size in rows:
        if name == prefix + "RECORD":
            if digest or size:
                raise ValueError("Wheel RECORD must leave its own digest empty")
            continue
        data = archive.read(name)
        expected = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        if digest != expected or size != str(len(data)):
            raise ValueError("Wheel RECORD digest/size mismatch: " + name)


def wheel_payload(path, name, version):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [safe_name(item.filename) for item in members]
        if len(names) != len(set(names)) or any(stat.S_ISLNK(item.external_attr >> 16) for item in members):
            raise ValueError("Duplicate or linked wheel members")
        prefix = normalize(name).replace("-", "_") + "-" + version + ".dist-info/"
        if any(not n.startswith(("flightcheck_cli/", prefix)) for n in names):
            raise ValueError("Unexpected wheel payload")
        files = {n: archive.read(n) for n in names if n.startswith("flightcheck_cli/")}
        manifest, source = source_payload(files, name, version)
        metadata_check(archive.read(prefix + "METADATA"), name, version, source)
        entry_points(archive.read(prefix + "entry_points.txt"))
        wheel = BytesParser().parsebytes(archive.read(prefix + "WHEEL"))
        build = tomllib.loads(source["pyproject.toml"][0].decode())["build-system"]
        setuptools_version = next(item.split("==", 1)[1] for item in build["requires"] if item.startswith("setuptools=="))
        expected_wheel = {"Wheel-Version": ["1.0"], "Generator": ["setuptools (" + setuptools_version + ")"],
                          "Root-Is-Purelib": ["true"], "Tag": ["py3-none-any"]}
        if (set(wheel.keys()) != set(expected_wheel)
                or any(wheel.get_all(key) != values for key, values in expected_wheel.items())):
            raise ValueError("WHEEL control metadata differs from reviewed pure-Python build")
        if archive.read(prefix + "licenses/LICENSE") != source["LICENSE"][0]:
            raise ValueError("Missing or altered license notice")
        expected_names = set(files) | {prefix + name for name in (
            "METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "licenses/LICENSE", "RECORD")}
        if set(names) != expected_names or archive.read(prefix + "top_level.txt") != b"flightcheck_cli\n":
            raise ValueError("Unexpected wheel control inventory")
        verify_record(archive, names, prefix)
        return manifest, source


def sdist_payload(path, name, version):
    entries = tar_files(path.read_bytes())
    prefix = normalize(name).replace("-", "_") + "-" + version + "/"
    if any(not n.startswith(prefix) for n in entries):
        raise ValueError("Unexpected sdist root")
    files = {n[len(prefix):]: data for n, (data, _) in entries.items()}
    config = tomllib.loads(files["pyproject.toml"].decode())
    manifest, source = source_payload(files, name, version)
    expected_config = tomllib.loads(source["pyproject.toml"][0].decode())
    # These are the only transformations made by the canonical staging backend.
    expected_config["build-system"]["build-backend"] = "setuptools.build_meta"
    expected_config["build-system"].pop("backend-path")
    if config != expected_config:
        raise ValueError("Sdist build configuration differs from reviewed source")
    egg = normalize(name).replace("-", "_") + ".egg-info/"
    expected_names = ({n for n in files if n.startswith("flightcheck_cli/")}
                      | {"LICENSE", "README.md", "pyproject.toml", "setup.cfg", "PKG-INFO"}
                      | {egg + n for n in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "top_level.txt")})
    if set(files) != expected_names:
        raise ValueError("Unexpected sdist installation/build inputs")
    metadata_check(files["PKG-INFO"], name, version, source)
    if files[egg + "PKG-INFO"] != files["PKG-INFO"]:
        raise ValueError("Sdist metadata copies differ")
    entry_points(files[egg + "entry_points.txt"])
    if (files["README.md"] != source["README.md"][0]
            or files[egg + "top_level.txt"] != b"flightcheck_cli\n"
            or files[egg + "dependency_links.txt"].strip()):
        raise ValueError("Unexpected sdist description, package or dependency inputs")
    setup = ConfigParser()
    setup.read_string(files["setup.cfg"].decode())
    if setup.sections() != ["egg_info"] or dict(setup["egg_info"]) != {"tag_build": "", "tag_date": "0"}:
        raise ValueError("Unexpected generated sdist build options")
    sources = files[egg + "SOURCES.txt"].decode().splitlines()
    if len(sources) != len(set(sources)) or set(sources) != expected_names - {"setup.cfg", "PKG-INFO"}:
        raise ValueError("Sdist source inventory differs")
    if files["LICENSE"] != source["LICENSE"][0]:
        raise ValueError("Sdist license differs")
    return manifest, source


def verify(folder, require_release=False):
    folder = ordinary(folder)
    record = json.loads(ordinary(folder / "release.json").read_text())
    if record.get("schema") != 1 or record.get("kind") not in ("review", "release"):
        raise ValueError("Invalid release record")
    config = project()
    name, version = record["distribution"], record["version"]
    if name != config["name"] or version != config["version"]:
        raise ValueError("Release differs from this reviewed tool's project metadata")
    if set(record["files"]) != {normalize(name).replace("-", "_") + "-" + version + "-py3-none-any.whl",
                               normalize(name).replace("-", "_") + "-" + version + ".tar.gz"}:
        raise ValueError("Release needs exactly its wheel and source distribution")
    dist = ordinary(folder / "dist")
    if {p.name for p in dist.iterdir()} != set(record["files"]):
        raise ValueError("Missing or unexpected distribution files")
    payloads = []
    for filename, expected in record["files"].items():
        path = ordinary(dist / safe_name(filename))
        data = path.read_bytes()
        if not path.is_file() or len(data) != expected["size"] or sha(data) != expected["sha256"]:
            raise ValueError("Artifact digest/size mismatch: " + filename)
        payloads.append(wheel_payload(path, name, version) if filename.endswith(".whl")
                        else sdist_payload(path, name, version))
    manifest, source = payloads[0]
    if payloads[1] != payloads[0] or manifest != record["source"]:
        raise ValueError("Wheel, sdist and approved source provenance differ")
    eligible = record["kind"] == "release" and not manifest["development"] and record["tag"] == "v" + version
    if record["release_eligible"] != eligible or (require_release and not eligible):
        raise ValueError("Review/development artifacts cannot authorize publication")
    if record["license_sha256"] != sha(source["LICENSE"][0]):
        raise ValueError("License record mismatch")
    return record


def prepare(output, review=False, tag=None):
    output = ordinary(output)
    if output == ROOT or ROOT in output.parents or output.exists():
        raise ValueError("Choose a new output directory outside the checkout")
    config = project()
    if not review:
        if git("status", "--porcelain=v1", "--untracked-files=all") or os.environ.get("FLIGHTCHECK_BUILD_DEVELOPMENT"):
            raise ValueError("A release needs clean Git and no development-build flag")
        if tag != "v" + config["version"] or git("rev-parse", "refs/tags/" + tag + "^{commit}") != git("rev-parse", "HEAD"):
            raise ValueError("A release needs its exact version tag at HEAD")
    output.mkdir(parents=True, mode=0o700)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    environment.pop("FLIGHTCHECK_BUILD_DEVELOPMENT", None)
    if review:
        environment["FLIGHTCHECK_BUILD_DEVELOPMENT"] = "1"
    for command, log in [
        ([sys.executable, "-B", "-m", "build", "--wheel", "--sdist", "--no-isolation", "--outdir", str(output / "dist"), str(ROOT)], "prepare.log"),
        ([sys.executable, "-B", "-m", "twine", "check", "--strict"], "metadata.log"),
    ]:
        if log == "metadata.log":
            command += [str(p) for p in sorted((output / "dist").iterdir())]
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        (output / log).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError("Preparation failed; original output: " + str(output / log))
    wheel = next((output / "dist").glob("*.whl"))
    manifest, source = wheel_payload(wheel, config["name"], config["version"])
    record = {"schema": 1, "kind": "review" if review else "release",
              "distribution": config["name"], "version": config["version"], "tag": tag,
              "release_eligible": not review and not manifest["development"],
              "source": manifest, "license_sha256": sha(source["LICENSE"][0]),
              "files": {p.name: {"sha256": sha(p.read_bytes()), "size": p.stat().st_size}
                        for p in sorted((output / "dist").iterdir())}}
    (output / "release.json").write_bytes(encoded(record))
    verify(output, not review)
    return {"status": "prepared", "release_eligible": record["release_eligible"],
            "manifest_sha256": sha((output / "release.json").read_bytes()), "record": record}


def publication_gate(folder, context, expected_manifest, expected_source, reviewed_run, reviewed_artifact, enabled):
    record = verify(folder, True)
    if not enabled or context["mode"] != "publish":
        raise ValueError("Publication is disabled; explicit owner publish mode and repository enablement are required")
    if sha((Path(folder) / "release.json").read_bytes()) != expected_manifest:
        raise ValueError("Approved manifest digest differs")
    if record["source"]["source_revision"] != expected_source or context["current_sha"] != expected_source:
        raise ValueError("Publication source differs from reviewed source")
    run, artifact, environment, workflow = (context[n] for n in ("run", "artifact", "environment", "workflow"))
    if (str(run["id"]) != str(reviewed_run) or run["head_sha"] != expected_source
            or run["event"] != "workflow_dispatch" or run["conclusion"] != "success"
            or run["path"] != WORKFLOW or run["workflow_id"] != workflow["id"]
            or workflow["path"] != WORKFLOW or workflow["state"] != "active"
            or run["repository"]["full_name"] != REPOSITORY):
        raise ValueError("Reviewed workflow/run identity does not match")
    if (str(artifact["id"]) != str(reviewed_artifact) or artifact["name"] != "flightcheck-release"
            or artifact["expired"] or str(artifact["workflow_run"]["id"]) != str(reviewed_run)
            or artifact["workflow_run"]["head_sha"] != expected_source):
        raise ValueError("Reviewed immutable artifact identity does not match")
    if (environment["name"] != "pypi" or not any(
            rule.get("type") == "required_reviewers" and rule.get("reviewers")
            for rule in environment.get("protection_rules", []))):
        raise ValueError("The pypi environment must already have required human reviewers")
    return {"status": "eligible_for_protected_job", "artifact_id": str(reviewed_artifact),
            "source_revision": expected_source, "manifest_sha256": expected_manifest,
            "note": "This validation does not upload or substitute for GitHub environment approval"}


def read_url(url, expected_size=None):
    with urlopen(url, timeout=30) as response:
        if response.url != url:
            raise ValueError("Unexpected registry redirect")
        data = response.read((expected_size if expected_size is not None else 4_000_000) + 1)
    if expected_size is not None and len(data) != expected_size:
        raise ValueError("Downloaded artifact size differs")
    return data


def verify_index(folder, test_index=None):
    record = verify(folder, True)
    if test_index:
        parsed = urlsplit(test_index)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password:
            raise ValueError("Test registries must be explicit HTTP IPv4 loopback fixtures")
        base = test_index.rstrip("/")
    else:
        base = "https://pypi.org"
    url = base + "/pypi/" + record["distribution"] + "/" + record["version"] + "/json"
    data = json.loads(read_url(url))
    if (normalize(data["info"]["name"]) != normalize(record["distribution"])
            or data["info"]["version"] != record["version"]):
        raise ValueError("Registry project/version mismatch")
    entries = data["urls"]
    if len(entries) != len(record["files"]) or {row["filename"] for row in entries} != set(record["files"]):
        raise ValueError("Registry inventory differs")
    for entry in entries:
        expected = record["files"][entry["filename"]]
        if entry.get("yanked") or entry["digests"]["sha256"] != expected["sha256"] or entry["size"] != expected["size"]:
            raise ValueError("Registry artifact digest, size or yanked state differs")
        parsed = urlsplit(entry["url"])
        allowed = (parsed.scheme == "https" and parsed.hostname == "files.pythonhosted.org") if not test_index else (
            parsed.scheme == "http" and parsed.netloc == urlsplit(base).netloc)
        if not allowed or parsed.username or parsed.password:
            raise ValueError("Unexpected artifact download origin")
        if sha(read_url(entry["url"], expected["size"])) != expected["sha256"]:
            raise ValueError("Registry metadata and downloaded bytes disagree")
    return {"status": "simulated_registry_match" if test_index else "verified_public_artifact_bytes",
            "simulated": bool(test_index), "index": base,
            "manifest_sha256": sha((Path(folder) / "release.json").read_bytes()),
            "distribution": record["distribution"], "version": record["version"],
            "source_revision": record["source"]["source_revision"],
            "public_installation": "pending fresh public-index pipx installation",
            "native_qualification": "pending separate client/reviewer/browser observations under #14"}


def docs_proposal(folder):
    record = verify(folder)
    original = (ROOT / "README.md").read_text()
    old = 'pipx install "git+https://github.com/spring-labs-inc/FlightCheck.git"'
    if original.count(old) != 1:
        raise ValueError("README quickstart changed; reconcile the proposal explicitly")
    proposed = original.replace(old, "pipx install " + record["distribution"] + "==" + record["version"])
    proposed = proposed.replace("Install from Git with [pipx]", "Install with [pipx]")
    proposed = proposed.replace("PyPI installation will replace this Git channel after a release is published and verified.",
                                "For source installation and retained versions, use the setup guide.")
    return {"status": "proposal_only", "apply_after": "Verified owner-controlled PyPI publication AND fresh public-index installation",
            "manifest_sha256": sha((Path(folder) / "release.json").read_bytes()),
            "before_sha256": sha(original.encode()), "readme": proposed,
            "note": "No repository file was changed. Public availability and native qualification are not established."}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify", "gate", "verify-index", "docs"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--tag")
    parser.add_argument("--require-release", action="store_true")
    parser.add_argument("--context", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--source-sha")
    parser.add_argument("--reviewed-run-id")
    parser.add_argument("--reviewed-artifact-id")
    parser.add_argument("--test-index")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if not args.output:
                raise ValueError("prepare requires --output outside the checkout")
            result = prepare(args.output, args.review, args.tag)
        else:
            if not args.artifacts:
                raise ValueError("--artifacts is required")
            if args.command == "verify":
                record = verify(args.artifacts, args.require_release)
                result = {"status": "verified", "release_eligible": record["release_eligible"], "record": record}
            elif args.command == "gate":
                if not all((args.context, args.manifest_sha256, args.source_sha, args.reviewed_run_id, args.reviewed_artifact_id)):
                    raise ValueError("gate requires current trusted context and all reviewed identities")
                result = publication_gate(args.artifacts, json.loads(ordinary(args.context).read_text()),
                                          args.manifest_sha256, args.source_sha, args.reviewed_run_id,
                                          args.reviewed_artifact_id, os.environ.get("FLIGHTCHECK_PYPI_PUBLISH_ENABLED") == "true")
            elif args.command == "verify-index":
                result = verify_index(args.artifacts, args.test_index)
            else:
                result = docs_proposal(args.artifacts)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile, tarfile.TarError) as error:
        print(json.dumps({"status": "incomplete", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
