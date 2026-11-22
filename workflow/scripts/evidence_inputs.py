"""Content manifests for explicitly selected gate inputs and test overlays."""

import hashlib
import os
from pathlib import Path
import stat


def sha(data):
    return hashlib.sha256(data).hexdigest()


def describe(path, parents=()):
    path = Path(path).absolute()
    metadata = path.lstat()
    resolved = path.resolve(strict=True)
    if resolved in parents:
        raise ValueError("Input link/directory cycle: " + str(path))
    if path.is_symlink():
        return {"link": os.readlink(path), "target": str(resolved),
                "content": describe(resolved, parents)}
    if stat.S_ISREG(metadata.st_mode):
        data = path.read_bytes()
        after = path.stat()
        if (metadata.st_size, metadata.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Input changed while reading: " + str(path))
        return {"sha256": sha(data), "mode": stat.S_IMODE(metadata.st_mode)}
    if stat.S_ISDIR(metadata.st_mode):
        return {"entries": {child.name: describe(child, (*parents, resolved))
                            for child in sorted(path.iterdir(), key=lambda item: item.name)}}
    raise ValueError("Required input is not a regular file or directory: " + str(path))


def manifest(root, paths):
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or not p for p in paths):
        raise ValueError("inputs/spec must be a nonempty list of paths")
    if len(set(paths)) != len(paths):
        raise ValueError("Input paths must be unique")
    root = Path(root).resolve(strict=True)
    return {name: describe(root / name) for name in paths}
