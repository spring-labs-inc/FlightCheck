"""Prepare private GitHub assets and verify public readback; never build or upload."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import release

API = "https://api.github.com/repos/" + release.REPOSITORY
WEB = "https://github.com/" + release.REPOSITORY


def payload(folder, manifest_sha256):
    folder = release.ordinary(folder)
    raw = (Path(folder) / "release.json").read_bytes()
    if not re.fullmatch(r"[a-f0-9]{64}", manifest_sha256) or release.sha(raw) != manifest_sha256:
        raise ValueError("Release differs from the independently approved manifest SHA-256")
    record = release.verify(folder, require_release=True, expected_manifest_sha256=manifest_sha256)
    files = {name: (Path(folder) / "dist" / name).read_bytes() for name in record["files"]}
    files["release.json"] = (Path(folder) / "release.json").read_bytes()
    if files["release.json"] != raw or json.loads(raw) != record or any(
            len(files[name]) != value["size"] or release.sha(files[name]) != value["sha256"]
            for name, value in record["files"].items()):
        raise ValueError("Reviewed artifacts changed during preparation")
    files["SHA256SUMS"] = "".join(release.sha(data) + "  " + name + "\n"
                                   for name, data in sorted(files.items())).encode()
    return record, files


def notes(record, manifest):
    version, source = record["version"], record["source"]["source_revision"]
    return f"""FlightCheck {version}

Source: {WEB}/commit/{source}
Tag: `{record['tag']}`. Distribution/executable: `flightcheck`.
`release.json` SHA-256: `{release.sha(manifest)}`.

The wheel and sdist must use the exact reviewed #67 build shared with PyPI.
Public channel matching requires a successful retained readback.
Check SHA256SUMS before installation. Build/run/artifact IDs and actual PyPI
attestations belong in the retained release approval; this preparation does
not establish publication, public installation or an OIDC exchange.

Declared application minimum: Python >=3.9 on POSIX. Only recorded tested
combinations are qualified; native Windows and cloud sessions are unqualified.
Native client observations and the accepted manual prepare/check/footer scope:
{WEB}/blob/main/docs/claude-trial-report.md#accepted-native-app-scope
New package bytes need their own retained local/SSH card qualification.

FSL-1.1-MIT: retain LICENSE and notices inside both distributions.
Installation and explicit project setup: {WEB}/blob/main/setup/README.md
Global CLI reinstall/upgrade/uninstall does not migrate or remove a configured
project's pinned workflow/runtime; project migration/removal is unsupported.
"""


def prepare(folder, output, manifest_sha256):
    record, files = payload(folder, manifest_sha256)
    output = release.ordinary(output).resolve()
    source = release.ordinary(folder).resolve()
    if (output.exists() or output == release.ROOT or release.ROOT in output.parents
            or output == source or source in output.parents):
        raise ValueError("Choose a new private output directory outside source and artifacts")
    output.mkdir(mode=0o700, parents=True)
    for name, data in files.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    (output / "release-notes.md").write_text(notes(record, files["release.json"]))
    return {"status": "private_bundle_prepared", "publication": "held: separate explicit grant required",
            "tag": record["tag"], "source_revision": record["source"]["source_revision"],
            "manifest_sha256": release.sha(files["release.json"]),
            "assets": {name: {"sha256": release.sha(data), "size": len(data)}
                       for name, data in files.items()}}


def download_origin(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in ("github.com", "release-assets.githubusercontent.com")
            and parsed.port in (None, 443) and not parsed.username and not parsed.password)


class AssetRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if not download_origin(newurl):
            raise ValueError("Untrusted GitHub asset redirect")
        return super().redirect_request(request, response, code, message, headers, newurl)


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError("Unexpected GitHub API redirect")


def read_get(url, size=None, asset=False):
    handler = AssetRedirects() if asset else NoRedirects()
    request = Request(url, headers={"Accept": "application/octet-stream" if asset else "application/vnd.github+json",
                                    "User-Agent": "FlightCheck-release-verifier",
                                    "X-GitHub-Api-Version": "2026-03-10"})
    with build_opener(handler).open(request, timeout=30) as response:
        data = response.read((size if size is not None else 4_000_000) + 1)
    if (size is not None and len(data) != size) or (size is None and len(data) > 4_000_000):
        raise ValueError("GitHub response length differs")
    return data


def tag_commit(tag):
    reference = json.loads(read_get(API + "/git/ref/tags/" + quote(tag, safe="")))
    if reference.get("ref") != "refs/tags/" + tag:
        raise ValueError("GitHub tag reference differs")
    obj = reference["object"]
    seen = set()
    while obj.get("type") == "tag":
        sha = obj.get("sha", "")
        if not re.fullmatch(r"[a-f0-9]{40}", sha) or sha in seen or len(seen) >= 8:
            raise ValueError("Invalid or cyclic annotated tag")
        seen.add(sha)
        obj = json.loads(read_get(API + "/git/tags/" + sha))["object"]
    if obj.get("type") != "commit" or not re.fullmatch(r"[a-f0-9]{40}", obj.get("sha", "")):
        raise ValueError("GitHub tag does not resolve to a commit")
    return obj["sha"]


def verify_public(folder, manifest_sha256):
    record, expected = payload(folder, manifest_sha256)
    tag = record["tag"]
    metadata = json.loads(read_get(API + "/releases/tags/" + quote(tag, safe="")))
    from packaging.version import Version
    if (metadata.get("tag_name") != tag or metadata.get("draft") is not False
            or metadata.get("prerelease") is not Version(record["version"]).is_prerelease
            or metadata.get("html_url") != WEB + "/releases/tag/" + tag):
        raise ValueError("GitHub release identity/state differs")
    if tag_commit(tag) != record["source"]["source_revision"]:
        raise ValueError("GitHub tag source commit differs")
    assets = metadata["assets"]
    if len(assets) != len(expected) or {row["name"] for row in assets} != set(expected):
        raise ValueError("Missing, duplicate or unexpected GitHub assets")
    identities = {}
    for asset in assets:
        name, data = asset["name"], expected[asset["name"]]
        url = WEB + "/releases/download/" + quote(tag, safe="") + "/" + quote(name, safe="")
        digest = release.sha(data)
        if (asset.get("browser_download_url") != url or asset.get("state") != "uploaded"
                or asset.get("size") != len(data)
                or asset.get("digest") not in (None, "sha256:" + digest)):
            raise ValueError("GitHub asset metadata differs: " + name)
        if read_get(url, len(data), asset=True) != data:
            raise ValueError("Downloaded GitHub asset bytes differ: " + name)
        identities[name] = {"id": asset["id"], "sha256": digest, "size": len(data)}
    # Re-read the actual public index and artifact bodies; no saved/mock receipt can qualify it.
    pypi = release.verify_index(folder, expected_manifest_sha256=manifest_sha256)
    if pypi["manifest_sha256"] != manifest_sha256:
        raise ValueError("PyPI and GitHub were checked against different local release snapshots")
    # Detect changes even if they occurred after the shared verifier's initial read.
    payload(folder, manifest_sha256)
    return {"status": "verified_public_channel_bytes", "release_id": metadata["id"],
            "release_url": metadata["html_url"], "tag": tag, "version": record["version"],
            "source_revision": record["source"]["source_revision"], "assets": identities,
            "manifest_sha256": release.sha(expected["release.json"]), "pypi": pypi,
            "installation": "pending fresh downloaded-wheel and sdist installs and explicit setup/doctor"}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "verify-public"))
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest-sha256", required=True,
                        help="SHA-256 from the independently retained exact-artifact approval")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            if args.output is None:
                raise ValueError("prepare requires --output")
            result = prepare(args.artifacts, args.output, args.manifest_sha256)
        else:
            result = verify_public(args.artifacts, args.manifest_sha256)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
