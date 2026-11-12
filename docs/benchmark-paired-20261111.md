# Authoritative paired benchmark: 24 attempts

This cohort compares FlightCheck at `4ff0e7c5556615bd0dbf082b915ea8747c02be56` with ordinary Codex on four frozen historical defects. Each condition received three fresh attempts per target: **24 attempts, 12 matched pairs**. All planned outcomes are retained. No target changes were committed or published.

Measured attempts ran from **2026-11-12T05:42:07+00:00** to **2026-11-12T11:00:56+00:00**. The cohort wall window was 318m 49.4s; summed attempt times below exclude gaps between attempts and shared setup. The filename retains the experiment's November 11 start date in America/Chicago; later attempts ran on November 12 locally.

**Key findings:** 23 of 24 attempts reached the frozen endpoint; 1 was incomplete. Additional checks demonstrated remaining defects in 5 of 11 approved Django/ripgrep candidates (2 FlightCheck, 3 ordinary). In this cohort, final approval did not exclude all demonstrated defects. These additional checks are exploratory and exclude the unapproved incomplete candidate.

## Outcomes

| Condition | Attempts | Final approvals | Frozen endpoints | Frozen-grade escapes | Incomplete | Sum of measured elapsed | Worker iterations | Repair iterations | Review returns |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| flightcheck | 12 | 11 | 11 | 0 | 1 | 174m 13.7s | 17 | 5 | 4 |
| ordinary | 12 | 12 | 12 | 0 | 0 | 144m 18.0s | 18 | 6 | 6 |

A successful endpoint requires the frozen native scope and baseline outcomes, visible acceptance checks, an eligible blind final skeptical approval, and private evaluation success. A defect escape means private functional evaluation failed **after** that first approval. An incomplete attempt without approval is not an escaped approval.

## Defects that passed final skeptical review

No functional failure was observed by the **frozen private grader** after an eligible final approval in this cohort. This result applies to the measured approvals and this evaluator; it does not establish that every possible defect was excluded.

### Additional checks after the cohort

The frozen grader is only one detection bar. Reviews found concrete additional cases during the cohort. After all 24 development attempts ended, a separate, versioned diagnostic plan checked **every first-approved Django and ripgrep candidate**, plus baseline/reference controls: three projection cases per Django candidate and twelve deterministic promptness/encoding/binary-preservation cases per ripgrep candidate. These are exploratory checks derived from observed review requests, not prespecified private grading. No worker received their results, no candidate was repaired, and no measured score, verdict or duration was replaced.

**5 of the 11 additionally checked approved candidates failed at least one broader case. These are defects that survived final skeptical approval despite passing the frozen grader.** They must not be presented as fully correct speed wins. Counts here are affected candidates, not independent defect families.

| Approved attempt | Condition | Additional failing cases |
| --- | --- | --- |
| django-r1-ordinary | ordinary | `posthoc:duplicate-pk-values`, `posthoc:duplicate-pk-values-list`, `posthoc:duplicate-scalar-validation` |
| ripgrep-r1-flightcheck | flightcheck | `posthoc:null-data-stdin-open`, `posthoc:parallel-lf-stdin-open`, `posthoc:parallel-null-data-stdin-open` |
| ripgrep-r2-ordinary | ordinary | `posthoc:null-data-stdin-open`, `posthoc:parallel-lf-stdin-open`, `posthoc:parallel-null-data-stdin-open` |
| ripgrep-r2-flightcheck | flightcheck | `posthoc:null-data-stdin-open`, `posthoc:parallel-lf-stdin-open`, `posthoc:parallel-null-data-stdin-open` |
| ripgrep-r3-ordinary | ordinary | `posthoc:null-data-stdin-open`, `posthoc:parallel-lf-stdin-open`, `posthoc:parallel-null-data-stdin-open` |

**Supplemental assay correction:** version 2 wrongly required a second leading UTF-16 BOM to be preserved. Original decoder/block-buffered controls remove it, and the actual final reviewer had withdrawn that finding. Those four assertions were invalid for this preservation task and are not counted as product defects. All v2 output remains under `posthoc/`; corrected v3 was frozen and reapplied uniformly, checking original BOM handling plus continued before-EOF delivery. These extra diagnostic executions are outside the measured 24 attempts and their time is excluded.

| Additional case | Behavior required |
| --- | --- |
| posthoc:duplicate-pk-values | Repeated composite-pk values projection must use its effective SQL width and preserve the caller query. |
| posthoc:duplicate-pk-values-list | The same repeated composite projection through values_list must remain valid. |
| posthoc:duplicate-scalar-validation | Repeated scalar projection is one effective column and must be rejected during lookup construction, before database execution. |
| posthoc:null-data-stdin-open | Two NUL-delimited matching records must each arrive before stdin closes. |
| posthoc:parallel-lf-stdin-open | Two LF-delimited stdin matches must each arrive promptly during a parallel search. |
| posthoc:parallel-null-data-stdin-open | Parallel NUL-delimited stdin matches must arrive before EOF. |

Baseline/reference controls help distinguish pre-existing limitations from new regressions; a failed control must be interpreted using its actual error/bytes, rather than equating every failure reason. Control binaries were identified after the cohort with source identities matching their calibrated candidates; calibration predates per-gate product manifests, so their original build-output digest was not available. A reference that passed the original qualification can still fail this broader diagnostic; its original calibration remains unchanged.

| Control | Additional result | Failing cases |
| --- | --- | --- |
| ripgrep-control-baseline | failed | posthoc:null-data-stdin-open, posthoc:parallel-lf-stdin-open, posthoc:parallel-null-data-stdin-open, posthoc:explicit-utf8-short-line, posthoc:explicit-windows1252-short-line, posthoc:bom-compatibility-auto-le, posthoc:bom-compatibility-explicit-le, posthoc:bom-compatibility-auto-be, posthoc:bom-compatibility-explicit-be |
| ripgrep-control-reference | failed | posthoc:null-data-stdin-open, posthoc:parallel-lf-stdin-open, posthoc:parallel-null-data-stdin-open, posthoc:binary-utf16-preprocessor |
| django-control-baseline | failed | posthoc:duplicate-scalar-validation |
| django-control-reference | passed | none |

| Unavailable diagnostic | Reason |
| --- | --- |
| ripgrep-r3-flightcheck | No first eligible approval; not an approved-candidate escape |

Only Django and ripgrep received these added cases. Django used a standalone SQLite fixture; the added ripgrep CLI probes used the default regex engine. fmt and jsoup were not additionally qualified. The added suite does not replay the race-sensitive heading-attribution/record-interleaving cases and is not exhaustive. Two-second streaming observations and finite-file timeouts are retained with actual bytes, commands and binary/source identities. Diagnostic execution time is excluded from all development-time comparisons. Case selection was informed by observed reviews and repairs, so these pass rates are exploratory and do not estimate general detection probability or establish a ranking between conditions.

| Condition | Planned applicable slots | Passed all added cases | Failed added case(s) | Unavailable |
| --- | --- | --- | --- | --- |
| flightcheck | 6 | 3 | 2 | 1 |
| ordinary | 6 | 3 | 3 | 0 |

## Defects caught before final approval

These functional findings caused review returns. Completed candidates were repaired and re-reviewed before eligible approval; the incomplete candidate’s latest repair remains unapproved. Original reviews are retained under the archive at `runs/<Attempt>/reviews/<Review>.json`. They are catches, not escaped approvals. Review-return counts can include process issues; the table below includes functional findings only.

| Attempt | Review | Finding | Disposition | Impact |
| --- | --- | --- | --- | --- |
| ripgrep-r1-ordinary | evidence-1 | EVIDENCE_null_data_promptness | resolved before approval | With piped stdout, run rg --line-buffered --null-data '^x$' - and write x followed by NUL while keeping stdin open. The input path recognizes a complete matching line, but its NUL-terminated output contains no LF and receives no explicit flush. Output can remain buffered until additional output or EOF, leaving the requested prompt-delivery behavior incomplete. |
| ripgrep-r1-ordinary | evidence-2 | EVIDENCE_parallel_stdin_promptness | resolved before approval | With an empty file hay, run rg --threads 2 --line-buffered --no-heading --no-filename '^x$' - hay and write x followed by LF while keeping stdin open. Multiple paths permit parallel search, whose printer accumulates matches in memory and publishes them only after searcher.search returns. Complete matching lines therefore remain invisible until stdin closes. The same path bypasses the new NUL-flushing stdout wrapper. |
| ripgrep-r1-ordinary | evidence-3 | EVIDENCE_parallel_heading_attribution | resolved before approval | With --threads 2 --line-buffered --heading --with-filename, stdin's first match prints its heading. If another file then publishes its heading and matches, stdin's next matching record is emitted through continuation_writer without restoring the stdin heading. That record appears to belong to the other file. A competing publication can also separate the initial stdin heading from its first match. |
| ripgrep-r1-ordinary | evidence-4 | EVIDENCE_parallel_record_atomicity | resolved before approval | With --threads 2 --line-buffered --null --null-data --no-heading --with-filename, the printer writes the filename-ending NUL separately from matching content. ParallelOutput immediately publishes that prefix and releases stdout. Another file's buffer can then appear before stdin's content, producing corrupt filename/content pairings. BufferWriter guarantees atomic chunks, but these chunks are not complete result records. |
| ripgrep-r2-flightcheck | code-1 | CODE_F001 | resolved before approval | An explicit encoding immediately constructs DecodeReaderBytes. Its BOM detection still calls read_full for three bytes before decoding. Thus --line-buffered -E utf-8 '^x$' - waits after receiving x\n while stdin remains open. The same problem affects single-byte encodings such as windows-1252. The requested prompt-line behavior remains incomplete. |
| ripgrep-r2-flightcheck | code-1 | CODE_F002 | resolved before approval | Returning complete lines after each decoder read changes ordinary binary filtering. With explicit UTF-8, the decoder can initially return only its three peeked bytes: a file containing a\nb\0\n exposes a matching a line before the NUL is examined. A UTF-8 BOM also makes the new prefetched 65,536-byte prefix yield only 65,533 decoded bytes, shrinking the initial detection window. An implicit --no-mmap -l search can consequently report a binary file that the original implementation filtered. These changes also apply without --line-buffered. |
| ripgrep-r2-flightcheck | code-2 | CODE_F003 | resolved before approval | Read-ahead is enabled only for regular-file stdin here. Named files searched through --pre or decompression therefore use the streaming decoder and inspect each short decoded read. For UTF-16 input with an initial matching line and a NUL later within the first 65,536 decoded bytes, an implicit -l search can report the path before detecting binary content. The original implementation filled that decoded window and filtered the file. This changes ordinary file-search behavior even without --line-buffered. |
| django-r2-ordinary | evidence-1 | EVIDENCE_selected_width | resolved before approval | The width calculation ignores Query.selected. For Comment.objects.filter(id__in=[1, 4]).values('pk', 'pk').query, Query.select contains two ColPairs expressions but the compiler emits one two-column composite projection. The candidate counts four columns and rejects this valid explicit pk projection. Conversely, values('id', 'id').query emits one column but is counted as two, bypassing the required ValueError and reaching a database width error. Determine width from the effective projection, including ColPairs expansion. |
| ripgrep-r3-flightcheck | code-1 | CODE_null_data_flush | attempt incomplete; no final approval | The fix releases input at the configured line terminator but still relies on stdout's LF-based flushing. With --line-buffered --null-data '^x$' -, writing x followed by NUL produces a complete matching line containing no LF. The printer writes that record without an explicit flush, leaving it buffered while stdin stays open. The requested prompt matching-line behavior therefore remains incomplete for the supported NUL line terminator. |
| ripgrep-r3-flightcheck | evidence-3 | EVIDENCE_parallel_stdin_buffer | attempt incomplete; no final approval | With an empty file hay, run rg --line-buffered -j2 --no-filename --no-heading '^x$' - hay and write x followed by LF while keeping stdin open. Two paths permit parallel execution. Its printer writes into bufwtr.buffer(), and bufwtr.print() runs only after searcher.search() returns. The matching line therefore remains buffered while stdin stays open, leaving the requested prompt-delivery behavior incomplete. |

### Withdrawn review finding

`ripgrep-r2-ordinary` returned for an extra worker/review turn after `EVIDENCE_BOM_CONTENT_LOSS`. Original-product and ordinary-decoder controls disproved its expected output, so final `evidence-2.json` explicitly withdrew it. This was a false-positive review return, not a caught defect. Its time and iteration remain in the measured result. The same overlooked withdrawal caused the supplemental v2 BOM assertion error described above; v3 corrects the diagnostic while preserving every original output.


## Each measured attempt

Durations are elapsed wall time. Workflow time ends at first eligible blind approval; the table shows no approval for an incomplete attempt. Its raw workflow_seconds field stops at terminal failure rather than an approval. Total ends at private grading or terminal failure. Iterations count worker invocations, including the initial invocation; repair iterations include re-entry caused by review findings or controller/check/proof failures. Internal test-and-edit cycles within one invocation remain included in its time. The compact metrics retain controller-repair counts separately from review returns. Compact metrics also retain observed edit checkpoints: a lower bound on source changes seen at tool-completion boundaries, not a count of thoughts or every file save. Review columns count CODE/final skeptical invocations. Gate counts in the compact metrics include controller whitespace, native, known-case and proof gates; historical reproduction invocations are counted separately.

| Attempt | Outcome | Workflow | Total | Iterations / repairs | CODE / final reviews | Review returns |
| --- | --- | --- | --- | --- | --- | --- |
| django-r1-ordinary | completed | 6m 15.9s | 6m 16.8s | 1 / 0 | 0 / 1 | 0 |
| django-r1-flightcheck | completed | 10m 07.3s | 10m 08.4s | 1 / 0 | 0 / 1 | 0 |
| ripgrep-r1-flightcheck | completed | 16m 48.6s | 16m 48.8s | 1 / 0 | 1 / 1 | 0 |
| ripgrep-r1-ordinary | completed | 59m 14.5s | 59m 14.8s | 5 / 4 | 0 / 5 | 4 |
| fmt-r1-ordinary | completed | 5m 14.3s | 5m 15.5s | 1 / 0 | 0 / 1 | 0 |
| fmt-r1-flightcheck | completed | 6m 56.9s | 6m 58.0s | 1 / 0 | 0 / 1 | 0 |
| jsoup-r1-flightcheck | completed | 8m 46.4s | 8m 47.2s | 1 / 0 | 0 / 1 | 0 |
| jsoup-r1-ordinary | completed | 6m 25.7s | 6m 26.5s | 1 / 0 | 0 / 1 | 0 |
| ripgrep-r2-ordinary | completed | 19m 43.5s | 19m 43.8s | 2 / 1 | 0 / 2 | 1 |
| ripgrep-r2-flightcheck | completed | 41m 24.7s | 41m 25.0s | 3 / 2 | 3 / 1 | 2 |
| fmt-r2-flightcheck | completed | 7m 22.4s | 7m 23.6s | 1 / 0 | 0 / 1 | 0 |
| fmt-r2-ordinary | completed | 3m 46.8s | 3m 48.0s | 1 / 0 | 0 / 1 | 0 |
| jsoup-r2-ordinary | completed | 4m 33.7s | 4m 34.5s | 1 / 0 | 0 / 1 | 0 |
| jsoup-r2-flightcheck | completed | 8m 59.8s | 9m 00.6s | 1 / 0 | 0 / 1 | 0 |
| django-r2-flightcheck | completed | 8m 17.6s | 8m 18.5s | 1 / 0 | 0 / 1 | 0 |
| django-r2-ordinary | completed | 11m 03.0s | 11m 04.3s | 2 / 1 | 0 / 2 | 1 |
| fmt-r3-ordinary | completed | 4m 04.5s | 4m 05.7s | 1 / 0 | 0 / 1 | 0 |
| fmt-r3-flightcheck | completed | 7m 26.3s | 7m 27.4s | 1 / 0 | 0 / 1 | 0 |
| jsoup-r3-flightcheck | completed | 9m 10.0s | 9m 10.8s | 1 / 0 | 0 / 1 | 0 |
| jsoup-r3-ordinary | completed | 4m 14.2s | 4m 15.0s | 1 / 0 | 0 / 1 | 0 |
| django-r3-ordinary | completed | 7m 11.2s | 7m 12.3s | 1 / 0 | 0 / 1 | 0 |
| django-r3-flightcheck | completed | 9m 50.8s | 9m 51.7s | 1 / 0 | 0 / 1 | 0 |
| ripgrep-r3-flightcheck | incomplete | no approval | 38m 53.5s | 4 / 3 | 2 / 1 | 2 |
| ripgrep-r3-ordinary | completed | 12m 20.5s | 12m 20.8s | 1 / 0 | 0 / 1 | 0 |

## Timing comparison

These are descriptive times to the **frozen protocol endpoint**, including candidates subsequently found defective by additional checks. Only frozen successful endpoints enter these medians. Paired ratios require both arms of that exact pair to reach that endpoint; failed or incomplete attempts are excluded. These ratios do not establish correctness-adjusted speed wins; consult the additional diagnostics above. Ratios are FlightCheck total / ordinary total; values above 1 mean FlightCheck took longer.

| Target | Condition | Successful attempts | Median total | Range |
| --- | --- | --- | --- | --- |
| django | flightcheck | 3/3 | 9m 51.7s | 8m 18.5s–10m 08.4s |
| django | ordinary | 3/3 | 7m 12.3s | 6m 16.8s–11m 04.3s |
| ripgrep | flightcheck | 2/3 | 29m 06.9s | 16m 48.8s–41m 25.0s |
| ripgrep | ordinary | 3/3 | 19m 43.8s | 12m 20.8s–59m 14.8s |
| fmt | flightcheck | 3/3 | 7m 23.6s | 6m 58.0s–7m 27.4s |
| fmt | ordinary | 3/3 | 4m 05.7s | 3m 48.0s–5m 15.5s |
| jsoup | flightcheck | 3/3 | 9m 00.6s | 8m 47.2s–9m 10.8s |
| jsoup | ordinary | 3/3 | 4m 34.5s | 4m 15.0s–6m 26.5s |

| Pair | Target | Repetition | FlightCheck total | Ordinary total | Eligible paired ratio |
| --- | --- | --- | --- | --- | --- |
| 1 | django | 1 | 10m 08.4s | 6m 16.8s | 1.615 |
| 2 | ripgrep | 1 | 16m 48.8s | 59m 14.8s | 0.284 |
| 3 | fmt | 1 | 6m 58.0s | 5m 15.5s | 1.325 |
| 4 | jsoup | 1 | 8m 47.2s | 6m 26.5s | 1.364 |
| 5 | ripgrep | 2 | 41m 25.0s | 19m 43.8s | 2.099 |
| 6 | fmt | 2 | 7m 23.6s | 3m 48.0s | 1.946 |
| 7 | jsoup | 2 | 9m 00.6s | 4m 34.5s | 1.969 |
| 8 | django | 2 | 8m 18.5s | 11m 04.3s | 0.750 |
| 9 | fmt | 3 | 7m 27.4s | 4m 05.7s | 1.821 |
| 10 | jsoup | 3 | 9m 10.8s | 4m 15.0s | 2.160 |
| 11 | django | 3 | 9m 51.7s | 7m 12.3s | 1.369 |
| 12 | ripgrep | 3 | 38m 53.5s | 12m 20.8s | not comparable |

## Phase accounting

| Attempt | Worker | CODE | Final review | Controller gates | Private grading | Residual controller |
| --- | --- | --- | --- | --- | --- | --- |
| django-r1-ordinary | 3m 58.8s | 0m 00.0s | 2m 12.2s | 0m 03.4s | 0m 00.7s | 0m 01.7s |
| django-r1-flightcheck | 6m 04.0s | 0m 00.0s | 3m 48.7s | 0m 07.6s | 0m 00.7s | 0m 07.5s |
| ripgrep-r1-flightcheck | 11m 30.3s | 3m 06.2s | 1m 49.4s | 0m 20.1s | 0m 00.2s | 0m 02.7s |
| ripgrep-r1-ordinary | 40m 45.9s | 0m 00.0s | 17m 57.0s | 0m 28.0s | 0m 00.2s | 0m 03.8s |
| fmt-r1-ordinary | 2m 58.5s | 0m 00.0s | 2m 13.9s | 0m 01.4s | 0m 01.1s | 0m 00.6s |
| fmt-r1-flightcheck | 4m 35.0s | 0m 00.0s | 2m 05.0s | 0m 15.4s | 0m 01.1s | 0m 01.6s |
| jsoup-r1-flightcheck | 5m 56.8s | 0m 00.0s | 2m 37.5s | 0m 09.8s | 0m 00.7s | 0m 02.5s |
| jsoup-r1-ordinary | 3m 58.8s | 0m 00.0s | 2m 21.3s | 0m 04.9s | 0m 00.7s | 0m 00.8s |
| ripgrep-r2-ordinary | 13m 32.6s | 0m 00.0s | 5m 57.1s | 0m 12.4s | 0m 00.2s | 0m 01.6s |
| ripgrep-r2-flightcheck | 25m 41.8s | 10m 06.5s | 3m 37.8s | 1m 51.9s | 0m 00.2s | 0m 06.9s |
| fmt-r2-flightcheck | 3m 46.4s | 0m 00.0s | 3m 19.0s | 0m 15.6s | 0m 01.1s | 0m 01.6s |
| fmt-r2-ordinary | 1m 52.4s | 0m 00.0s | 1m 52.5s | 0m 01.4s | 0m 01.1s | 0m 00.6s |
| jsoup-r2-ordinary | 2m 24.4s | 0m 00.0s | 2m 03.6s | 0m 05.0s | 0m 00.7s | 0m 00.9s |
| jsoup-r2-flightcheck | 5m 50.7s | 0m 00.0s | 2m 56.9s | 0m 09.7s | 0m 00.7s | 0m 02.8s |
| django-r2-flightcheck | 5m 15.7s | 0m 00.0s | 2m 51.2s | 0m 06.1s | 0m 00.7s | 0m 04.8s |
| django-r2-ordinary | 6m 10.7s | 0m 00.0s | 4m 37.8s | 0m 09.3s | 0m 00.7s | 0m 05.8s |
| fmt-r3-ordinary | 2m 10.0s | 0m 00.0s | 1m 52.7s | 0m 01.4s | 0m 01.1s | 0m 00.7s |
| fmt-r3-flightcheck | 4m 47.6s | 0m 00.0s | 2m 21.8s | 0m 15.4s | 0m 01.1s | 0m 01.4s |
| jsoup-r3-flightcheck | 5m 35.8s | 0m 00.0s | 3m 21.6s | 0m 09.9s | 0m 00.7s | 0m 02.8s |
| jsoup-r3-ordinary | 2m 14.8s | 0m 00.0s | 1m 53.7s | 0m 05.0s | 0m 00.7s | 0m 00.8s |
| django-r3-ordinary | 3m 23.6s | 0m 00.0s | 3m 41.0s | 0m 04.2s | 0m 00.7s | 0m 02.7s |
| django-r3-flightcheck | 6m 08.9s | 0m 00.0s | 3m 30.9s | 0m 06.1s | 0m 00.7s | 0m 05.0s |
| ripgrep-r3-flightcheck | 28m 20.8s | 5m 33.4s | 3m 48.9s | 1m 04.8s | 0m 00.0s | 0m 05.7s |
| ripgrep-r3-ordinary | 9m 23.0s | 0m 00.0s | 2m 52.3s | 0m 04.5s | 0m 00.2s | 0m 00.9s |

Native builds/checks the worker runs internally are included in worker time. Controller gates include expected failures in historical reproductions; those failures are evidence, not newly introduced regressions. Residual time covers handoff, identity checks, process checks, copying and other controller work not assigned to a timed phase. Raw original reports retain every observed native failure. Provider waiting is included. Active time and controller token consumption are unavailable.

## Incomplete attempts and deviations

| Attempt | Retained reason |
| --- | --- |
| ripgrep-r3-flightcheck | RuntimeError: Prerequisites block CODE: ["test-request:CODE_test_null_data_stream", "regression:CODE_null_data_flush"] |

The third FlightCheck ripgrep attempt stopped at a **controller handoff failure**, not a final product verdict. After a prior CODE finding had been repaired and reviewed, a later final-review repair changed the candidate. The frozen controller tried early CODE before refreshing the earlier candidate-bound request/proof receipts; the formal handoff correctly rejected those stale prerequisites. The controller treated that exception as terminal incomplete instead of routing back through the checks. The original blocked packet is `runs/ripgrep-r3-flightcheck/packets/code-4/validated-handoff.json`. No eligible final approval or private grade followed, and the worker’s locally passing repair is not claimed correct. This exposes an uncovered controller transition despite the prelaunch rehearsals. The slot was retained and was not rerun or replaced; fix and qualify that route before a future cohort.

## Method and limits

The worker and review clients requested **gpt-6.1-sol**, **high effort**, using codex-cli 0.167.0. Native rollout configuration observations are retained per session; requested configuration is not substituted for missing observations. Host: `macOS-27.2.1-arm64-arm-64bit-Mach-O`.

Both arms received the same source pin, symptom-only brief, edit scope, native test baselines, published compatibility cases, offline toolchains and final semantic review bar. Ordinary workers had no selected FlightCheck skill or effective workflow instructions. The FlightCheck arm installed the frozen adoption example and enforced its acceptance, conditional early CODE review, evidence, reviewer requests and identical-test before/after proof contracts. The ordinary arm used its normal approach with neutral native collection and the common final skeptical review. Reviewers ran in separate read-only sessions using the same base model as the workers; this provides context separation, not model diversity, and correlated blind spots remain possible. They were blind to private grading/reference outcomes, but condition metadata was not masked.

Attempts and reviews ran sequentially on one host. Target order rotated across repetitions; six pairs ran FlightCheck first and six ran ordinary first. Each attempt had its own cold build outputs, Cargo home, scratch and equivalent Maven seed. Global filesystem/provider caches, queue variation and unrelated host activity were uncontrolled. Three repetitions per historical target support a descriptive comparison, not a general performance or defect-detection claim. Historical public tasks may be familiar to the model.

Shared provisioning, source verification, baseline/reference calibration, access probes, native proof rehearsals and protocol review were excluded from measured time. Initial per-attempt task configuration, source snapshot and brief preparation occurred before its timer; timing started immediately before per-flight preflight/implementation. Per-flight FlightCheck preflight, implementation, checks, repair, reviews, proof replay and private grading were included. Final archive serialization after the terminal timestamp was outside the timer. Preflight controller defects and failed setup rehearsals were repaired before the manifest freeze and retained separately; they are not measured product failures.

Private calibration rejected all four baselines and accepted all four qualified references. The public known-case suite was unchanged from qualification v2 and its retained negative controls were hash-revalidated. Native baseline counts were Django 1060 (1030 passed, 27 skipped, 3 expected failures), ripgrep 398, fmt 160 and jsoup 368. Every required identity/outcome was protected. These were the declared benchmark-native scopes, not the entire upstream repositories’ test suites. The current private evaluator adds held-out cases to the preserved original evaluator; this cohort is not timing-comparable to the earlier twelve-run cohort. Both arms benefited from the expanded visible acceptance cases. Differences from the earlier cohort cannot be attributed solely to the generic FlightCheck workflow changes. Original earlier records remain unchanged.

| Target | Frozen commit |
| --- | --- |
| django-composite-query | `f8fce8d4dce7cf6d272a29351faddd5fa76f1aa0` |
| ripgrep-line-buffering | `3a612f88b805e14aef45bfa43e25a54abc6297fc` |
| fmt-wrapped-value | `40626af88bd7df9a5fb80be7b25ac85b122d6c21` |
| jsoup-replaced-child | `b02837b6c77b94799c055f8fa446fb770bfb49f1` |

## Preserved evidence

Readable results are accompanied by [compact machine metrics](benchmark-paired-20261111.json) (SHA-256 `02b02c55352affab98dbcf938282bdb7412c11857d4cf4bd4de239fc57b21dfa`). The measured archive is `/Users/jeff/FlightCheck-private-archive/paired-authoritative-20261111`. Its inventory binds original prompts/events/rollouts, source patches/restoration bundles, native outputs/receipts, reviews, proof overlays and frozen protocol inputs. Controller-private evaluator/reference source stays outside tracked repository files.

Manifest SHA-256: `5035e0bffd124d8bc178b654b7b4d6744ab469185c85078b141c8d3a39d33ded`. Evidence inventory SHA-256: `7d34182efc02444da7c2d68f10b76b04b942019abfa706c300df55059befda1c`. Every attempt's original result and final patch digest appears in the compact metrics. The retained protocol reviews document pre-measurement fixes; measured results are never silently replaced after grading.
