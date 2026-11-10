# Django composite-key lookup benchmark result

The November 9, 2026 pair used the [Django source pin](benchmark-pins.json) at `f8fce8d4dce7cf6d272a29351faddd5fa76f1aa0` and SpringDev revision `658d3cd`. Both arms started in isolated checkouts at the same pin with Codex CLI 0.167.0, GPT-6.1 Sol requested at high effort, Python 3.12.7 and SQLite 3.54.0. The task was to support implicit and explicit QuerySet projections in composite-key `IN` and exact lookups while preserving scalar, tuple and correlated behavior.

| Observation | Ordinary Codex | SpringDev |
| --- | ---: | ---: |
| Fresh task to independent `APPROVE` | 418.97 s | 1,330.61 s |
| Clean resume to independent `APPROVE` | 166.68 s | 161.68 s |
| Native Django tests run | 1,072 | 1,073 |
| Held-out evaluator checks passed | 18/18 | 18/18 |
| Native result on clean resume | Reused after manual assessment | Reused through receipt matching |

Both patches passed the [same seven-module native scope](benchmark.md#preflight-and-calibration), including all 1,060 baseline test identities. Both runs retained 27 skips and three expected failures. Ordinary Codex went first on the fresh task, and SpringDev went first on clean resume. Each arm resumed its own approved patch. The endpoint was scoped local approval. This single pair covers SQLite and measures no human approval wait or delivery time.

## Defect missed by ordinary Codex

SpringDev's second early CODE review returned `REVISE` because wrapping a multi-column `QuerySet` in an `ExpressionWrapper` bypassed validation when used as the right-hand side of a scalar lookup. The implementer restored early validation and added regression tests. The repaired candidate cleared early review, passed the planned checks, and received an independent final `APPROVE`.

The wrapped scalar case was outside the planned evaluator. After ordinary Codex reached `APPROVE`, the controller tested its approved patch separately. It accepted the invalid lookup during query construction and then raised SQLite's `OperationalError: row value misused` during execution. The pinned baseline and SpringDev's approved patch both rejected the lookup with `TypeError` during construction. The ordinary patch had the same digest at fresh and clean-resume approval, and the defect was still present at both endpoints. The controller repeated the probe on both endpoint patches after the timed runs. Ordinary Codex made no repair for this defect during the benchmark.

SpringDev's first early review also found a separate duplicate-projection column count defect in its initial patch. SpringDev repaired it, and both final patches passed the supplemental duplicate-projection checks.

## Where the time went

SpringDev spent 378.35 seconds in three early CODE reviews and 389.70 seconds in two repairs. The independent final review took 93.94 seconds. The native test runner itself took under one second per arm. On clean resume, SpringDev spent about one second combined on the shared summary, receipt matching and final packet. The resumed worker and final review accounted for almost all of the clean-resume time.

## Evidence retained

The private benchmark record `django-pair.LxAI9x` contains the run manifest, verified timings, original native and evaluator outputs, candidate diffs, receipts, review transcripts and the supplemental probes. The controller verified these endpoint diff digests against the recorded verdicts and verified the same patches for the supplemental probes.

| Candidate | Scoped diff SHA-256 |
| --- | --- |
| Ordinary Codex | `4dabe16477eb5db34b1d2365f5aba7e2bfad048b874a4bde4cfd1e8db0e041ae` |
| SpringDev | `4a3e0c46bfecd50db3f587da58f92fdade111f9fa7a2653e509d9140c6d4f91c` |

## Review routing rerun

The rerun used the same Django pin, toolchain, task, seven native modules, and original 18 held-out checks. It added the wrapped scalar probe as a required private check for both arms before final review. Both approved candidates covered all 1,060 baseline test identities and retained 27 skips and three expected failures. Each clean resume reused its own candidate's matching receipt.

| Observation | Ordinary Codex | SpringDev |
| --- | ---: | ---: |
| Fresh task to independent `APPROVE` | 615.34 s | 1,242.26 s |
| Clean resume to independent `APPROVE` | 138.93 s | 65.37 s |
| Native Django tests run on approved candidate | 1,078 | 1,075 |
| Original held-out checks passed | 18/18 | 18/18 |
| Wrapped scalar guard on approved candidate | Passed | Passed |

SpringDev's initial early review caught a separate regression in scalar relations targeting a non-PK field. After the repair, SpringDev resumed the same read-only reviewer with the repair diff and prior finding. That review took 52.85 seconds and cleared the relation repair, but missed the wrapped lookup. The required probe reproduced `OperationalError: row value misused` on that candidate and on ordinary Codex's first candidate. Both arms repaired the defect before independent final review. Both approved patches rejected the invalid lookup during construction with the pinned baseline's `TypeError`.

The clean SpringDev resume validated the saved state, recorded receipt reuse, and sent the final packet directly to a new independent reviewer. Summary, receipt matching, and packet generation took about one second combined. The previous SpringDev clean resume took 161.68 seconds and included a 61.78-second worker session. These runs used different approved patches and independent reviewer sessions. The added guard and different repairs also changed the fresh comparison.

Outside the timed pair, a replay used the original two pre-fix SpringDev patches, verified against their review digests. The resumed reviewer took 30.35 seconds and kept a related explicit `Exact` expression blocker open, but missed the wrapped lookup. The probe reproduced the wrapped failure on both pre-fix patches and passed on the original repaired patch. The required probe supplied the wrapped-case protection in the timed rerun.

The explicit sandbox denial for the earlier scratch directory was added after the ordinary fresh session launched. Its tool log showed no access to the earlier scratch directory or its answers.

The private record `django-routing.TwOQXp` retains the exact SpringDev workflow patch, manifests, native outputs, receipts, verified timings, reviewer sessions, probe outputs and replay candidates.

## Cheap checks before CODE review

This rerun used the same Django pin, scoped task, toolchain, native test modules, and private evaluator and wrapped-lookup probe as the review routing rerun. SpringDev recorded the native suite and wrapped probe in stage 03 and required current passes before stage 05. The original 18-case evaluator ran in stage 06. Ordinary Codex kept its previous check order. Both arms used separate independent final reviewers. The numbered workflow sequence follows the `adc9106` main pin.

| Observation | Ordinary Codex | SpringDev |
| --- | ---: | ---: |
| Fresh task to independent `APPROVE` | 593.98 s | 710.15 s |
| Clean resume to independent `APPROVE` | 142.08 s | 81.94 s |
| Native Django tests run on approved candidate | 1,078 | 1,076 |
| Original held-out checks passed | 18/18 | 18/18 |
| Wrapped scalar guard on approved candidate | Passed | Passed |
| Early CODE reviews launched | 0 | 1 |

Both approved patches covered all 1,060 baseline test identities, with 27 skips and three expected failures. The wrapped probe caught the regression in both arms. In SpringDev it blocked the first candidate at stage 03 even though the 1,074-test native run passed. No reviewer session started for that candidate. After repair, the candidate passed both checks, cleared one CODE review, passed the held-out evaluator, and received independent final approval. The clean SpringDev resume reused both stage 03 receipts and went directly to an independent final reviewer.

The previous SpringDev run took 1,242.26 seconds and launched three early reviews. This rerun took 710.15 seconds and launched one. Candidate implementations and repair work varied between runs, so the elapsed difference measures the full rerun. The blocked first candidate directly demonstrates the scheduling effect.

A separate scalar-relation probe ran after the timed endpoints on the exact approved patches. SpringDev returned the expected row when a scalar foreign key targeted a unique non-PK field on a composite-key model. The ordinary Codex patch rejected that valid lookup with `TypeError: Cannot use multi-field values as a filter value.` The probe was outside the timed acceptance scope, and ordinary Codex made no repair for this defect during the benchmark.

A controlled replay used the digest-verified initial SpringDev patch from the review routing rerun. Stage 03 blocked the original patch on the wrapped probe. After applying only the wrapped-lookup fix, both fast checks passed and the separate scalar-relation probe still failed. The independent CODE reviewer inspected that partial repair and returned `REVISE` for the scalar-relation defect. The fully repaired reference passed both probes. The replay was outside the paired timing.

The private record `django-cheap-first.vO2Cjs` retains the exact workflow patch, verified timings, candidate diffs, check and review records, and controlled and supplemental probe evidence.
