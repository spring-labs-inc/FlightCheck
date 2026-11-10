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
