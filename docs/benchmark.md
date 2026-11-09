# SpringDev benchmark

The benchmark answers two questions. Can SpringDev run and retain evidence from different project-native toolchains? How do two independent Codex attempts on the same task compare when one uses the selected SpringDev workflow?

## Targets

Use the [source pins](benchmark-pins.json) to restore independent copies of Django, ripgrep, fmt, and jsoup. Keep the same source commit and toolchain within a pair. Record the source archive digest, dependency identities, compiler or interpreter versions, host architecture, and declared test identities before an attempt. Warm dependency caches from equivalent verified seeds and give each attempt its own build directory, temporary files, and evidence store.

Restore Django and ripgrep from their verified Git bundles. Restore fmt and jsoup from an isolated source store at the exact commit and verify the archived source contents. The tar archives provide content verification. Retain the Git source identity separately. Restore each worker checkout from the baseline source independently.

Keep the source archives, private evaluator, reference implementation, native outputs, and review records in approved private storage outside the worker checkouts and tracked source. Workers receive a symptom-only task brief, allowed edit scope, required native checks, and the published evaluation criteria. The controller keeps the evaluator implementation and reference separate. A public historical task can still be familiar to a model. Record this limitation alongside the results.

## Preflight and calibration

Restore the exact pin to a clean checkout. Verify that the target can accept the example project instructions, skill, and reviewer definitions without replacing native project policy. Run the frozen native check scope and retain its original output and run packet. Record any compiler, dependency, sandbox, or harness failure separately from a candidate failure.

Run one private evaluator against both the baseline and a known-correct reference. The baseline must exhibit the scoped defect and the reference must satisfy the same evaluator. Record both outputs, any unchanged control cases, and the native suite's expected skips or failures. A passing native suite alone may leave the target defect uncovered.

### Initial calibration

Observed on macOS 27.2 arm64. Each clean pin accepted the SpringDev instruction, skill, and reviewer files without a path collision. Native checks passed again with those files present. Original output and run packets are retained in private calibration storage. The timed arms still need a launch-profile check for actual skill and reviewer discovery.

| Target | Native scope and tools | Evaluator result |
| --- | --- | --- |
| Django | Python 3.12.7, SQLite 3.54.0 and an offline hash-checked wheelhouse. Seven ORM modules ran 1,060 baseline tests and 1,064 reference tests, with 27 skips and three expected failures on each. | Baseline rejected with six errors across 18 cases. Reference passed all 18. |
| ripgrep | Rust/Cargo 1.99.1 with vendored dependencies. Formatting, 78 searcher tests including the doctest, and 320 PCRE2 CLI integration tests passed on each candidate. | The baseline failed the continuing-stdin probe. The reference passed. |
| fmt | Apple Clang 21.0.0 and CMake/CTest 3.31.6. Argument, formatting, and standard-library test groups passed on each candidate. | A wrapped value whose formatting conversion yields text failed compilation on the baseline. The reference compiled and produced the expected output, including the numeric control. |
| jsoup | Temurin 21.0.9+10, Maven 3.9.11, and separate copies of the seeded Maven cache. Element and selector suites passed offline, with 368 baseline and 369 reference tests. | The baseline failed the replaced-child consistency assertion. The reference passed with the unaffected sibling preserved. |

The restricted runner initially blocked ripgrep's system `uncompress` access to `/dev/stdout`. The full scope passed with that access available. Both timed arms need the same approved route for this check. The Java cache seed succeeded after a retry. Subsequent Maven checks used offline mode. These observations establish local compatibility for the named scopes. Other hosts, full upstream suites, and live Codex reviewer invocation remain separate checks.

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
| SpringDev selected | Run the task with the SpringDev repository-local configuration and explicitly select the workflow. Count its checks, reviews, repair and waits as part of the condition. |
| Ordinary Codex | Give Codex the same task and acceptance information with ordinary project instructions. Verify that no SpringDev workflow instructions or skill are effective in this checkout. |

Keep the base, task, acceptance bar, model, effort, permissions, native tools, and cache starting state equivalent. Start fresh independent sessions and prevent cross-arm evidence access. Give both candidates the same external evaluator and independent review standard. Freeze the assistance policy and apply it equally. Use independent private run packets and verify digests against original tool output. Project-native checks can use an equivalent recorder where available.

The shared endpoint is a named candidate that passes the frozen native checks and external evaluator and meets the common independent review standard. End locally before publishing a branch or opening a PR. Verify that the actual result covers every required baseline test identity and any added acceptance tests. Report excluded or unavailable coverage and any material edit to an existing assertion.

## Record results

Measure elapsed time from task start to the shared endpoint. Keep setup separate and record review, repair, reruns, and waiting intervals. Record active time and native usage when observable, with the sources and missing intervals. Keep controller and reviewer usage separate. Report each arm's endpoint status and actual candidate, check and review outcomes, and deviations. Include blocked, interrupted, and incomplete arms with their reasons. Compare elapsed time only for arms that reached the common endpoint.

One pair is a case study. Use repeated pairs with alternating order and equivalent cache preparation before drawing a general performance conclusion. See the [paired pilot plan](benchmark-pilot.md).
