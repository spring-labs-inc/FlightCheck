# Selected development workflow

Use this workflow for an explicitly selected task or its resume. The project owns the commands, acceptance criteria, execution boundaries, and delivery grant. Ordinary requests use their normal entry points.

## Project setup

Fill in the entries below during adoption. Record the exact commands, prerequisites, applicable paths, and inputs for each gate. Unconfigured required checks remain pending. Record a reason for each gate that is genuinely inapplicable.

| Setting | What to record |
| --- | --- |
| Cheap checks | Configure fast, reliable commands for the affected behavior, such as focused regression tests, schema validation, lint, documentation, or policy checks. Use observed runtime and setup cost to choose commands that can run on each relevant repair. `git diff --check HEAD` is a starting whitespace check for tracked changes. Cover new candidate files with the applicable project checks. |
| Early CODE review | Use the [standard criteria](#decide-on-early-code-review) and record any project-specific risk triggers. |
| Authoritative checks | Exact required test commands and their coverage. Classify each check by when it should run. A required check can run in the cheap stage when its full declared scope is fast. Schedule the remaining focused, broad, and visual checks after CODE review when it applies. |
| Check ownership | Assign one owner per required gate. The worker can own configured checks it can run through the trusted recorder at the applicable stage. The controller owns private, unavailable, and fallback checks. Use one gate identifier and evidence root across the handoff. |
| UI verification | How to serve interactive HTML using synthetic data, identify the approved surface, run any automated visual checks, and validate the producing run's report. |
| Test isolation | Disposable data or databases, service ports, scratch, caches, reports, and teardown. Use distinct worktrees for concurrent runs and serialize any suite that still shares mutable resources. |
| Evidence | An approved private location that survives checkout removal, with the evidence retention and access rules. Keep output free of credentials and sensitive data. |
| Interactive task status | Optional path to the task publisher and loopback server, private snapshot location, and port allocation. Record the task's stable route on activation and reuse it on resume. |
| Delivery | Target repository and branch, permitted provider writes, the tracker for nits, required checks, and the owner's grant and holds. Recheck current provider policy before delivery. |

## Run and resume

1. Record task scope, acceptance, checkout, base, current diff, and intended delivery. Give each deterministic criterion a reproducible assertion. Present a bounded implementation plan before editing.
2. Implement and run applicable cheap checks on the candidate. Record failures from independent checks together when they can run safely. Repair failures and refresh affected checks before moving on. For owner-facing UI, then provide the exact interactive HTML URLs and synthetic fixture identities, bind the preview to the candidate surface, and pause for the owner's answer. Get new approval after a surface edit unless the owner explicitly waives the preview pause. Show rendered images only on request.
3. [Decide whether to run early CODE review](#decide-on-early-code-review). If triggered, ask the reviewer to inspect the candidate and scripted acceptance after the cheap checks pass. Repair blocking findings and refresh affected cheap checks before any CODE re-review. Run the remaining required gates and retain any earlier receipts that cover the required command, scope, and current inputs. Bind any visual findings and freshness check to the report from that run. Execute deterministic checks within the project tool boundary and record live-only checks separately.
4. Validate the final packet with the shared handoff command, then ask one independent final reviewer to inspect the current diff and evidence. Give them a compact packet with the candidate, acceptance criteria, required gates and pass or reuse receipts, original outputs, applicable owner decisions and delivery limits, and any early findings and repairs. Route the verdict after the reviewer returns.

On resume, reconcile any open work with the current checkout, active processes and applicable provider state. Use the shared resume summary to route the task. When it reports `final_review`, establish any required reuse receipts, validate the final packet, and send it directly to the independent final reviewer. If the candidate or evidence changes during preparation, or the final packet is blocked, return to the normal resume path. Keep failures and interrupted results. Repair in scope and run the cheapest affected check first. Reassess the need for early CODE review after material changes to scope, behavior, risk, or acceptance assertions. Renew final review when its candidate or evidence changes. Record elapsed time, reruns, and review returns. Continue repair within actual limits and explicit holds, without fixed time or iteration quotas.

### Decide on early CODE review

Run early CODE review for material risk, such as a migration, permission or trading change, a change to a shared contract or across a boundary, or uncertainty about the approach or acceptance where early review could avoid substantial rework. A small diff can change behavior for many callers.

Skip early review when the change establishes or restores one bounded invariant, the affected paths are understood, and focused checks cover the change and relevant compatibility controls. A shared implementation is a reason to trace affected callers. Run early review if their impact or coverage remains materially uncertain. Record the decision and its reason for the current candidate after the cheap checks. Reassess it after material changes to scope, behavior, or evidence.

### Prepare each session

Use the project instructions and the relevant stage input. For a fresh implementer, the adapter can run `python3 scripts/handoff.py brief --task "$task_json"` with the task scope, acceptance, delivery boundary, and required gates. The brief supplies the standard early CODE criteria. Set `early_code` to the full applicable criteria when the project adds its own risk triggers. Include `preview` for UI work. Set `invocation` on worker-owned gates to the worker-facing command or command arguments. The brief lists gate ownership and scope and includes only worker-facing invocations. Give a resumed worker its current blockers and affected checks.

Give the CODE reviewer the validated CODE packet, including the task scope and acceptance criteria, with original evidence available when needed. Give the final reviewer the validated final packet. Open the applicable guide section when a stage input leaves a decision or requirement unresolved. Load status-card instructions for interactive tasks with a configured card.

## Evidence and reuse

For each check, record the run and candidate identity, exact command, coverage and skips, environment identity, relevant inputs before and after, exit status, and path and digest of original output. Include dependencies, linked files, test data, and report-producing runtimes where the check uses them.

### Capture native check output

Use your project's existing artifact recorder or copy the optional [capture script](../scripts/capture_check.py). The example needs Python 3 on a POSIX host and uses the standard library. Run it from the project root with an existing owner-only evidence directory outside the checkout. Set `evidence_dir` to that approved location and `candidate` to the current frozen candidate identity.

```sh
python3 scripts/capture_check.py --evidence-dir "$evidence_dir" --candidate "$candidate" \
  --scope "Full offline pytest suite" --summary pytest -- .venv/bin/python -m pytest -q

python3 scripts/capture_check.py --evidence-dir "$evidence_dir" --candidate "$candidate" \
  --scope "Clippy for all targets" -- cargo clippy --all-targets
```

Each invocation creates a fresh private run directory for evidence and runs the command without a shell. The check runs in the project checkout with noninteractive stdin and must wait for its workers. The recorder writes combined stdout and stderr to `output.log`, then replays that file after the check ends. Display truncation or a closed display pipe leaves the original file available. `run.json` records the exact command, requested scope, actual exit status, and the output's relative path and SHA-256. The project still owns test isolation, access policy, and verification of the candidate and actual coverage.

The optional pytest summary mode records recognizable final totals and distinguishes a captured warning summary, a completed run with no reported warnings, an incomplete run, and an unavailable summary. Suppressed or unrecognized summaries leave the original log available. Without the optional parser, warnings are marked unclassified and can be inspected in the native output. Retain separate report files under the project's existing evidence rules. A killed recorder can leave an incomplete packet with no observed exit status.

### Reuse a result

Use the recorder with a stable `--gate` and a project-owned `--fingerprint-command` (a JSON argument array) for checks whose receipts are verified or reused. Run this same invocation for a fresh attempt or on resume. Cheap checks outside the receipt-based handoff can run directly.

```sh
python3 scripts/capture_check.py --evidence-dir "$evidence_dir" --candidate "$candidate" \
  --gate offline-pytest --scope "Full offline pytest suite" --summary pytest \
  --fingerprint-command '["python3", "scripts/fingerprint_check.py", "offline-pytest"]' \
  -- .venv/bin/python -m pytest -q
```

The project implements the fingerprint command. Its stable, nonsecret output must cover every gate input and the relevant runtime, including dependencies, fixtures and configuration. Exit unsuccessfully if any required input is unavailable. For a visual gate, use a command that validates a freshly produced, current report. Supply each report to retain with `--artifact` using stable checkout-relative paths.

Keep one private evidence root per task and use the same gate identifier for all attempts of a given check. The recorder serializes those attempts, marks the newest one before executing, and compares the current fingerprint to both fingerprints from that run. It checks the saved command, scope and original output and report digests before recording reuse. A failed, interrupted or incomplete newer attempt prevents reuse of an older pass. Use `--refresh` to force a new attempt under that gate identifier, including after an explicit invalidation. Send every governing attempt through the recorder when reuse is enabled. The recorder retains the native exit status if a check ran, and missing artifacts or fingerprints make the receipt ineligible for reuse.

Include link-target existence in docs fingerprints. For visual checks, bind the producer and findings reader to the same run and inputs.

### Verify native test coverage

A project can produce a fresh JSON coverage report from each governing native run and retain it using `--artifact`. Use the trusted check runner to translate native reports into four arrays of unique test identities named `passed`, `skipped`, `expected_failures`, and `failed`. Regenerate the report from that run and clear old reports before execution. Keep required baseline identities and their outcomes in a separate file with the same schema. Freeze its digest independently of the worker.

Set the gate's optional `coverage` object with `artifact` equal to the report path in `request.artifacts`, `baseline` equal to the baseline file path under the evidence root, and `baseline_sha256` equal to its frozen digest. The handoff verifies both digests, compares identities and outcomes, and includes verified totals and the baseline comparison. A reported failure, missing required identity, changed baseline outcome, or damaged evidence blocks the gate.

### Carry checks across the handoff

Give the worker the exact configured invocation for each gate it owns, including the stable gate ID and task evidence root. Add `--owner worker` to its recorder invocation. For gates owned or taken over by the controller, use `--owner controller`. Execute the canonical command through a trusted recorder under the project's tool boundary. The task adapter owns the evidence store and establishes which recorder can write governing receipts. A manually assembled pass or an ad hoc test run does not establish governing evidence. The worker hands off the candidate identity and any unresolved failures. The recorder supplies the evidence.

```sh
python3 scripts/handoff.py checks --task "$task_json" --evidence-dir "$evidence_dir"
```

Use the resulting plan at the applicable stage. Carry a current verified receipt directly into the next stage. For `reuse`, use the recorder to bind the matching older pass to the current candidate and retain its reuse decision. For `run`, the controller takes over and records a fresh result with `--refresh`. For `repair`, return the current failure to the implementer. For `wait`, reconcile the in-progress attempt before continuing. If the process has stopped without a result, resolve the incomplete attempt and record a fresh run. Validate the final packet against the same gate definitions. Keep check commands, coverage, phase, and independent review requirements in force when the owner changes.

## Resume summary and final packet

Use [`handoff.py`](../scripts/handoff.py) next to the recorder. The project adapter writes a task JSON file for the current checkout before either command. Use the same required gate definitions for recording and validation.

```sh
python3 scripts/handoff.py resume --task "$task_json" --evidence-dir "$evidence_dir"
python3 scripts/handoff.py review --task "$task_json" --evidence-dir "$evidence_dir"
```

| Task field | Value |
| --- | --- |
| `candidate`, `saved_candidate` | Current frozen candidate identity from the checkout and the identity saved in the handoff. |
| `preview` | `null` for non-UI work. For UI work, provide the current `surface` fingerprint, the `approved_surface` from the recorded owner decision, and its `decision_reference`. Include a `waiver` reference only when explicitly granted. |
| `gates` | All required checks. Each entry has an `id` matching the recorder's gate identifier and a `request` with the exact `command`, `scope`, `summary`, `fingerprint_command` and `artifacts` used by the recorder. Set `phase` to `cheap` for checks that must pass before CODE review. The default is `authoritative`. Set `owner` to `worker` for an assigned worker gate. The default is `controller`, including for older receipts without an owner. Final review validates both phases. For an explicitly reused pass, include `reuse` with its receipt path relative to the evidence root. |
| `resume_state` | Optional verified state from the task adapter. Set `phase` to `awaiting_final_review` and `pending_work`, `pending_decisions`, and `active_processes` to `false` only after reconciling the saved task with current state. Leave uncertain state unset. |
| `diff`, `acceptance`, `delivery` | For final review, the current diff's path inside the evidence root, the acceptance criteria and delivery boundaries. Supply `decisions` and `findings` when there are owner decisions or early review findings to carry forward. |

The resume summary reports the current and saved candidate, preview applicability, and which gates are reusable, stale, failed, missing or unverified. It runs the configured fingerprint probes and validates retained evidence. The `final_review` route requires explicit clean resume state, an unchanged candidate, reusable required checks, and a current referenced UI approval if applicable. All other cases return `resume_work`. Run the applicable recorder invocations to establish current pass or reuse receipts.

The final command binds the diff digest and verifies the latest required attempts, current fingerprints, original output and artifact digests, configured test coverage, reuse decisions, and preview applicability. Exit status 1 means there are unresolved prerequisites. Repair them before starting final review. Exit status 0 means the packet is ready for a reviewer to judge correctness and coverage. Refresh the packet when the candidate, gate results or decisions change. Reviewers can follow the evidence paths for exceptions and ambiguous results.

## Independent review

Launch `workflow-evidence-reviewer` for the final code and evidence verdict. Launch `workflow-code-reviewer` only when the early review criteria apply. Give each applicable reviewer a separate read-only Codex session with the tools and evidence needed for their review. Check the effective sandbox and available tools before using the role. A role's instructions do not set its sandbox. Reviewers must have no provider write tools or access to secrets, and no executable hooks should run in the review session. If the client cannot provide that boundary or the reviewer cannot inspect required evidence, keep the review pending. [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

Retain the early review session handle and its candidate, verdict and findings when the harness supports secure continuation. After an in-scope repair, write the current full `diff` and the diff from the reviewed candidate to the repair into the task evidence root. Include an `early_review` object with the prior `session`, `candidate`, `verdict`, relative `findings` and `repair_diff` paths, and `scope_unchanged: true` only after confirming that the repair stays within the reviewed scope and risk boundaries.

```sh
python3 scripts/handoff.py code-review --task "$task_json" --evidence-dir "$evidence_dir"
```

Exit status 1 with `action: blocked` means a required cheap check has no verified pass for the current candidate. Resolve the listed blockers before launching or resuming CODE review. For `action: resume`, continue the named early reviewer under the same read-only boundary. Give them the current candidate, cheap-check results, repair diff, prior findings and affected call paths, with the full diff available. Ask for a new verdict on the current candidate. Expand review if the repair exposes new risks or changes affected behavior. For `action: start`, an unavailable session, or a changed boundary, start a fresh read-only CODE review if early review still applies. Always use a separate final reviewer with the full candidate and current evidence.

Retain each review's actual role, candidate, coverage, findings, and disposition. A complete review explicitly reports zero findings when clear. The implementer routes the verdict using those findings and does not submit a review on the reviewer's behalf.

## Landing

| Highest current finding | Verdict | Action |
| --- | --- | --- |
| None, with complete review | `APPROVE` | Begin authorized landing automatically. |
| `NIT` | `APPROVE_WITH_NITS` | Update or add tracker items, then begin authorized landing automatically. |
| `CONCERN` | `APPROVE_WITH_OBSERVATIONS` | Present the actual observations and get separate owner approval to land the current candidate. |
| `BLOCKER` | `REVISE` | Return to scope or implementation and renew affected verification. |
| Review missing or incomplete | Pending | Wait for the missing evidence or review. |

Before any provider write, verify the actual head, target, branch protections, required CI, and current grant. If the provider requires no CI, record it as inapplicable. A required check with no result stays pending. After an ambiguous provider response, inspect the actual remote state before retrying. Record the verified result.
