"""Controller-owned byte capture; validation never rewrites a native final reply."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile

from capture_check import evidence_directory, write_json
from handoff_schema import response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--input", default="-", help="Exact native final-message file, or - for binary stdin")
    parser.add_argument("--kind", choices=("review", "challenge"), default="review")
    parser.add_argument("--validate", action="store_true", help="Structural validation only; never final approval")
    args = parser.parse_args()
    try:
        root = evidence_directory(args.evidence_dir, Path.cwd(), create=False)
        directory = root / "captures"
        directory.mkdir(mode=0o700, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="native-", suffix=".bin", dir=directory)
        path = Path(name)
        record = {"path": str(path), "source": "stdin" if args.input == "-" else str(Path(args.input).absolute()),
                  "kind": args.kind, "complete": False, "validation": "not-run"}
        digest = hashlib.sha256()
        count = 0
        code = 0
        def interrupted(signum, frame):
            raise SystemExit(128 + signum)
        handlers = {signum: signal.signal(signum, interrupted) for signum in (signal.SIGINT, signal.SIGTERM)}
        try:
            source = sys.stdin.buffer if args.input == "-" else open(args.input, "rb")
            try:
                with os.fdopen(fd, "wb") as output:
                    while True:
                        chunk = source.read1(65536) if hasattr(source, "read1") else source.read(65536)
                        if not chunk:
                            break
                        output.write(chunk)
                        output.flush()
                        digest.update(chunk)
                        count += len(chunk)
                    os.fsync(output.fileno())
                record["complete"] = True
            finally:
                if source is not sys.stdin.buffer:
                    source.close()
        except SystemExit as error:
            code = int(error.code)
            record["error"] = "Capture interrupted; partial bytes retained"
        except OSError as error:
            code = 2
            record["error"] = str(error)
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
            retained = path.read_bytes()
            record.update(sha256=hashlib.sha256(retained).hexdigest(), bytes=len(retained))
            write_json(path.with_suffix(".json"), record)
        if record["complete"] and args.validate:
            try:
                response(root, path, args.kind)
                record["validation"] = "valid-structure"
            except (OSError, ValueError, TypeError, KeyError) as error:
                record.update(validation="invalid", error=str(error))
                code = 2
            write_json(path.with_suffix(".json"), record)
        print(json.dumps(record, indent=2))
        return code
    except (OSError, ValueError) as error:
        parser.exit(2, "Cannot retain native reviewer output: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
