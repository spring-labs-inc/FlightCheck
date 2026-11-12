# FlightCheck benchmark

The benchmark answers two questions. Can FlightCheck run and retain evidence from different project-native toolchains? How do two independent Codex attempts on the same task compare when one uses the selected FlightCheck workflow?

## Latest benchmark results

## Historical benchmark results

[Historical benchmark results](benchmark-history.md)

## Targets

Use the [source pins](benchmark-pins.json) to restore independent copies of Django, ripgrep, fmt, and jsoup. Keep the same source commit and toolchain within a pair. Record the source archive digest, dependency identities, compiler or interpreter versions, host architecture, and declared test identities before an attempt. Warm dependency caches from equivalent verified seeds and give each attempt its own build directory, temporary files, and evidence store.

Restore Django and ripgrep from their verified Git bundles. Restore fmt and jsoup from an isolated source store at the exact commit and verify the archived source contents. The tar archives provide content verification. Retain the Git source identity separately. Restore each worker checkout from the baseline source independently.

Keep the source archives, private evaluator, reference implementation, native outputs, and review records in approved private storage outside the worker checkouts and tracked source. Workers receive a symptom-only task brief, allowed edit scope, required native checks, and the published evaluation criteria. The controller keeps the evaluator implementation and reference separate. A public historical task can still be familiar to a model. Record this limitation alongside the results.

## Preflight and calibration

Restore the exact pin to a clean checkout. Verify that the target can accept the example project instructions, skill, and reviewer definitions without replacing native project policy. Run the frozen native check scope and retain its original output and run packet. Record any compiler, dependency, sandbox, or harness failure separately from a candidate failure.

Run one private evaluator against both the baseline and a known-correct reference. The baseline must exhibit the scoped defect and the reference must satisfy the same evaluator. Record both outputs, any unchanged control cases, and the native suite's expected skips or failures. A passing native suite alone may leave the target defect uncovered.

The native preflight commands below assume the pinned tools are available, the target checkout is the working directory, and each run has its own temporary and build directories. Set `fmt_build` and `maven_cache` to the per-run build directory and seeded Maven cache. Use the pinned Python environment and run the Django command with the checkout root on `PYTHONPATH`. For ripgrep, set the per-run Cargo home and target directory, configure its verified vendor source, and place `TMPDIR` outside the Git tree.

```sh
python -B tests/runtests.py --settings=test_sqlite --parallel=1 --verbosity=2 --noinput \
  composite_pk foreign_object lookup queries expressions custom_lookups many_to_one

cargo fmt --all --check
cargo test --frozen -p grep-searcher
cargo test --frozen --features pcre2 --test integration

cmake -S . -B "$fmt_build" -DFMT_TEST=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=clang++
cmake --build "$fmt_build" --parallel 3 --target args-test format-test std-test
ctest --test-dir "$fmt_build" -R '^(args|format|std)-test$' --output-on-failure

mvn -o -B -ntp "-Dmaven.repo.local=$maven_cache" -Dtest=ElementTest,SelectorTest test
```

## Paired comparison

Freeze one common task brief, two condition briefs, a common external reviewer brief, and a result record before launch. Use the [record templates](benchmark-records.md) to identify the exact source, target checks and coverage, evaluator digest, effective Codex model and effort, tools and permissions, configuration identity, cache state, assistance policy, execution order, and local endpoint. Capture actual values during the run and retain any deviation from the plan.

| Condition | Workflow |
| --- | --- |
| FlightCheck selected | Run the task with the FlightCheck repository-local configuration and explicitly select the workflow. Count its checks, reviews, repair and waits as part of the condition. |
| Ordinary Codex | Give Codex the same task and acceptance information with ordinary project instructions. Verify that no FlightCheck workflow instructions or skill are effective in this checkout. |

Keep the base, task, acceptance bar, model, effort, permissions, native tools, and cache starting state equivalent. Start fresh independent sessions and prevent cross-arm evidence access. Give both candidates the same external evaluator and independent review standard. Freeze the assistance policy and apply it equally. Use independent private run packets and verify digests against original tool output. Project-native checks can use an equivalent recorder where available.

The shared endpoint is a named candidate that passes the frozen native checks and external evaluator and meets the common independent review standard. End locally before publishing a branch or opening a PR. Verify that the actual result covers every required baseline test identity and any added acceptance tests. Report excluded or unavailable coverage and any material edit to an existing assertion.

## Record results

Measure elapsed time from task start to the shared endpoint. Keep setup separate and record review, repair, reruns, and waiting intervals. Record active time and native usage when observable, with the sources and missing intervals. Keep controller and reviewer usage separate. Report each arm's endpoint status and actual candidate, check and review outcomes, and deviations. Include blocked, interrupted, and incomplete arms with their reasons. Compare elapsed time only for arms that reached the common endpoint.

One pair is a case study. Use repeated pairs with alternating order and equivalent cache preparation before drawing a general performance conclusion. See the [paired pilot plan](benchmark-pilot.md).

## Rehearse a handoff with synthetic data

Run the handoff integration tests from the FlightCheck checkout on a POSIX host with Python 3.

```sh
python3 -B -m unittest discover -s tests -p 'test_handoff.py'
```

The tests create temporary checkouts and private evidence directories. They exercise fresh receipts, reuse, blocked review packets, and frozen coverage baselines using the standard library. For your own project, follow the [task JSON and evidence setup](../examples/existing-project/docs/development-workflow.md#resume-summary-and-final-packet).

## Versioned qualification after escaped defects

The original twelve authoritative attempts, timings, first verdicts, private evaluator, and endpoint decisions are immutable. Post-hoc defects belong in a separately versioned qualification record; they do not retroactively turn a measured APPROVE into a rejection or restart an incomplete attempt. No new measured cohort is implied by maintenance work.

The public [known-case suite](../benchmarks/regressions.py) covers the escaped Django projection/caller-isolation cases and ripgrep binary-file behavior, plus streaming, BOM/buffer-boundary, regular-stdin, and positive compatibility controls. These tests qualify future references and belong in future visible acceptance gates before approval. They are deliberately separate from FlightCheck's project-independent handoff helpers. A private evaluator must still assess the frozen candidate after the workflow's first final verdict, without feeding repairs, and retain unseen cases to limit benchmark overfitting.

```sh
# Use the pinned interpreter and an exact restored source checkout.
python -B benchmarks/regressions.py django --source "$django_checkout" --output "$qualification_reports"
python -B benchmarks/regressions.py ripgrep --binary "$built_rg" --output "$qualification_reports"
```

For a recorded gate, point `--output` at `FLIGHTCHECK_REPORT_DIR` and retain `coverage.json` and `result.json` with `--isolated-reports`. Do not reuse checkout XML, a historical glob, or an earlier candidate's report. The controller owns qualification; workers cannot change its frozen suite, expected outcomes, baseline identities, or private references. Include suite, fixture, native producer, toolchain, environment and product identity in fingerprints. Never use a required fixture's absence as a skip or an empty passing report.

Before launching another cohort, restore clean exact pins and version the task, checks, evaluator and references together. Test the baseline, old reference, corrected reference, and known escaped candidates against the same new suite. The baseline must reproduce the target symptom while unchanged controls pass. An old reference failing expanded cases is a calibration gap to correct, not an acceptable new reference. Verify corrected references against both the original private evaluator and the full frozen native scope with every baseline identity/outcome preserved. Retain reference patches and new files privately alongside original native outputs and before/after identities. Distinguish pre-existing baseline defects from newly introduced regressions. Publish a qualification summary with hashes and evidence references, without exposing the private evaluator or reference implementation.

The [version 2 qualification record](../benchmarks/qualification-v2.md) records this maintenance pass. It is not a rerun of the twelve attempts or a paired performance comparison. Before any future trial, also probe the actual worker and reviewer boundaries, readable original evidence, isolated report production, check ownership and final handoff. Read-only reviewers request counterexamples; the controller executes them and retains before-failure/after-pass proof for confirmed repairs. Harness failures are recorded separately from product defects and must not be described as an APPROVE or silently repaired inside measured source.

For qualification reuse, the fingerprint must read the external inputs, not just an inventory filename or its declared hashes. The optional [benchmark fingerprint helper](../benchmarks/fingerprint.py) reads a controller-owned manifest with explicit `files` and `trees` lists. Each tree has `path` and optional generated component names in `exclude`. Include restored product source/tests, built binaries, native baselines, helper/evaluator code, original records and retained evidence. Include runtime/dependency identities in the surrounding project probe. File links bind both link identity and target content; missing inputs or linked directories fail closed. A changed, added or removed input invalidates reuse. Keep the manifest and helper protected from the worker; validate expected archive digests again in the fresh qualification command.

```sh
python -B benchmarks/fingerprint.py /private/controller/qualification-inputs.json
```
