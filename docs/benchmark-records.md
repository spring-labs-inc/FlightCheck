# Benchmark record templates

Copy these fields into the private experiment records. Replace the descriptions with actual values. Freeze the planned manifest and briefs before launch. Keep observations and deviations in the results. Record unavailable observations explicitly.

## Manifest

| Field | Planned value |
| --- | --- |
| Identity | Experiment ID, protocol revision, target pin, archive and dependency digests |
| Briefs | Common task, two condition briefs and reviewer brief, with a digest for each |
| Evaluation | Endpoint, required checks and native test identities, applicability and reuse rule, external evaluator identity and digest |
| Arms | Condition, requested model and effort, tools, permission profile, isolation, configuration identity and initial cache state |
| Controller | Host and toolchain versions, execution order, assistance policy, resource limits and delivery scope |
| Evidence | Approved private record location and per-arm evidence layout |

## Common task brief

- Describe the symptom and expected externally observable behavior.
- Define the allowed edit scope and test additions. Name the exact native checks and required coverage.
- Tell both arms that the controller applies the same private evaluator and independent review. State what result counts as completion.

## Condition brief

- Identify the assigned checkout, condition and scope. State which project instructions and tools apply.
- Specify the permitted native checks, cache and evidence paths, and any known platform restriction.
- State the assistance and delivery boundary. Keep the other arm's implementation and evidence out of the session.

## External reviewer brief

- Inspect the named endpoint candidate, the common task brief, and the relevant original check evidence. Apply the same acceptance criteria in each review.
- Report actual coverage, evidence gaps and findings with severity and references. A complete clear review records zero findings.
- Record reviewer identity, effective model and effort when observable, and any information that could reveal the condition.

## Controller evidence handoff

Allocate a unique directory for each handoff in a controller namespace separate from worker-created evidence. Verify the candidate is unchanged from the start of the check before handing off its packet. Include the original output and a receipt even when a successful tool emits zero bytes. The receipt binds the output digest, command, exit status, working directory, timestamps, toolchain and effective cache configuration to the candidate digest. Give the reviewer both paths and include the native test identity comparison when applicable.

## Result

| Field | Observed value |
| --- | --- |
| Identity | Experiment and arm IDs, actual source and candidate, effective model and effort, session and review IDs |
| Check evidence | Exact commands, outcomes, coverage, output and report identities and digests, repairs and reruns |
| Endpoint | Completed, blocked, interrupted or incomplete, with endpoint candidate and timestamp or reason |
| Time and usage | Setup and arm windows, wait intervals, elapsed and observable active time, native counter deltas and gaps |
| Deviations | Differences from the manifest, controller assistance, environment changes and attribution limits |

## Evidence-inspection supplement

For the separate [evidence-inspection protocol](evidence-inspection.md), freeze these additional planned fields and retain actual values/deviations privately. Publish only the sanitized reusable schema; exclude private paths, native logs, reviewer prose and oracle contents.

| Field | Required record |
| --- | --- |
| Track/provenance | Schema revision, harness/suite digests, opaque case/view IDs, original seal/source-manifest/oracle/dependency digests; separately bound derived adjudication crosswalk and status, synthetic versus preserved-private origin |
| Workflow identity | Actual baseline/incremental Git pins, native helper/policy digests, retained original commands/output/exit codes, explicit fixture adaptations |
| Subject identity | Separate product source pin, candidate/diff digest, unchanged source/evidence/claim identities within each matched pair |
| Decision schedule | Trajectory/step/stage/session IDs; CODE then separate independent final; all planned steps/repetitions and session totals |
| Matched settings | Provider, requested/effective model/effort, client, tools/access, cache, prompts, assistance, order and exposure limitations |
| Isolation/access | Actual session boundary/write-denial and required-evidence probes before decision, accessible originals, necessary missing evidence versus covered duplicate, bypass/telemetry gaps |
| Quality | Frozen specific-discrepancy/repair rubric, genuine detections, actionable repairs, generic blocks, misses, false alarms, critical false approvals, uncertain findings, semantic-audit status, provisional quality precheck and actual adjudication status |
| Per-decision cost | Active model/session time and summed totals; elapsed/critical-path intervals; tools/reads/repeated bytes; native tokens/cache/quota with sources and unknowns |
| Full experiment cost | Setup, supervision, waits, native checks, prescribed repairs/reruns, totals, overlaps and accounting completeness |
| Limits/outcome | Frozen time/session/tool/token/quota caps and enforcement, consumed budgets, stopped/interrupted/diagnostic/incomplete attempts and reasons; no hidden replacement attempts |
| Interpretation | Machinery-only smoke versus actual model observation; single-case/cohort limits; no efficiency acceptance after a critical false approval or incomplete required measurement |

Keep public calibration separate from the frozen private measured cohort. Preserve every governing attempt and the original verdict before feedback. Ordinary regression results do not establish model detection performance, and review-time savings alone do not establish whole-flight savings.

Unresolved public proposal bindings remain `null`; do not insert invented hashes. Freeze actual private identities and exact owner approval separately before launch. Historical scoring consumes a derived private crosswalk while the original independent key stays unchanged. Extraction/semantic audit uses the bounded supervision allowance, with no extra model or full review per trial.
