# Evidence-inspection benchmark, version 1

This track measures whether reviewers identify specific defects in code and retained evidence while making repeated repair/resume decisions. It complements the [source-repair benchmark](benchmark.md) and its [qualification suite](../benchmarks/qualification-v2.md). It changes no production review policy and rewrites no historical result. Ordinary regression tests and the provider-free smoke establish harness behavior, not model behavior.

## Identities and comparison boundary

The baseline is the actual FlightCheck source at `ee869f9a3c03c8c048ad778d7465d9c31e70f970`. The incremental condition is the merged #106 source at `c69bbfe364ac01c9a13b46cb983f0c4ffd2c5e33`. Preparation snapshots the pinned Git bytes and invokes their native helpers; condition labels alone do not establish a comparison. Retain original preflight, capture, CODE packet, final packet, verdict and resume outputs, commands, exit codes and helper/policy digests. Label fixture adaptations explicitly. Do not supply the incremental implementation to the baseline under an old label.

The Ripgrep subject source pin is independently `3a612f88b805e14aef45bfa43e25a54abc6297fc`. It is not a FlightCheck policy pin. Current main `952aaa74fafdcf2780e263d401235aa096e4c1ac` additionally changes recorder progress hooks and heartbeats; substituting it for the merged #106 pin changes the comparison and requires a newly frozen proposal.

Both conditions receive the same claims, candidate/source evidence, expected outcomes, provider/model/effort, tools, access, cache preparation, assistance and ordered decision stages. Run CODE and then one separate independent final reviewer for every prescribed decision in both conditions. The condition-specific native packet and effective pinned policy are the treatment. Match all other inputs, retain actual session boundaries and prohibit cross-condition access. There is no extra outer review cycle and no artificial session-count advantage.

## Public calibration and preserved private cases

The [versioned suite](../benchmarks/evidence-inspection-v1.json) uses the `evidence-inspection-v1` schema. Its public synthetic matrix is calibration material:

| ID | Calibration distinction |
| --- | --- |
| c01 | Clean accepted evidence |
| c02 | Navigation-only change with unchanged target bytes |
| c03 | Short-line/BOM semantic inadequacy |
| c04 | Redirected-stdin binary-filtering inadequacy |
| c05 | Parallel-stdin buffering inadequacy |
| c06 | Changed effective dependency |
| c07 | Contradictory evidence |
| c08 | Unresolved prior obligation |
| c09 | Missing necessary evidence |
| c10 | Covered inaccessible duplicate |
| c11 | Tampered evidence |
| c12 | Current-diff / decision-basis reopening control |

The c12 fixture uses an explicit synthetic “contains defect” marker to test current-diff binding and decision-basis reopening. It does not demonstrate executable new-code-defect discovery or model detection of such a defect.

The synthetic cases do not reconstruct or replace historical evidence. Import the already preserved private views for the three selected Ripgrep cases: short-line/BOM blocking, redirected-stdin binary filtering and parallel-stdin buffering. Retain their original seals, integrity manifests, independent oracle and dependency provenance. The private view identifiers are opaque; their mapping and contents stay in controller storage. Only the three preserved pre-repair historical views are established here; no historical repaired/control variant is constructed. A missing sealed view is unavailable evidence, not permission to recreate an archive or requalify a historical attempt.

The sole import format has `schema: evidence-inspection-v1`, `kind: historical-import`, and these fields:

| Field | Binding |
| --- | --- |
| `lineage` | `id`, independent Ripgrep `subject_pin`, and recorded `limitations` |
| `source_manifest` | Private `path` and `sha256`; its `files` map uses absolute paths and binds the selected seals |
| `oracle` | Private `path` and `sha256` of the unchanged original independent key |
| `views` | Entries with `id`, absolute private `root`, `seal` path/digest, and `files` entries containing `id`, relative `path`, `sha256`, `bytes`, `necessary` and `coverage` |
| `dependencies` | Private path/digest references, including the independently pinned parent manifest that binds the original oracle and any retained excerpt provenance |

Each seal maps relative artifact paths to digests. Verification reads the actual selected files, seals, manifests, dependencies and key, checking source/candidate/case identity. There is no older single-view import compatibility. Keep the specification and referenced private paths outside the public checkout. Hashes establish integrity relative to the frozen controller trust root; arbitrary caller-supplied hashes do not establish authenticity.

The original historical key is not canonical scorer input. Create a separate private, derived adjudication crosswalk with `schema: evidence-inspection-crosswalk-v1`, `kind: derived-private-adjudication`, `original_oracle_sha256`, `case_id`, `candidate`, canonical `oracle`, exact `source_references` entries (`artifact_id`, `location`), and `adjudication` (`status: provisional` or `independent-audit`, plus the retained actual `source`). The Python API `normalize_historical_oracle(import_spec, case_id, crosswalk_path)` checks those bindings against the sealed import. Each source reference names the exact sealed artifact path, optionally followed by a one-based `:line` or `:first-last` range within that selected file. Do not copy a combined finding location onto unrelated artifact IDs; retained excerpts with different original line coordinates use their selected path without an invented line mapping. It never modifies the historical key or automatically interprets arbitrary historical prose. Preserve the key, crosswalk, its status and source references separately.

Public fixtures and published rubric details can be familiar to a model. Calibration success is not unseen detection performance. A future measured cohort must freeze private views and exposure limitations separately; importing preserved views does not imply that a model has never seen their underlying task.

## Bounded commands

Run from the repository root with Python 3. Use a new owner-only output directory outside the checkout. The implementation provides no provider/session orchestrator.

```sh
python3 -B benchmarks/evidence_inspection.py prepare \
  --suite benchmarks/evidence-inspection-v1.json --case c01 \
  --runtime "$flightcheck_repository" --condition baseline \
  --output "$new_private_run"

python3 -B benchmarks/evidence_inspection.py prepare \
  --runtime "$flightcheck_repository" --condition incremental --case q7 \
  --import-spec "$private_import_spec" --output "$new_private_import_run"

python3 -B benchmarks/evidence_inspection.py read \
  --view "$view_manifest" --artifact "$artifact_id" --offset 0 --length 4096 \
  --role CODE --session "$session_id" --phase inspection --events "$private_events"

python3 -B benchmarks/evidence_inspection.py score \
  --run "$private_run_json" --reviews "$private_reviews_json" \
  --events "$private_events" --oracle "$private_scoring_oracle" \
  --output "$new_private_score"

python3 -B benchmarks/evidence_inspection.py smoke \
  --suite benchmarks/evidence-inspection-v1.json \
  --runtime "$flightcheck_repository" --output "$new_private_smoke"
```

`--suite` defaults to the bundled specification. Imported preparation requires both `--import-spec` and `--case` selecting one opaque view ID in that bundle; `q7` above is an example. For synthetic scoring, `--oracle` is the prepared canonical synthetic oracle. For historical scoring, it is the separately validated private crosswalk, never the raw historical key. The runtime repository must contain the exact pinned Git objects. Preparation records the selected helper and policy identities and retains their native output. The view includes actual `policy.txt` and `packet-code.json` / `packet-final.json` artifacts. Lifecycle fixtures preserve native helper states and explicitly label their scripted common history as synthetic rather than historical or real model acceptance; only navigation paths are adapted for the view. Smoke exercises deterministic scripted controls, native helper boundaries, view reads and scoring; it makes no model/provider calls and yields no actual review result. Its report explicitly marks `machinery_only: true`, `synthetic: true` and `measured_review_observations: false`.

`read` accepts only manifest-listed artifact IDs and bounded byte ranges. It records returned bytes and digest, role, session, phase and read interval. Use `--phase probe` for access probes; they are distinct from inspection. Repeated reads are allowed and recorded. Scoring requires each inspection/probe event to name a session and role in the retained attempt ledger and occur no later than the captured decision cutoff; inconsistent captures are rejected instead of silently attributing unrelated or later audit reads to that decision. Arbitrary accounting intervals are not treated as absolute session-start timestamps. A read-only reader command is not an operating-system sandbox: before any model decision, probe that session's actual read-only boundary and required-evidence access. Missing necessary evidence blocks the decision. An inaccessible duplicate does not automatically block a claim supported by accessible, correctly bound originals. Controller access cannot substitute for reviewer access.

## Privacy and reusable reports

Keep controller originals/oracles, reviewer views and controller-owned event/capture storage separate. Reviewer views expose only approved artifacts and the assigned condition's policy/packet. Reject unsafe paths, escaping aliases, symlinks and digest drift; deny access to the oracle, generator answer material, private originals not approved for the view, the other condition, secrets and provider writes. Existing shell/file tools must either participate in trustworthy read capture or make inspection-efficiency measurements incomplete. No command here establishes those external permissions by itself.

A reusable sanitized score contains schema/version and opaque case/condition IDs, bound input digests, outcome counts, quality flags, metric values and explicit unavailable observations. Its `case_id`, `condition`, `pin`, `view_sha256`, `run_sha256` and `manifest_sha256` identify the validated prepared run and effective identity groups without copying private manifest contents. It must exclude raw private paths, native logs, reviewer prose, answer keys and private artifact contents. Retain those originals privately for audit. Publishing sanitized summaries does not authorize publishing their supporting private records.

## Scoring quality before efficiency

Freeze the independent oracle before review. A specific detection identifies the affected claim, concrete discrepancy and supporting evidence; an actionable repair identifies a change or exact additional witness that addresses that discrepancy. A generic `BLOCK`, unrelated concern or passing assertion that also passes with the defect present receives no specific-detection or actionable-repair credit. Report `specific_detected`, `actionable_repairs` and `false_alarms` separately. Blanket blocking can avoid approval while missing the actual defect; record both facts.

Structured matching is a deterministic bookkeeping aid. It cannot establish that arbitrary prose is semantically correct or that a suggested repair is sufficient. `quality_pass` is only a provisional precheck; `quality_accepted` stays false until actual adjudication. Retain the complete native response privately, keep `semantic_audit_required` explicit, and record an extraction with `assessment: uncertain` separately as `uncertain_findings`; do not convert uncertainty into a genuine detection or automatically call it a false alarm. An unresolved critical false approval sets `critical_false_approval`, fails the precheck and forbids an acceptable efficiency conclusion, regardless of apparent speed. The harness leaves `acceptable_efficiency_claim` false; only actual independent adjudication and complete comparable measurements can support such a conclusion.

Audit extraction and semantic adequacy as one lightweight controller supervision batch within the proposal's 24-minute supervision allowance. Do not launch a new model, an extra full review or an outer review cycle for each trial. If the bounded audit cannot finish, retain provisional/uncertain results and the incomplete audit rather than manufacturing quality acceptance.

## Accounting contract

Record every decision and the complete trajectory, including interrupted, blocked, failed and diagnostic attempts. Preserve unknown observations as unknown, with source/reason; never convert missing usage or intervals to zero.

| Observation | Required distinction |
| --- | --- |
| Model time | Active time and source by session/role; summed session/model time separately from elapsed time |
| Critical path | Start-to-endpoint elapsed and interval unions; concurrent work must not be summed into elapsed time |
| Controller work | Setup/calibration and supervision separately, also included in experiment totals |
| Waiting | Provider/queue, tool, handoff and other wait intervals, without double-counting overlapping intervals |
| Repairs | Prescribed repair, native checks, reruns and repair/resume decisions; retain each original attempt |
| Reads | Total/unique returned bytes, calls, overlapping/repeated reads, and automatic packet presentation separately from explicit reads |
| Probes | Access/boundary probes separately from reviewer inspection |
| Usage | Native input/output/cache token counters and quota observations, sources, deltas and gaps; bytes are not tokens |
| Sessions/tools | Actual launches, requests and tool calls, prescribed limits and any overrun |

Fewer reads or lower review time alone does not establish whole-flight savings. Compare time to the common endpoint only when quality and observability permit it; keep non-completing trajectories visible.

## Finite measured-cohort proposal: not authorized to execute

This implementation may be merged independently of the following proposal. The public `cohort_proposal` leaves unresolved private variant, oracle, prompt, environment, source, workflow and evidence bindings as `null`, not placeholder hashes. Its validator rejects an approved launch while any required binding remains unresolved. The final private freeze must bind the actual available inputs; report any readiness gap rather than presenting the public proposal as launch-ready. No measured model cohort, model-provider spending, fallback or purchases are authorized by the implementation task. The separate implementation delivery grant for GitHub PR, merge and issue work remains unchanged. Freeze the final candidate, private manifest/oracle, exact briefs, matched settings, views, accounting sources and enforcement mechanism, then obtain separate owner approval before launch.

Propose twelve decision states, one repetition each: six clean and six defective. Three are single-decision inspections of the three preserved pre-repair historical Ripgrep views. The remaining nine are explicitly derived synthetic states with common premises; they do not reconstruct historical repairs or establish real reviewer acceptance. The public manifest reserves `h1`, `h2` and `h3` for the three historical defective states; bind their exact opaque view mapping privately. The proposed synthetic sequence and forks are:

| State | Premise | Expected quality class |
| --- | --- | --- |
| s0 | Initial synthetic clean evidence | Clean |
| s1, from s0 | Changed effective input and affected claim invalidate accepted bindings | Defective |
| s2, from s1 | Prescribed synthetic repair and resume restore the affected proof | Clean |
| s3, from s2 | Contradictory original evidence reopens the relevant claim | Defective |
| s4, from s3 | Prescribed synthetic repair resolves that contradiction | Clean |
| s5, from s4 | Necessary evidence becomes inaccessible; prelaunch readiness negative | Defective |
| s6, from s5 | Necessary access is restored before the decision | Clean |
| s7, fork from s2 | Navigation-only relocation with identical verified target bytes | Clean |
| s8, fork from s4 | Inaccessible duplicate remains covered by accessible correctly bound evidence | Clean |

The synthetic spine contains three repair/resume transitions; its two clean forks test preservation of valid proof. Freeze each snapshot and its runtime-specific representation before launch. Synthetic seeded histories and scripted premises remain labeled synthetic. A preceding measured reviewer result is retained as an observation, never silently replaced by a claimed approval; the next scheduled snapshot uses the frozen experimental premise regardless of that result. No repair worker or feedback-driven extra attempt is included. Wrong-binding, tamper, unresolved-obligation and current-diff variants remain deterministic calibration coverage, not separate measured cases in this small proposal.

The s5 access-negative state is a remaining cohort-readiness gap. Keep it as a prelaunch readiness negative unless a separately frozen valid vignette exposes the absence as accessible decision data. Do not relax actual required-evidence access, or launch an invalid trial to fill the 48 planned slots. The public cohort proposal is not yet privately frozen or launch-ready; no model run is implied.

For each separately frozen, launch-ready state, the proposed schedule is CODE and then one fresh independent final session. Two conditions × twelve states × two stages = **48 planned reviewer sessions**, at most 48 attempts. This count includes s0, every continuation and both forks. The final reviewer may see the prescribed CODE result in both conditions. Capture first verdicts before oracle feedback. No discretionary extra stage, retry-until-green rule or outer review cycle is included.

Freeze execution order as the three historical views, then s0 through s8. Use baseline-first for odd-numbered states in that order and incremental-first for even-numbered states. Run CODE then final for the first condition, then CODE then final for its pair, in isolated views. Record actual order and interruptions. This single-repetition cohort is a bounded paired case study, not a general performance estimate.

Proposed matched settings are OpenAI Codex, `gpt-6.1-sol`, high reasoning effort, the same client build and read-only tool/permission profile. Verify effective settings before launch; unavailable settings require a revised approved freeze, not a silent substitute. The future controller must enforce these proposed caps; the offline harness does not launch or police model sessions:

| Limit | Proposed ceiling |
| --- | --- |
| Reviewer session | 4 minutes elapsed including provider/tool waits; 24 total tool calls, including evidence reads and access probes |
| Reviewer attempts | 48 total, including interrupted/unavailable launches; 192 minutes summed session elapsed at the individual ceilings |
| Setup/calibration | 45 minutes total, recorded separately |
| Controller supervision | 24 minutes active total, recorded separately |
| Other overhead | 24 minutes elapsed total for native checks, scripted repair/resume preparation, diagnostics and reruns |
| Entire serial experiment | 285 minutes elapsed, including setup, supervision, other overhead and waits; stop on the first exhausted applicable cap |

Record every tool call, native token counter and quota observation when available. Missing token/quota metrics remain UNKNOWN and make the affected cost comparison unavailable; they do not alone block subscription-funded quality inspection. Stop for an actual capacity, access or effective-configuration blocker. No dollar conversion is inferred from tokens or unavailable quota. Any mandatory preflight diagnostic rerun consumes setup/overhead limits and is retained. No failed reviewer launch is silently replaced: it occupies its scheduled slot and yields an incomplete outcome. Do not reallocate unused attempts to another slot. Preserve native outputs, usage gaps and stop reasons, and publish no invented model result.
