# Benchmark maintenance qualification, version 2

This qualification adds known escaped-defect checks and verifies corrected private references. It does not change the original twelve runs, their timings, first verdicts, or endpoint results, and does not constitute a new measured cohort.

| Candidate | Known-case result | Meaning |
| --- | --- | --- |
| Django run 2 | Rejected | Direct tuple lookup changes its caller; invalid projected SQL width lacks the required validation. |
| Django run 3 | Rejected | The same gaps, plus an implicit projection with a shadowing extra alias fails. |
| ripgrep run 2 | Rejected | Implicit binary-file filtering regresses. |
| Corrected Django reference v2 | 7/7 pass | Original private evaluator passes; 1,071 native tests: 1,041 pass, 27 skip, 3 expected failures. All 1,060 baseline identities/outcomes preserved. |
| Corrected ripgrep reference v2 | 6/6 pass | Original private evaluator and formatting pass; 415 native tests pass. All 398 baseline identities/outcomes preserved. |

The old reference implementations fail expanded qualification and must not be used for the next cohort. Version 2 restores the exact original pins and applies the final Django run 1 source/test patch and ripgrep run 3 patch with its added reader file. The Django patch is qualified here with the full native suite; this does **not** turn the original incomplete Django run 1 into a completed benchmark attempt.

Controls exercise explicit composite-key projection, literal tuples, explicit text searches, streaming while stdin remains open, and BOM/buffer-boundary consistency for named files and redirected regular stdin. Django's missing projected-width validation also occurs in the original baseline; it is a coverage gap, not evidence that every such failure was introduced by a candidate. The ripgrep run 2 binary-file failure changes previously passing baseline behavior.

The [machine-readable qualification record](qualification-v2.json) provides suite, patch, source, report and native-output hashes. Original outputs, corrected reference patches, evaluator observations and an inventory are retained in the private benchmark-maintenance archive; neither private evaluator nor reference implementation is published here. Every tracked original benchmark result file was compared byte for byte with the preserved results commit. Qualification uses disposable fixtures and fresh reports, and checks frozen product fingerprints before and after evaluation.

For future runs, follow the [versioned calibration protocol](../docs/benchmark.md#versioned-qualification-after-escaped-defects). These known cases become visible acceptance checks. Keep separate unseen evaluation after the first workflow verdict so improving known coverage does not replace an independent assessment of new defects.
