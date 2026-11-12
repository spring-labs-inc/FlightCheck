"""Fingerprint controller-declared benchmark inputs, including external evidence.

The controller freezes this manifest outside worker storage. Files are mandatory.
Trees include new and removed files; exclusions must name generated paths only.
The manifest itself is included so changing its scope invalidates an old receipt.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path


def fingerprint(manifest):
    manifest = manifest.resolve()
    raw = manifest.read_bytes()
    config = json.loads(raw)
    result = hashlib.sha256(raw)
    result.update(Path(__file__).read_bytes())

    def include(path):
        path = path.absolute()
        result.update(str(path).encode() + b"\0")
        if path.is_symlink():
            # Bind both the link and the linked input; changing either must stale
            # a receipt. Required broken links fail rather than disappearing.
            result.update(b"link\0" + os.fsencode(os.readlink(path)) + b"\0")
            path = path.resolve(strict=True)
            result.update(str(path).encode() + b"\0")
        if not path.is_file():
            raise ValueError("Required input must be a regular file: " + str(path))
        content = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                content.update(chunk)
        # Fixed-size digests keep embedded binary separators from shifting the
        # boundary between adjacent input files in the combined hash.
        result.update(content.digest())

    if not isinstance(config.get("files"), list) or not isinstance(config.get("trees"), list):
        raise ValueError("Input manifest needs explicit files and trees lists")
    if not config["files"] and not config["trees"]:
        raise ValueError("Input manifest is empty")
    for name in sorted(config["files"]):
        include(manifest.parent / name)
    for tree in config["trees"]:
        root = (manifest.parent / tree["path"]).absolute()
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Required source tree is unavailable: " + str(root))
        exclude = tree.get("exclude", [])
        if not isinstance(exclude, list) or any(not isinstance(e, str) or not e or "/" in e for e in exclude):
            raise ValueError("Tree exclusions must be generated path-component names")
        paths = []
        # Prune generated build trees before traversing them.
        def failed(error):
            raise error

        for parent, directories, files in os.walk(root, onerror=failed):
            directories[:] = sorted(d for d in directories if d not in exclude)
            for directory in directories:
                if (Path(parent) / directory).is_symlink():
                    raise ValueError("Source tree contains a linked directory")
            paths.extend(Path(parent) / name for name in files if name not in exclude)
        if not paths:
            raise ValueError("Required source tree contains no inputs")
        result.update(str(root).encode() + b"\0")
        for path in sorted(paths):
            include(path)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        print(fingerprint(args.manifest))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, "Cannot fingerprint required benchmark inputs: " + str(error) + "\n")


if __name__ == "__main__":
    main()
