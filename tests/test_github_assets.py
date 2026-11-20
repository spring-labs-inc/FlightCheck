"""Synthetic public-URL fixtures: these do not qualify a public release."""
import copy
import importlib.util
import inspect
import io
from contextlib import redirect_stdout
from email.message import Message
import shutil
from urllib.request import HTTPSHandler
from urllib.response import addinfourl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_release as release_fixture

ROOT = Path(os.environ.get("FLIGHTCHECK_PRODUCT_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(ROOT / "release"))
spec = importlib.util.spec_from_file_location("github_assets", ROOT / "release/github_assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class GitHubAssetsTests(unittest.TestCase):
    # Use the release owner's clean synthetic build fixture; never build a channel-specific release.
    command = release_fixture.ReleaseTests.__dict__["command"]
    artifacts_copy = release_fixture.ReleaseTests.artifacts_copy

    @classmethod
    def setUpClass(cls):
        release_fixture.ReleaseTests.setUpClass.__func__(cls)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=self.scratch)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def approval(folder):
        return assets.release.sha((Path(folder) / "release.json").read_bytes())

    def call(self, function, folder, *args, approval=None):
        # Same test overlay exercises the original documented API and its additive
        # explicit approval parameter; no compatibility shim changes product bytes.
        kwargs = {}
        if "manifest_sha256" in inspect.signature(function).parameters:
            kwargs["manifest_sha256"] = approval or self.approval(folder)
        return function(folder, *args, **kwargs)

    def cli(self, command, folder, output=None, approval=None):
        args = ["github_assets.py", command, "--artifacts", str(folder)]
        if output is not None:
            args += ["--output", str(output)]
        if "manifest_sha256" in inspect.signature(assets.payload).parameters:
            args += ["--manifest-sha256", approval or self.approval(folder)]
        captured = io.StringIO()
        with patch.object(sys, "argv", args), redirect_stdout(captured):
            status = assets.main()
        return status, json.loads(captured.getvalue())

    def test_prepare_exact_bundle_and_no_overwrite(self):
        before = {p: p.read_bytes() for p in self.artifacts.rglob("*") if p.is_file()}
        output = self.root / "bundle"
        writes = []
        original_open = Path.open

        def observed_open(path, mode="r", *args, **kwargs):
            if any(c in mode for c in "wax+"):
                self.assertEqual({p: p.read_bytes() for p in before}, before)
                writes.append(path)
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", observed_open), patch.object(subprocess, "run", side_effect=AssertionError("no build/upload")), patch.object(assets, "read_get", side_effect=AssertionError("no network")):
            result = self.call(assets.prepare, self.artifacts, output)
        self.assertEqual(result["status"], "private_bundle_prepared")
        self.assertIn("separate explicit grant", result["publication"])
        self.assertTrue(writes)
        for name, value in self.record["files"].items():
            data = (output / name).read_bytes()
            self.assertEqual(data, (self.artifacts / "dist" / name).read_bytes())
            self.assertEqual(assets.release.sha(data), value["sha256"])
        manifest = (output / "release.json").read_bytes()
        self.assertEqual(manifest, (self.artifacts / "release.json").read_bytes())
        expected = "".join(assets.release.sha((output / n).read_bytes()) + "  " + n + "\n"
                           for n in sorted([*self.record["files"], "release.json"]))
        self.assertEqual((output / "SHA256SUMS").read_text(), expected)
        notes = (output / "release-notes.md").read_text()
        for text in [self.record["version"], self.record["source"]["source_revision"], "FSL-1.1-MIT", "Python >=3.9", "POSIX", "manual prepare/check/footer", "project migration/removal is unsupported"]:
            self.assertIn(text, notes)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        with self.assertRaises(ValueError):
            self.call(assets.prepare, self.artifacts, output)
        with self.assertRaises(ValueError):
            self.call(assets.prepare, self.artifacts, self.artifacts / "nested")
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def public_fixture(self, folder=None):
        folder = folder or self.artifacts
        record, files = self.call(assets.payload, folder)
        tag = record["tag"]
        metadata = {"id": 71, "tag_name": tag, "draft": False, "prerelease": True,
                    "html_url": assets.WEB + "/releases/tag/" + tag, "assets": []}
        responses = {}
        for i, (name, data) in enumerate(files.items(), 1):
            url = assets.WEB + "/releases/download/" + tag + "/" + name
            metadata["assets"].append({"id": i, "name": name, "browser_download_url": url,
                                       "size": len(data), "state": "uploaded", "digest": "sha256:" + assets.release.sha(data)})
            responses[url] = data
        release_url = assets.API + "/releases/tags/" + tag
        reference_url = assets.API + "/git/ref/tags/" + tag
        reference = {"ref": "refs/tags/" + tag, "object": {"type": "commit", "sha": record["source"]["source_revision"]}}
        responses[release_url] = metadata
        responses[reference_url] = reference
        index = "https://pypi.org/pypi/flightcheck/" + record["version"] + "/json"
        registry = {"info": {"name": "flightcheck", "version": record["version"]}, "urls": []}
        for name, info in record["files"].items():
            url = "https://files.pythonhosted.org/packages/fixture/" + name
            registry["urls"].append({"filename": name, "digests": {"sha256": info["sha256"]},
                                      "size": info["size"], "yanked": False, "url": url})
            responses[url] = files[name]
        responses[index] = registry
        return responses, release_url, reference_url, index

    def verify_fixture(self, responses, folder=None, approval=None, during_read=None):
        folder = folder or self.artifacts
        calls = []

        def read(url, size=None, asset=False):
            calls.append((url, size, asset))
            if during_read is not None:
                during_read(url)
            data = responses[url]
            raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            if size is not None:
                self.assertEqual(len(raw), size)
            return raw

        with patch.object(assets, "read_get", side_effect=read), patch.object(assets.release, "read_url", side_effect=read):
            result = self.call(assets.verify_public, folder, approval=approval)
        return result, calls

    def test_public_readback_matches_and_rejects_conflicts(self):
        responses, rel, ref, index = self.public_fixture()
        result, calls = self.verify_fixture(responses)
        self.assertEqual(result["status"], "verified_public_channel_bytes")
        self.assertEqual(result["pypi"]["status"], "verified_public_artifact_bytes")
        self.assertIn("pending fresh", result["installation"])
        self.assertTrue(any(url == index for url, _, _ in calls))
        for row in responses[index]["urls"]:
            self.assertTrue(any(url == row["url"] for url, _, _ in calls))
        wheel_url = next(row["url"] for row in responses[index]["urls"] if row["filename"].endswith(".whl"))
        wrong = copy.deepcopy(responses)
        original = wrong[wheel_url]
        wrong[wheel_url] = bytes([original[0] ^ 1]) + original[1:]
        with self.assertRaisesRegex(ValueError, "downloaded bytes"):
            self.verify_fixture(wrong)
        for key, value in [("tag_name", "vwrong"), ("draft", True), ("prerelease", False), ("html_url", "https://example.invalid/release")]:
            with self.subTest(key=key):
                wrong = copy.deepcopy(responses)
                wrong[rel][key] = value
                with self.assertRaises(ValueError):
                    self.verify_fixture(wrong)
        alterations = [lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0])),
                       lambda rows: rows.append(dict(rows[0], name="unexpected.whl")),
                       lambda rows: rows[0].update(size=1),
                       lambda rows: rows[0].update(digest="sha256:" + "0" * 64),
                       lambda rows: rows[0].update(browser_download_url="https://example.invalid/asset")]
        for i, change in enumerate(alterations):
            with self.subTest(alteration=i):
                wrong = copy.deepcopy(responses)
                change(wrong[rel]["assets"])
                with self.assertRaises(ValueError):
                    self.verify_fixture(wrong)
        for filename in [*self.record["files"], "release.json", "SHA256SUMS"]:
            wrong = copy.deepcopy(responses)
            url = assets.WEB + "/releases/download/" + self.record["tag"] + "/" + filename
            raw = wrong[url]
            wrong[url] = bytes([raw[0] ^ 1]) + raw[1:]
            with self.assertRaisesRegex(ValueError, "Downloaded GitHub asset bytes"):
                self.verify_fixture(wrong)
        wrong = copy.deepcopy(responses)
        wrong[ref]["object"]["sha"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "source commit"):
            self.verify_fixture(wrong)
        annotated = copy.deepcopy(responses)
        annotated[ref]["object"] = {"type": "tag", "sha": "a" * 40}
        annotated[assets.API + "/git/tags/" + "a" * 40] = {"object": responses[ref]["object"]}
        self.assertEqual(self.verify_fixture(annotated)[0]["source_revision"], self.record["source"]["source_revision"])
        annotated[assets.API + "/git/tags/" + "a" * 40]["object"] = annotated[ref]["object"]
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.verify_fixture(annotated)
        for url in ["http://github.com/a", "https://example.invalid/a", "https://github.com@evil.invalid/a", "https://github.com:444/a"]:
            self.assertFalse(assets.download_origin(url))
            with self.assertRaises(ValueError):
                assets.AssetRedirects().redirect_request(None, None, 302, "Found", {}, url)
        with self.assertRaises(ValueError):
            assets.NoRedirects().redirect_request(None)

    def test_ineligible_artifacts_and_publication_hold(self):
        folder = self.artifacts_copy()
        record = copy.deepcopy(self.record)
        record.update(kind="review", release_eligible=False)
        (folder / "release.json").write_text(json.dumps(record))
        output = self.root / "must-not-exist"
        original_open, original_mkdir = Path.open, Path.mkdir
        writes = []

        def observed_open(path, mode="r", *args, **kwargs):
            if any(c in mode for c in "wax+"):
                writes.append(("open", str(path)))
            return original_open(path, mode, *args, **kwargs)

        def observed_mkdir(path, *args, **kwargs):
            writes.append(("mkdir", str(path)))
            return original_mkdir(path, *args, **kwargs)

        with patch.object(Path, "open", observed_open), patch.object(Path, "mkdir", observed_mkdir), patch.object(assets, "read_get", side_effect=AssertionError("no public GET")):
            with self.assertRaises(ValueError):
                self.call(assets.prepare, folder, output)
            with self.assertRaises(ValueError):
                self.call(assets.verify_public, folder)
        self.assertFalse(output.exists())
        self.assertEqual(writes, [])
        development = self.development_release()
        with patch.object(Path, "open", observed_open), patch.object(Path, "mkdir", observed_mkdir):
            with self.assertRaises(ValueError):
                self.call(assets.prepare, development, output)
        self.assertEqual(writes, [])
        self.assertFalse(output.exists())
        document = (ROOT / "release/github-assets.md").read_text()
        for text in ["separate explicit owner grant", "same retained wheel and sdist", "skip-existing", "readback", "project migration/removal", "FSL-1.1-MIT"]:
            self.assertIn(text.lower(), document.lower())
        result = subprocess.run([sys.executable, "-B", str(ROOT / "release/github_assets.py"), "upload", "--artifacts", str(folder)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_canonical_output_containment(self):
        folder = self.artifacts_copy()
        checkout = self.root / "checkout"
        checkout.mkdir()
        shutil.copyfile(ROOT / "pyproject.toml", checkout / "pyproject.toml")
        alias = self.root / "alias"
        alias.mkdir()
        before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
        existing = self.root / "existing"
        existing.mkdir()
        (existing / "sentinel").write_bytes(b"owner bytes")
        with patch.object(assets.release, "ROOT", checkout):
            for target in [alias / ".." / folder.name / "leak", alias / ".." / "checkout" / "leak", existing]:
                with self.subTest(target=str(target)):
                    status, result = self.cli("prepare", folder, target)
                    self.assertEqual(status, 1, result)
                    self.assertEqual(result["status"], "failed")
                    self.assertFalse((target.resolve() / "release.json").exists())
            self.assertEqual(self.cli("prepare", folder, self.root / "external")[0], 0)
        self.assertEqual((existing / "sentinel").read_bytes(), b"owner bytes")
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertFalse((folder / "leak").exists())
        self.assertFalse((checkout / "leak").exists())

    def test_transport_request_boundary(self):
        trace = []
        opened = []
        routes = {
            "https://github.com/allowed": (302, "https://release-assets.githubusercontent.com/fixture", b""),
            "https://release-assets.githubusercontent.com/fixture": (200, None, b"allowed"),
            "https://github.com/off-origin": (302, "https://example.invalid/forbidden", b""),
            "https://github.com/downgrade": (302, "http://example.invalid/forbidden", b""),
            "https://pypi.org/redirect": (302, "https://example.invalid/forbidden", b""),
            "https://example.invalid/forbidden": (200, None, b"forbidden"),
        }

        def transport(handler, request):
            url = request.full_url
            trace.append(url)
            status, location, body = routes[url]
            headers = Message()
            if location is not None:
                headers["Location"] = location
            response = addinfourl(io.BytesIO(body), headers, url, status)
            response.msg = "Found" if status == 302 else "OK"
            opened.append(response)
            return response

        with patch.object(HTTPSHandler, "https_open", transport):
            self.assertEqual(assets.read_get("https://github.com/allowed", 7, asset=True), b"allowed")
            for path in ["off-origin", "downgrade"]:
                with self.assertRaises(ValueError):
                    assets.read_get("https://github.com/" + path, asset=True)
            with self.assertRaises(ValueError):
                assets.release.read_url("https://pypi.org/redirect")
        for response in opened:
            response.close()
        self.assertNotIn("https://example.invalid/forbidden", trace)
        self.assertNotIn("http://example.invalid/forbidden", trace)
        responses, _, _, index = self.public_fixture()
        row = responses[index]["urls"][0]
        row["url"] = row["url"].replace("files.pythonhosted.org", "files.pythonhosted.org:444")
        calls = []

        def registry_read(url, size=None):
            calls.append(url)
            data = responses[url] if url in responses else b"unused forbidden body"
            return data if isinstance(data, bytes) else json.dumps(data).encode()

        with patch.object(assets.release, "read_url", side_effect=registry_read):
            with self.assertRaises(ValueError):
                assets.release.verify_index(self.artifacts)
        self.assertEqual(calls, [index])
        print("TRANSPORT_TRACE", json.dumps({"redirects": trace, "nondefault_port": calls}))

    def alternate_release(self):
        source = self.root / "source-b"
        shutil.copytree(self.source, source)
        (source / "synthetic-alternate-source.txt").write_text("Distinct internally valid source for snapshot control.\n")
        for args in [["add", "."], ["-c", "user.name=Alternate fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "Alternate synthetic release"], ["tag", "-f", "v0.1.0a1"]]:
            subprocess.run(["git", "-C", str(source), *args], env=self.env, check=True, capture_output=True)
        folder = self.root / "release-b"
        self.command("prepare", "--output", folder, "--tag", "v0.1.0a1", script=source / "release/release.py")
        return folder

    def development_release(self):
        source = self.root / "development-source"
        shutil.copytree(self.source, source)
        (source / "uncommitted-review-source.txt").write_text("Genuine embedded development snapshot.\n")
        folder = self.root / "development-artifacts"
        self.command("prepare", "--review", "--output", folder, script=source / "release/release.py")
        record = json.loads((folder / "release.json").read_text())
        self.assertTrue(record["source"]["development"])
        record.update(kind="release", release_eligible=True, tag="v" + record["version"])
        (folder / "release.json").write_text(json.dumps(record))
        return folder

    def test_cross_channel_approved_snapshot(self):
        folder = self.artifacts_copy()
        approved = self.approval(folder)
        alternate = self.alternate_release()
        self.assertNotEqual(self.approval(alternate), approved)
        first, _, _, _ = self.public_fixture(folder)
        second, _, _, index = self.public_fixture(alternate)
        self.verify_fixture(first, folder, approved)
        mixed = copy.deepcopy(first)
        for url, value in second.items():
            if url.startswith("https://pypi.org/") or url.startswith("https://files.pythonhosted.org/"):
                mixed[url] = value
        replaced = []

        def replace_during_download(url):
            if url.startswith(assets.WEB + "/releases/download/") and not replaced:
                shutil.rmtree(folder)
                shutil.copytree(alternate, folder)
                replaced.append(url)

        with self.assertRaises(ValueError):
            self.verify_fixture(mixed, folder, approved, replace_during_download)
        self.assertTrue(replaced)
        with self.assertRaises(ValueError):
            self.verify_fixture(second, alternate, approved)
        self.assertEqual(self.verify_fixture(second, alternate, self.approval(alternate))[0]["pypi"]["manifest_sha256"], self.approval(alternate))
        self.assertEqual(second[index]["info"]["version"], self.record["version"])

    def test_eligibility_before_creation(self):
        folder = self.artifacts_copy()
        self.assertEqual(self.cli("prepare", folder, self.root / "eligible")[0], 0)
        review = copy.deepcopy(self.record)
        review.update(kind="review", release_eligible=False)
        (folder / "release.json").write_text(json.dumps(review))
        development = self.development_release()
        original_open, original_mkdir = Path.open, Path.mkdir
        for label, supplied in [("review", folder), ("forged-development", development)]:
            operations = []

            def observed_open(path, mode="r", *args, **kwargs):
                if any(c in mode for c in "wax+"):
                    operations.append(("open", str(path)))
                return original_open(path, mode, *args, **kwargs)

            def observed_mkdir(path, *args, **kwargs):
                operations.append(("mkdir", str(path)))
                return original_mkdir(path, *args, **kwargs)

            output = self.root / label
            with patch.object(Path, "open", observed_open), patch.object(Path, "mkdir", observed_mkdir):
                status, result = self.cli("prepare", supplied, output)
            self.assertEqual(status, 1, result)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(operations, [], label)
            self.assertFalse(output.exists())

    def test_malformed_readback_response(self):
        responses, rel, ref, _ = self.public_fixture()
        for key, value in [(rel, []), (ref, {"ref": "refs/tags/" + self.record["tag"], "object": None})]:
            with self.subTest(response=key):
                wrong = copy.deepcopy(responses)
                wrong[key] = value

                def read(url, size=None, asset=False):
                    data = wrong[url]
                    return data if isinstance(data, bytes) else json.dumps(data).encode()

                args = ["github_assets.py", "verify-public", "--artifacts", str(self.artifacts)]
                if "manifest_sha256" in inspect.signature(assets.payload).parameters:
                    args += ["--manifest-sha256", self.approval(self.artifacts)]
                output = io.StringIO()
                with patch.object(sys, "argv", args), patch.object(assets, "read_get", side_effect=read), redirect_stdout(output):
                    status = assets.main()
                self.assertEqual(status, 1)
                self.assertEqual(json.loads(output.getvalue())["status"], "failed")
        self.assertEqual(self.verify_fixture(responses)[0]["status"], "verified_public_channel_bytes")


if __name__ == "__main__":
    unittest.main()
