# fmt and ripgrep benchmark results

Both pairs used the pinned sources and the SpringDev workflow at `7b5c8a0`. Each arm used an isolated local checkout, GPT-6.1 Sol requested at high effort, and Codex CLI 0.167.0. The controller ran the same fast and authoritative checks for both arms within each pair. It launched conditional early CODE review only for SpringDev and a separate read-only final reviewer for each arm. Timings include implementation, checks, repair and review through independent local `APPROVE`. Source and toolchain preflight preceded the timed runs. [Source pins](benchmark-pins.json)

## fmt wrapped-value formatting

Ordinary Codex went first. Both arms used Apple Clang 21.0.0 and CMake/CTest 3.31.6, with separate controller builds. The baseline failed the focused C++17 compile probe and the linked behavior evaluator. The reference passed both and preserved all 160 existing test identities across `args-test`, `format-test`, and `std-test`.

| Measure | Ordinary Codex | SpringDev |
| --- | ---: | ---: |
| Wall time to independent `APPROVE` | 168.28 s | 218.16 s |
| Implementation | 110.25 s | 161.30 s |
| Focused compile gate | 0.53 s | 0.42 s |
| CMake build and CTest | 9.07 s | 8.95 s |
| Linked evaluator | 0.55 s | 0.51 s |
| Independent final review | 47.60 s | 46.46 s |
| Early CODE reviews | 0 | 0 |
| Final review cycles | 1 | 1 |
| Controller repair cycles | 0 | 0 |
| Controller gate reruns | 0 | 0 |
| Native test identities passing | 162 | 162 |

Both workers reproduced the pinned compile failure during implementation. A second focused compile caught an ambiguous formatter specialization in each worker's intermediate fix, and each resolved it before handoff. Every controller gate passed on the first submitted candidate. SpringDev skipped early CODE review because the change was bounded and had focused compile coverage. Both independent final reviewers found no unresolved findings. The difference in elapsed time came chiefly from implementation. No submitted fmt candidate failed the fast gate, so this pair observed no avoided broad build.

## Ripgrep line buffering

SpringDev went first. Both arms used Rust and Cargo 1.99.1, an identical verified offline vendor seed, separate empty build targets, and the same local decompressor shim used in the earlier pilot. Formatting and the searcher suite ran first. The controller then ran the PCRE2 CLI integration suite and the held-out continuing-stdin evaluator. The baseline passed all 398 native tests and failed the evaluator. The reference passed the native scope and all five rounds in each of the plain, inverted, and fixed-string evaluator cases.

| Measure | Ordinary Codex | SpringDev |
| --- | ---: | ---: |
| Wall time to independent `APPROVE` | 293.56 s | 357.09 s |
| Implementation | 227.80 s | 270.12 s |
| Formatting | 0.38 s | 0.38 s |
| Searcher tests and doctest | 1.22 s | 1.20 s |
| PCRE2 CLI integration tests | 2.32 s | 2.28 s |
| Held-out pipe evaluator | 0.26 s | 0.26 s |
| Independent final review | 61.23 s | 82.13 s |
| Early CODE reviews | 0 | 0 |
| Final review cycles | 1 | 1 |
| Controller repair cycles | 0 | 0 |
| Controller gate reruns | 0 | 0 |
| Native test identities passing | 399 | 399 |

Both workers reproduced the open-pipe stall with their own new test. Their initial fixes passed the new regression but broke `searcher::glue::tests::binary3` and `binary4`. Both workers caught and fixed those failures during implementation before handing off a candidate. SpringDev skipped early CODE review after the focused checks passed. Both final reviewers approved the first submitted candidate, which preserved all 78 searcher and 320 CLI baseline identities and added one CLI regression.

The earlier SpringDev-first pilot recorded 671.48 seconds to `APPROVE`, with a return from the authoritative gates for the two binary failures and renewed CODE review. This run took 357.09 seconds and resolved those failures inside implementation. The workflow, worker sessions and candidate patches differed across runs. These timings describe individual pairs. [Earlier ripgrep pilot](benchmark-pilot-result.md#springdev-first-rerun)

## Evidence retained

The private archive `native-pairs.buVrzs` contains each frozen manifest, exact workflow snapshot, candidate diff, raw worker failure logs, original native and evaluator evidence, receipts, reviewer transcripts and audited phase timings. The audit checked candidate and output digests, baseline coverage, and independent final-review session identities. The benchmark checkouts and results stayed local.

## One-owner handoff rerun

This rerun preserved the source pins, test identities, private probes, and independent final review. SpringDev assigned native gates to the worker and used a trusted request service to record them in a controller-owned evidence bank. The handoff carried verified receipts for the current candidate. The controller owned the private checks and any fallback. Ordinary Codex used the same check scope and its previous implementation brief. Times include any worker-requested checks. They are counted once in the implementation session.

### fmt

| Measure | Ordinary Codex | SpringDev |
| --- | ---: | ---: |
| Wall time to independent `APPROVE` | 232.15 s | 173.63 s |
| Implementation session | 178.82 s | 125.04 s |
| Independent final review | 43.12 s | 47.31 s |
| Early CODE reviews | 0 | 0 |
| Final review cycles | 1 | 1 |
| Controller repair cycles | 0 | 0 |
| Governing gate reruns | 0 | 0 |
| Native test identities passing | 162 | 162 |

SpringDev's worker requested the canonical CMake and CTest gate once. The request service first ran the controller-owned private compile probe, then recorded the native gate as worker-owned. The controller carried both original receipts and ran the linked evaluator once. The worker used focused compile probes during implementation, and the handoff avoided a second broad build and test run.

An initial SpringDev launch received the reviewer brief due to a benchmark harness error. It made no edits and ran no gates. Its 51.10 seconds and transcript are retained separately. The measured arm restarted with a fresh session from the unchanged pin.

### Ripgrep

| Measure | Ordinary Codex | SpringDev |
| --- | ---: | ---: |
| Wall time to independent `APPROVE` | 370.89 s | 284.60 s |
| Implementation session | 289.87 s | 222.40 s |
| Independent final review | 76.06 s | 60.62 s |
| Early CODE reviews | 0 | 0 |
| Final review cycles | 1 | 1 |
| Controller repair cycles | 0 | 0 |
| Governing gate reruns after a candidate change | 0 | 2 |
| Native test identities passing | 400 | 399 |

Both workers reproduced the continuing-stdin failure. SpringDev's worker-owned searcher gate caught the existing `binary3` and `binary4` tests failing on the first fix. The worker repaired the patch and reran formatting and the searcher gate on the changed candidate. It then ran the CLI suite once. The handoff carried all three passing receipts, and the controller ran the private pipe evaluator once. Ordinary Codex caught the same binary failures during local verification and repaired them before its controller ran the governing checks. Both final reviewers approved their first submitted candidates.

The rerun directly verified that the final SpringDev candidate's carried gates executed once each. Wall times also include different patches and independent worker and reviewer sessions. These individual pairs do not isolate the effect of receipt carry on elapsed time.

The private archive `owner-pairs.J83LQO` preserves both manifests, the workflow patch, worker requests, original receipts and failure outputs, review transcripts, and audited timings. The benchmark worktrees and results stayed local.
