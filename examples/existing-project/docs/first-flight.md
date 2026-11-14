# A small first FlightCheck flight

Use an existing Python behavioral witness first. Expect to choose setup and delivery, run preflight, obtain an independent Plan challenge, run the native check, inspect its control/spec bindings, and obtain real review. The goal is to preserve an existing contract, not to manufacture a green review or solve a large feature at the same time.

## Choose the environment

Use the project's selected interpreter and dependency/lock files. The reference reporter is tested with Python 3.13 and pytest 9.2.0 and accepts pytest 9.2.x. Re-run its supplied tests when choosing another patch; qualify other versions before widening the adapter. The other shared helpers use Python's standard library on POSIX. Pin optional pytest with the supplied `requirements.dev.txt`; installing FlightCheck does not install dependencies or change global client settings.

Decide the actual default branch, nit tracker, evidence location and delivery permission. Commands below use POSIX `sh` syntax, quoted paths and argument arrays; they are not PowerShell examples. Keep evidence, reports and disposable environments outside the checkout.

For a real adopter, use the [complete setup guide](https://github.com/spring-labs-inc/FlightCheck/blob/main/setup/README.md) first. The disposable helper flight below can also run from source in a fresh controller session explicitly pointed at the shared develop-change skill and read-only reviewer roles. It does not qualify native Claude/Codex client behavior by itself. Installed projects have this guide and example under `.flightcheck/`.

## Prepare one existing witness

From the FlightCheck checkout, choose unused disposable paths and your actual Python:

```sh
python3 -B examples/existing-project/examples/first-flight/prepare.py \
  --project /tmp/flightcheck-first --evidence /tmp/flightcheck-first-evidence \
  --python /absolute/path/to/python --default-branch main \
  --nit-tracker 'Private adoption notes'
```

From an installed project, use `.flightcheck/examples/first-flight/prepare.py`. The command prepares a small Git project, runs the existing native `test_existing.py::test_normalization` witness and captures its actual passing baseline/control. It emits a private task with coverage, spec and phase artifacts, exact native identities and explicit runtime/input configuration. It never creates a reviewer response. The original product archive, Git identity and input manifest remain private with the evidence.

Start a fresh session in the printed project. Select develop-change for its bounded scope and local-only delivery. Follow the shared status instructions to start its browser card. Use the printed interpreter and shared scripts path for every command. Preflight the printed private task, then obtain an actual independent scope-only proposal with `challenge-brief`. Use `challenge-review` for early grounding discussion; register the actual proposal using `challenges` and bind each grounded case to a witness that really asserts it. Add missing assertions and rerun original/current controls under the same updated test overlay when necessary.

Use the task's exact `request.command`, `fingerprint_command`, scope and artifact list with `capture_check.py`. The supplied `pytest_report.py` and `fingerprint.py` are the glue: no custom output parser is needed. Use `--refresh` for a witness that must occur after the actual Plan proposal. Then use `checks`, `next-action` and `review` to expose remaining work. A native pass cannot substitute for independent challenges, qualified controls or real review.

CODE, when applicable, precedes the remaining authoritative checks and the separate EVIDENCE review. Each reviewer uses an enforced read-only session with hooks disabled and required source/evidence readable. Return raw JSON as the complete native final message: no fences, prose or model-authored abridgment. The controller retains the client's original final-message export with `capture_review.py --input PATH --evidence-dir EVIDENCE --kind review --validate`, then passes its returned capture path to `handoff.py requests`/`verdict`. Structural validation is not approval. Preserve the native session/transcript alongside that exact message. A mock JSON plumbing rehearsal must be labeled synthetic and can never serve as the real final review.

## Reporter and fingerprint boundaries

`pytest_report.py --spec TEST_OR_FIXTURE --spec HELPER -- PYTEST_ARGS` writes `coverage.json`, `spec.json` and `phases.json` inside the recorder's `FLIGHTCHECK_REPORT_DIR`. Coverage uses unique actual collected parent node IDs; parametrized IDs stay intact. Setup, call, teardown and supported native pytest/unittest subtest failures cannot be overwritten by a later pass. Subtests stay attached to their real parent ID; their context/events live in phases rather than invented child IDs. A skipped subtest does not turn an otherwise passing parent into a skipped test. See pytest's [report hook](https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_runtest_logreport) and [subtest behavior](https://docs.pytest.org/en/stable/how-to/subtests.html).

Support is serial, single-attempt pytest 9.2.x. Distributed workers and rerun aggregation are not qualified. Unexecuted/incomplete identities are omitted from passing coverage and recorded in phases; a native zero exit with incomplete phases or a changed spec becomes a nonzero adapter result. Native exit status remains separately recorded. Include all three artifacts in the request before freezing and declare `coverage.spec` explicitly.

`fingerprint.py gate --config PATH` binds explicit `root`, `inputs`, absolute `python`, selected distribution `dependencies`, and relevant `environment` names. Required files/trees are read regardless of Git ignores; linked inputs bind link identity and resolved target content. Missing inputs, broken/cyclic links and missing dependencies fail. Dependency versions and installed file bytes are bound; editable/external source trees and lock files still belong in `inputs` when used. Environment values are represented by digests. Keep the resulting manifest private.

`fingerprint.py candidate --root PROJECT` matches the bundled controller's Git identity, including local untracked tool files. It is a candidate label, not proof of gate equivalence. Always pair it with the configured gate fingerprint. The optional `candidate --config PATH` also binds that gate's required ignored/linked/runtime context; use that extended identity only with a project adapter/status publisher configured to use the same identity. Do not mix it with the bundled Git-candidate controller path.

Portable runtime contracts are shipped under `.flightcheck/tests`. Run them without upstream documentation or path edits:

```sh
FLIGHTCHECK_SCRIPTS_ROOT="$PWD/.flightcheck/scripts" \
  /absolute/path/to/python -B -m unittest discover -s .flightcheck/tests -v
```

## Refresh and provenance

Create local tools and finish mutating lint/format/hooks before freezing or reviewing. Git candidate identity includes nonignored local tool files; keep generated evidence outside the repository. Required ignored fixtures and linked inputs must still appear in the gate manifest. A Git ignore rule is not evidence of irrelevance.

After a change, recompute the chosen identity and use `handoff.py refresh --task EVIDENCE/task.json --evidence-dir EVIDENCE --candidate ID`. Refresh changes only `candidate`, leaving `saved_candidate`, original baseline, acceptance, expected outcomes, gates, native witness identities and retained obligations untouched. Run `resume` and `next-action` afterward; old verdicts or receipts do not become current merely because refresh succeeded. It refuses an already changed frozen contract. Genuine scope changes use the existing explicit owner-amendment process. If setup adds files after the original baseline, preflight the original valid task then refresh to the observed current identity; retain the original baseline identity and run the current witness after Plan.

For test-only/additive work, keep genuine behavioral criteria. Declare native coverage and a distinct retained test/fixture spec before freezing. If fixtures change, rerun original-product controls and current witnesses under the identical new overlay; preserve the original product definition and failed/interrupted attempts. See the [bootstrap/new-behavior recipe](../examples/evidence-bootstrap/README.md) and [workflow safeguards](development-workflow.md#bootstrap-and-additive-flights).

The gate pointer names a `check-*` directory. Its receipt binds actual output, input fingerprints and logical artifact digests; never glob a historical report. Spec manifests bind the tests/runner/required fixtures, while the gate fingerprint separately binds the product and runtime. Exclude vendored `.flightcheck/` and copied upstream resources from project linter/autofix paths. Check untracked source whitespace as well as `git diff --check`; formatting only tracked diffs misses new files. Run mutating hooks before the final candidate freeze and renew evidence/review after any correction.

Use your own repository's contribution/delivery policy. FlightCheck's [contribution policy](https://github.com/spring-labs-inc/FlightCheck/blob/main/CONTRIBUTING.md) and [licensing guidance](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/licensing.md) remain unchanged. Completing this helper flight neither opens outside code intake nor grants additional licensing rights.
