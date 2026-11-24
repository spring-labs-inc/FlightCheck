"""Private, recoverable project writes around the canonical installer.

The lock coordinates this CLI's apply/recover calls. It is not a flight-startup
lock: init refuses changes to an existing installation in this first version.
"""
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from .source import encoded, sha


def no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Symlink path is unsupported: " + str(part))
    return path


def private_dir(path, create=True):
    no_links(path)
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.exists() and (not path.is_dir() or path.stat().st_uid != os.geteuid() or stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise ValueError("Private installer storage must be owner-only (0700): " + str(path))
    return path


def directory(root, create=True):
    configured = os.environ.get("FLIGHTCHECK_INSTALLER_STATE_DIR")
    base = Path(configured).expanduser() if configured else Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "flightcheck/installer"
    if not base.is_absolute():
        raise ValueError("Installer state directory must be absolute")
    if base == root or root in base.parents:
        raise ValueError("Keep installer plans/backups outside the project")
    base = private_dir(base, create)
    return private_dir(base / sha(str(root).encode())[:24], create)


def atomic(path, data):
    no_links(path)
    fd, pending = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        sync_dir(path.parent)
    finally:
        Path(pending).unlink(missing_ok=True)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def locked(root):
    import fcntl
    state = directory(root)
    path = no_links(state / "lock")
    with path.open("a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield state


def journal(state):
    path = no_links(state / "transaction.json")
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if value.get("schema") != 1 or value.get("status") not in ("prepared", "rollback_required", "rolled_back", "committed"):
        raise ValueError("Invalid recovery journal: " + str(path))
    return value


def pending(root):
    state = directory(root, False)
    value = journal(state)
    if value and value["status"] in ("prepared", "rollback_required"):
        return state, value
    return None


def file_state(module, root, name):
    path = module.safe_path(root, name)
    if not path.exists():
        return None, None
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Managed path is not a regular file: " + name)
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def operation_state(module, root, operations):
    rows = []
    for op in operations:
        before, mode = file_state(module, root, op["path"])
        if before != op["before"]:
            raise ValueError("Project changed during planning: " + op["path"])
        rows.append({"path": op["path"], "action": op["action"], "before": sha(before) if before is not None else None,
                     "after": sha(op["after"]), "mode": mode,
                     "after_mode": op.get("after_mode", mode if mode is not None else 0o644)})
    return rows


def snapshot(module, root, state, operations):
    folder = private_dir(state / ("backup-" + uuid.uuid4().hex))
    records, dirs = [], set()
    for op in operations:
        if op["action"] == "unchanged":
            continue
        before, mode = file_state(module, root, op["path"])
        if before != op["before"]:
            raise ValueError("Project changed before backup: " + op["path"])
        path = module.safe_path(root, op["path"])
        for parent in path.parents:
            if parent == root:
                break
            if not parent.exists():
                dirs.add(str(parent.relative_to(root)))
        backup = None
        if before is not None:
            backup = str((folder / (str(len(records)) + ".bin")).relative_to(state))
            atomic(state / backup, before)
        temporary = str(path.with_name(".flightcheck-" + uuid.uuid4().hex + ".tmp").relative_to(root))
        if module.safe_path(root, temporary).exists():
            raise ValueError("Temporary write path already exists")
        records.append({"path": op["path"], "temporary": temporary, "before": sha(before) if before is not None else None,
                        "before_mode": mode, "after": sha(op["after"]),
                        "after_mode": op.get("after_mode", mode if mode is not None else 0o644),
                        "mode_transition": "after_mode" in op and op["after_mode"] != (mode if mode is not None else 0o644),
                        "backup": backup})
    value = {"schema": 1, "target": str(root), "status": "prepared", "files": records,
             "created_directories": sorted(dirs, key=lambda n: len(Path(n).parts), reverse=True)}
    atomic(state / "transaction.json", encoded(value))
    return value


def restore(module, root, state, value):
    if value.get("target") != str(root) or not isinstance(value.get("files"), list):
        raise ValueError("Recovery journal targets another project")
    # Check EVERY file before restoring anything; later owner edits are never
    # overwritten or partially mixed with a rollback of the other files.
    originals = {}
    temporaries = []
    for row in value["files"]:
        temporary = row.get("temporary")
        if temporary is not None:
            path = module.safe_path(root, temporary)
            if (path.parent != module.safe_path(root, row["path"]).parent
                    or not re.fullmatch(r"\.flightcheck-[a-f0-9]{32}\.tmp", path.name)):
                raise ValueError("Unsafe journaled temporary path")
            data, temporary_mode = file_state(module, root, temporary)
            if data is not None:
                if (sha(data) not in {sha(b""), row["before"], row["after"]}
                        or temporary_mode not in {0o600, row["before_mode"], row["after_mode"]}):
                    raise ValueError("Recovery incomplete: modified or partial temporary write retained at " + str(path)
                                     + "; inspect it with the original backup and journal at " + str(state))
                temporaries.append(path)
        current, mode = file_state(module, root, row["path"])
        identity = sha(current) if current is not None else None
        allowed = {(row["before"], row["before_mode"]), (row["after"], row["after_mode"])}
        if row.get("mode_transition"):
            allowed.add((row["after"], row["before_mode"] if row["before_mode"] is not None else 0o644))
        if (identity, mode) not in allowed:
            raise ValueError("Recovery conflict; preserve owner changes at " + row["path"] + ". Original backup retained in " + str(state))
        if row["before"] is not None:
            if not isinstance(row["backup"], str) or not re.fullmatch(r"backup-[a-f0-9]{32}/[0-9]+\.bin", row["backup"]):
                raise ValueError("Unsafe recovery backup path")
            backup = no_links(state / row["backup"]).read_bytes()
            if sha(backup) != row["before"]:
                raise ValueError("Recovery backup hash mismatch: " + row["path"])
            originals[row["path"]] = backup
    for path in temporaries:
        path.unlink()
    for row in reversed(value["files"]):
        current, mode = file_state(module, root, row["path"])
        if (sha(current) if current is not None else None, mode) == (row["before"], row["before_mode"]):
            continue
        path = module.safe_path(root, row["path"])
        if row["before"] is None:
            path.unlink()
        else:
            # Publish original bytes and permissions together. A crash after
            # replacement is already a complete, recognizable restored state.
            module.write_file(root, row["path"], current, originals[row["path"]],
                              temporary=row.get("temporary"), mode=row["before_mode"])
    for name in value["created_directories"]:
        # Reuse file-safe validation on a nonexistent child before rmdir.
        path = module.safe_path(root, name + "/.recovery-path-check").parent
        try:
            path.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            # Unrelated owner files in an otherwise newly created directory stay.
            if not path.is_dir() or not any(path.iterdir()):
                raise
    value["status"] = "rolled_back"
    atomic(state / "transaction.json", encoded(value))


def apply(module, root, operations, verify, state=None):
    with (locked(root) if state is None else nullcontext(state)) as state:
        existing = journal(state)
        if existing and existing["status"] in ("prepared", "rollback_required"):
            raise ValueError("Interrupted installation; run flightcheck recover first. Journal: " + str(state / "transaction.json"))
        record = snapshot(module, root, state, operations)
        try:
            # The durable transaction owns rollback. The source CLI retains its
            # legacy fallback, but must not restore files before our conflict check.
            module.apply_plan(root, operations, rollback_on_error=False,
                              temporary_paths={row["path"]: row["temporary"] for row in record["files"]})
            # Older pinned installers preserve old modes; the journal also records
            # this intermediate state so interruption remains recoverable.
            for row in record["files"]:
                if row.get("mode_transition"):
                    module.safe_path(root, row["path"]).chmod(row["after_mode"])
            result = verify()
            record["status"] = "committed"
            atomic(state / "transaction.json", encoded(record))
            return result
        except BaseException as error:
            record["status"] = "rollback_required"
            try:
                atomic(state / "transaction.json", encoded(record))
                restore(module, root, state, record)
            except Exception as recovery:
                raise ValueError("Installation failed: " + str(error) + "; recovery required: " + str(recovery)
                                 + ". Journal: " + str(state / "transaction.json")) from error
            raise ValueError("Installation failed and original project restored: " + str(error)
                             + ". Backups: " + str(state)) from error
