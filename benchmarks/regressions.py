"""Version 2 known-case qualification, separate from the frozen private evaluator.

Run in a fresh process with the target's pinned interpreter/dependencies. Reports
contain native observations; failures never trigger repairs to frozen candidates.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

VERSION = 2


def require(condition, message):
    # Qualification must still enforce observations if Python uses -O.
    if not condition:
        raise AssertionError(message)


def django_cases(source, check):
    sys.path.insert(0, str(source))
    from django.conf import settings
    settings.configure(INSTALLED_APPS=[], DATABASES={"default": {
        "ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        SECRET_KEY="synthetic-qualification", DEFAULT_AUTO_FIELD="django.db.models.AutoField")
    import django
    django.setup()
    from django.db import connection, models
    from django.db.models import F
    from django.db.models.fields.tuple_lookups import TupleIn

    class Entry(models.Model):
        tenant = models.IntegerField()
        number = models.IntegerField()
        label = models.CharField(max_length=20)
        pk = models.CompositePrimaryKey("tenant", "number")

        class Meta:
            app_label = "benchmark_qualification"

    with connection.schema_editor() as editor:
        editor.create_model(Entry)
    Entry.objects.bulk_create([Entry(tenant=1, number=1, label="keep"),
                              Entry(tenant=1, number=2, label="drop"),
                              Entry(tenant=2, number=1, label="keep")])

    def membership(explicit=False, shadow=False):
        rhs = Entry.objects.filter(label="keep")
        if shadow:
            rhs = rhs.extra(select={"number": "2"})
        if explicit:
            rhs = rhs.values("pk")
        before = str(rhs.query)
        actual = set(Entry.objects.filter(pk__in=rhs).values_list("tenant", "number"))
        require(actual == {(1, 1), (2, 1)}, repr(actual))
        require(str(rhs.query) == before, "Membership lookup mutated the caller query")
        return {"rows": sorted(actual), "caller_unchanged": True}

    def direct():
        rhs = Entry.objects.filter(label="keep")
        before = str(rhs.query), rhs.query.has_select_fields
        lookup = TupleIn((F("tenant"), F("number")), rhs.query)
        require((str(rhs.query), rhs.query.has_select_fields) == before, "Direct TupleIn mutated its caller")
        actual = set(Entry.objects.filter(lookup).values_list("tenant", "number"))
        require(actual == {(1, 1), (2, 1)}, repr(actual))
        return {"rows": sorted(actual), "caller_unchanged": True}

    def reject(fields):
        rhs = Entry.objects.values(*fields).query
        try:
            # Validation must count actual SQL columns (pk expands to two).
            list(Entry.objects.filter(pk__in=rhs))
        except ValueError as error:
            return {"exception": "ValueError", "message": str(error)}
        raise AssertionError("Invalid projected SQL width was accepted")

    def literal():
        rows = set(Entry.objects.filter(pk__in=[(1, 1), (2, 1)]).values_list("tenant", "number"))
        require(rows == {(1, 1), (2, 1)}, repr(rows))
        return {"rows": sorted(rows)}

    check("implicit-queryset-membership", membership)
    check("explicit-composite-pk-control", lambda: membership(explicit=True))
    check("direct-tuple-lookup-caller-isolation", direct)
    check("reject-one-sql-column", lambda: reject(["number"]))
    check("reject-three-sql-columns", lambda: reject(["pk", "number"]))
    check("implicit-projection-shadowing-extra-alias", lambda: membership(shadow=True))
    check("literal-tuple-control", literal)


def ripgrep_cases(binary, scratch, check):
    def pipe(payload):
        command = [str(binary), "--line-buffered", "^x$", "-"]
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) as process:
            try:
                process.stdin.write(payload)
                process.stdin.flush()
                output = bytearray()
                deadline = time.monotonic() + 2
                with selectors.DefaultSelector() as poll:
                    poll.register(process.stdout, selectors.EVENT_READ)
                    while len(output) < len(payload):
                        remaining = deadline - time.monotonic()
                        require(remaining > 0 and poll.select(remaining),
                                "No complete line within two seconds while stdin remained open")
                        chunk = os.read(process.stdout.fileno(), 4096)
                        require(bool(chunk), "Search terminated before emitting the complete line")
                        output.extend(chunk)
                require(output == payload, repr(output))
                process.stdin.close()
                require(process.wait(timeout=5) == 0, "Search exited unsuccessfully")
                return {"command": command, "input_hex": payload.hex(), "stdout_hex": output.hex(),
                        "stdin_open_when_observed": True}
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    fixture = scratch / "files"
    fixture.mkdir()
    (fixture / "hay").write_bytes(b"a\nb\0\n")

    def binary_file(text=False):
        command = [str(binary), "--no-mmap", "--line-buffered", *(["--text"] if text else []),
                   "-l", "^a$", "-g", "hay", "."]
        result = subprocess.run(command, cwd=fixture, capture_output=True, timeout=10)
        expected = (0, b"./hay\n") if text else (1, b"")
        require((result.returncode, result.stdout) == expected, repr((result.returncode, result.stdout, result.stderr)))
        return {"command": command, "exit_code": result.returncode, "stdout_hex": result.stdout.hex()}

    # Reproduce the incremental-reader boundary with a UTF-8 BOM. Compare with
    # this same binary's ordinary file behavior, including redirected regular stdin.
    boundary = scratch / "boundary"
    boundary.write_bytes(b"\xef\xbb\xbfa\n" + b"x" * 65531 + b"\0a\n")

    def bom(redirected):
        base = [str(binary), "--no-mmap", "-l", "^a$"]

        def invoke(line_buffered):
            command = base + (["--line-buffered"] if line_buffered else [])
            if redirected:
                with boundary.open("rb") as stream:
                    return subprocess.run(command + ["-"], stdin=stream, capture_output=True, timeout=10)
            return subprocess.run(command + [str(boundary)], capture_output=True, timeout=10)

        ordinary, incremental = invoke(False), invoke(True)
        require(ordinary.returncode in (0, 1), repr(ordinary.stderr))
        require((incremental.returncode, incremental.stdout) == (ordinary.returncode, ordinary.stdout), repr({
            "ordinary": [ordinary.returncode, ordinary.stdout.hex()],
            "line_buffered": [incremental.returncode, incremental.stdout.hex()]}))
        return {"fixture_sha256": hashlib.sha256(boundary.read_bytes()).hexdigest(),
                "exit_code": incremental.returncode, "stdout_hex": incremental.stdout.hex()}

    check("two-byte-first-line", lambda: pipe(b"x\n"))
    check("multiple-short-lines", lambda: pipe(b"x\nx\n"))
    check("implicit-binary-file-filtering", binary_file)
    check("explicit-text-control", lambda: binary_file(text=True))
    check("bom-buffer-boundary-named-file", lambda: bom(False))
    check("bom-buffer-boundary-regular-stdin", lambda: bom(True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("django", "ripgrep"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.target == "django" and (args.source is None or not (args.source / "django").is_dir()):
        parser.error("Django requires an explicit source checkout")
    if args.target == "ripgrep" and (args.binary is None or not args.binary.is_file()):
        parser.error("ripgrep requires an explicit built binary")
    cases = []

    def check(name, function):
        started = time.monotonic()
        try:
            observation = function()
            cases.append({"id": args.target + ":" + name, "passed": True, "observation": observation,
                          "seconds": time.monotonic() - started})
        except Exception as error:
            cases.append({"id": args.target + ":" + name, "passed": False,
                          "error": type(error).__name__ + ": " + str(error),
                          "seconds": time.monotonic() - started})

    with tempfile.TemporaryDirectory(prefix="flightcheck-qualification-") as scratch:
        if args.target == "django":
            django_cases(args.source.resolve(), check)
        else:
            ripgrep_cases(args.binary.resolve(), Path(scratch), check)
    report = {"suite_version": VERSION, "suite_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "target": args.target, "cases": cases, "passed": bool(cases) and all(c["passed"] for c in cases),
              "interpretation": "Known-case qualification; does not replace or rewrite frozen benchmark results."}
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    coverage = {"passed": [], "skipped": [], "expected_failures": [], "failed": []}
    for case in cases:
        coverage["passed" if case["passed"] else "failed"].append(case["id"])
    (args.output / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
