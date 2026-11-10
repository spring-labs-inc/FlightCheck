# Ripgrep paired pilot result

November 9, 2026. The approved [pilot](benchmark-pilot.md) ran against the [ripgrep 15.0.0 pin](benchmark-pins.json) on macOS arm64. Both arms reached the common local endpoint and received an independent `APPROVE` verdict. [FlightCheck #13](https://github.com/spring-labs-inc/FlightCheck/issues/13)

## First pair

The ordinary arm ran first and the selected workflow arm ran second. Both used the same symptom-only brief, GPT-6.1 Sol at high effort, the same native commands, and equivalent permission profiles. Runtime records confirmed the model and effort in both implementer sessions and their continued turns. Each arm started with an empty build target, an isolated Cargo home, and the same locked vendor seed and Rust 1.99.1 toolchain.

Preflight verified all 398 baseline test identities in each profile, denied reads of the other arm and private evaluator, and denied writes from reviewer profiles. The selected workflow session discovered its workflow skill and role files. The ordinary session had neither. Both profiles used the same local gzip-backed `uncompress` shim for the restricted macOS system decompressor test. All native tests remained in scope.

### Endpoint and timing

| Measure | Ordinary Codex | Selected workflow |
| --- | ---: | ---: |
| Wall time to common endpoint | 298.49 s | 919.20 s |
| Implementer sessions | 244.22 s | 585.26 s |
| Internal review sessions | 0.00 s | 218.71 s |
| Common external review | 49.58 s | 46.64 s |
| Controller checks | 4.48 s | 3.95 s |
| Controller transitions and unattributed time | 0.22 s | 64.63 s |
| Baseline tests passing | 398 | 398 |
| Added regressions passing | 2 | 2 |
| Private pipe evaluator | PASS | PASS |
| Common external review | APPROVE | APPROVE |

Setup and discovery preceded the timed runs. Implementer and reviewer session durations are wall time and include their tool work and provider waits. The transition bucket is the residual after measured phases. The ordinary candidate digest is `ea327cdb062129ac0a4f1b562dbadcbc8844166a46974033199dfeced07797da`. The selected workflow candidate digest is `e297f7179e9f171462621c085a2f1c88fc644f9fe83b5e542c1064f1a508f930`.

| Native token counters | Ordinary Codex | Selected workflow |
| --- | ---: | ---: |
| Implementer input, including cached | 716,052 | 2,523,364 |
| Implementer cached input | 660,224 | 2,403,712 |
| Implementer output | 9,399 | 22,732 |
| Internal reviews input / output | 0 / 0 | 591,401 / 8,239 |
| Common external review input / output | 188,869 / 1,825 | 125,673 / 1,836 |

Implementer counters are native cumulative totals from each fresh session through its final turn. Review counters are from the separate read-only sessions. They report observable usage.

### Returns and interpretation

Both implementers encountered the same two binary-handling searcher failures and repaired them independently. Ordinary Codex repaired them within its implementation turn. The selected workflow arm returned from the authoritative gate to repair, obtained fresh CODE review, and reran the affected checks. Its final EVIDENCE review approved the repaired candidate.

The first CODE reviewer for the selected workflow reported zero code findings and returned `REVISE` because the controller exposed an empty formatting log without its successful exit receipt. A controller evidence-directory collision interrupted the handoff after the implementer supplied a receipt. The controller resumed the original session, kept the interrupted record, and provided candidate-bound check receipts to subsequent reviewers. The observed wall time for the selected workflow includes these incidents and recovery.

This first pair documents the costs and outcomes observed under its fixed order. A performance comparison across repetitions needs a corrected evidence handoff, alternating order, and equivalent fresh caches. The independent external reviewers used the same brief and bar, with condition visibility possible from their checkout paths.

The frozen manifest digest is `29db21e7e182d120c2b76797879dd1126dec897f8c0d2d73ce5be5bf64a44b24`. The private experiment record retains the endpoint patches, original logs, coverage, reviews, evaluator results, and native counters.

## Rerun with the selected workflow first

The rerun used the same source pin, task and review briefs, native check scope, evaluator, GPT-6.1 Sol at high effort, and equivalent permission profiles. Fresh checkouts each started with an empty build target and an isolated Cargo home initialized from the same offline vendor seed. Preflight ran outside the measured caches and passed all 398 baseline test identities in each profile. The selected workflow arm completed before Ordinary Codex started.

The controller now gives reviewers the original formatter log and a receipt containing its candidate digest and successful exit status. It allocates a unique directory for each handoff under a controller namespace separate from worker evidence. A regression check exercised an empty log, two handoffs under the same label, a preexisting worker path, and a stale candidate. Both live CODE reviews verified the formatter receipts and approved their candidates.

| Measure | Selected workflow | Ordinary Codex |
| --- | ---: | ---: |
| Wall time to common endpoint | 671.48 s | 232.46 s |
| Implementer sessions | 465.17 s | 176.06 s |
| Internal review sessions | 146.61 s | 0.00 s |
| Common external review | 55.42 s | 52.85 s |
| Controller checks | 3.75 s | 3.31 s |
| Controller transitions and unattributed time | 0.54 s | 0.25 s |
| Baseline tests passing | 398 | 398 |
| Added regressions passing | 2 | 1 |
| Private pipe evaluator | PASS | PASS |
| Common external review | APPROVE | APPROVE |

Both arms repaired the same two binary-detection failures while preserving the existing assertions. The selected workflow arm returned from the authoritative gates to repair, obtained fresh CODE approval, reran the gates, and received EVIDENCE approval. It added a short-read boundary unit test alongside the open-stdin regression. Ordinary Codex repaired the failures in its implementation session and added the open-stdin regression. The selected workflow arm took 439.01 s longer in this rerun, including 146.61 s of internal review. The arms produced different repairs, and the first pair includes controller recovery. These two pairs document observed timings for this task.

| Native token counters | Selected workflow | Ordinary Codex |
| --- | ---: | ---: |
| Implementer input, including cached | 1,695,078 | 804,944 |
| Implementer cached input | 1,613,696 | 755,200 |
| Implementer output | 18,943 | 6,414 |
| Internal reviews input / output | 399,448 / 5,280 | 0 / 0 |
| Common external review input / output | 132,043 / 2,236 | 165,980 / 1,897 |

Cold caches refer to the local build environment. Provider-cached input is reported separately in the native counters. The selected workflow candidate digest is `522af553199004b367157303658e40b6c2ddba0d6430d4fce06fb976cb7263cb`. The Ordinary Codex candidate digest is `d2a0c1b389ca59c2b56d8886c5373c8069d31567fdf8a531715ba2939f1cd216`. The frozen manifest digest is `439579b675f7260e117ba245eaf54c64bc89a28151ae6b73ced03131a913125c`. The verified receipts and raw results are retained in the private experiment record.
