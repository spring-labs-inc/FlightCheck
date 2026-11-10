# Selected development workflow

Use this workflow for an explicitly selected task or its resume. The project owns the commands, acceptance criteria, execution boundaries, and delivery grant. Ordinary requests use their normal entry points.

## Project setup

Fill in the entries below during adoption. Record the exact commands, prerequisites, applicable paths, and inputs for each gate. Unconfigured required checks remain pending. Record a reason for each gate that is genuinely inapplicable.

| Setting | What to record |
| --- | --- |
| Cheap checks | Use project commands for lint, documentation, and policy as applicable. `git diff --check HEAD` is a starting whitespace check for tracked changes. Cover new candidate files with the applicable project checks. |
| Early CODE review | Project-specific risk triggers and cases where review before an expensive run could avoid substantial rework. |
| Authoritative checks | Exact focused and broad test commands and their coverage. A pytest project might use `python -m pytest -q` from its configured development environment. Record the equivalent for your stack. |
| UI verification | How to serve interactive HTML using synthetic data, identify the approved surface, run any automated visual checks, and validate the producing run's report. |
| Test isolation | Disposable data or databases, service ports, scratch, caches, reports, and teardown. Use distinct worktrees for concurrent runs and serialize any suite that still shares mutable resources. |
| Evidence | An approved private location that survives checkout removal, with the evidence retention and access rules. Keep output free of credentials and sensitive data. |
| Interactive task status | Optional path to the task publisher and loopback server, private snapshot location, and port allocation. Record the task's stable route on activation and reuse it on resume. |
| Delivery | Target repository and branch, permitted provider writes, the tracker for nits, required checks, and the owner's grant and holds. Recheck current provider policy before delivery. |

## Run and resume

1. Record task scope, acceptance, checkout, base, current diff, and intended delivery. Give each deterministic criterion a reproducible assertion. Present a bounded implementation plan before editing.
2. Implement and run applicable cheap checks. For owner-facing UI, provide the exact interactive HTML URLs and synthetic fixture identities, bind the preview to the candidate surface, and pause for the owner's answer. Get new approval after a surface edit unless the owner explicitly waives the preview pause. Show rendered images only on request.
3. Record whether early CODE review is warranted. Use it for risks such as migrations, permission or trading changes, or an uncertain approach or acceptance check that could waste a long gate run. If triggered, ask the reviewer to inspect the candidate and scripted acceptance and repair blocking findings. Run applicable focused, broad, and visual checks. Bind any visual findings and freshness check to the report from that run. Execute deterministic checks within the project tool boundary and record live-only checks separately.
4. Validate the final packet with the shared handoff command, then ask one independent final reviewer to inspect the current diff and evidence. Give them a compact packet with the candidate, acceptance criteria, required gates and pass or reuse receipts, original outputs, applicable owner decisions and delivery limits, and any early findings and repairs. Route the verdict after the reviewer returns.

On resume, start with the shared resume summary and reconcile any open work with the current checkout, active processes and provider state before repeating work. Keep failures and interrupted results. Repair in scope and run the cheapest affected check first. Reassess the need for early CODE review after material changes to scope, behavior, risk, or acceptance assertions. Renew final review when its candidate or evidence changes. Record elapsed time, reruns, and review returns. Continue repair within actual limits and explicit holds, without fixed time or iteration quotas.

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

Use the recorder with a stable `--gate` and a project-owned `--fingerprint-command` (a JSON argument array) for each expensive check that can be reused. Run this same invocation for a fresh attempt or on resume. Cheap checks can run directly.

```sh
python3 scripts/capture_check.py --evidence-dir "$evidence_dir" --candidate "$candidate" \
  --gate offline-pytest --scope "Full offline pytest suite" --summary pytest \
  --fingerprint-command '["python3", "scripts/fingerprint_check.py", "offline-pytest"]' \
  -- .venv/bin/python -m pytest -q
```

The project implements the fingerprint command. Its stable, nonsecret output must cover every gate input and the relevant runtime, including dependencies, fixtures and configuration. Exit unsuccessfully if any required input is unavailable. For a visual gate, use a command that validates a freshly produced, current report. Supply each report to retain with `--artifact` using stable checkout-relative paths.

Keep one private evidence root per task and use the same gate identifier for all attempts of a given check. The recorder serializes those attempts, marks the newest one before executing, and compares the current fingerprint to both fingerprints from that run. It checks the saved command, scope and original output and report digests before recording reuse. A failed, interrupted or incomplete newer attempt prevents reuse of an older pass. Use `--refresh` to force a new attempt under that gate identifier, including after an explicit invalidation. Send every governing attempt through the recorder when reuse is enabled. The recorder retains the native exit status if a check ran, and missing artifacts or fingerprints make the receipt ineligible for reuse.

Include link-target existence in docs fingerprints. For visual checks, bind the producer and findings reader to the same run and inputs.

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
| `gates` | All required checks. Each entry has an `id` matching the recorder's gate identifier and a `request` with the exact `command`, `scope`, `summary`, `fingerprint_command` and `artifacts` used by the recorder. For an explicitly reused pass, include `reuse` with its receipt path relative to the evidence root. |
| `diff`, `acceptance`, `delivery` | For final review, the current diff's path inside the evidence root, the acceptance criteria and delivery boundaries. Supply `decisions` and `findings` when there are owner decisions or early review findings to carry forward. |

The resume summary reports the current and saved candidate, preview applicability, and which gates are reusable, stale, failed, missing or unverified. It runs the configured fingerprint probes and validates retained evidence. Run the applicable recorder invocations to establish current pass or reuse receipts.

The final command binds the diff digest and verifies the latest required attempts, current fingerprints, original output and artifact digests, reuse decisions, and preview applicability. Exit status 1 means there are unresolved prerequisites. Repair them before starting final review. Exit status 0 means the packet is ready for a reviewer to judge correctness and coverage. Refresh the packet when the candidate, gate results or decisions change. Reviewers can follow the evidence paths for exceptions and ambiguous results.

## Independent review

Launch `workflow-evidence-reviewer` for the final code and evidence verdict. Launch `workflow-code-reviewer` only when the early review criteria apply. Give each applicable reviewer a separate read-only Codex session with the tools and evidence needed for their review. Check the effective sandbox and available tools before using the role. A role's instructions do not set its sandbox. Reviewers must have no provider write tools or access to secrets, and no executable hooks should run in the review session. If the client cannot provide that boundary or the reviewer cannot inspect required evidence, keep the review pending. [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

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
