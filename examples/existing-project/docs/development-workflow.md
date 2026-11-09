# Selected development workflow

Use this workflow for an explicitly selected task or its resume. The project owns the commands, acceptance criteria, execution boundaries, and delivery grant. Ordinary requests use their normal entry points.

## Project setup

Fill in the entries below during adoption. Record the exact commands, prerequisites, applicable paths, and inputs for each gate. Unconfigured required checks remain pending. Record a reason for each gate that is genuinely inapplicable.

| Setting | What to record |
| --- | --- |
| Cheap checks | Use project commands for lint, documentation, and policy as applicable. `git diff --check HEAD` is a starting whitespace check for tracked changes. Cover new candidate files with the applicable project checks. |
| Authoritative checks | Exact focused and broad test commands and their coverage. A pytest project might use `python -m pytest -q` from its configured development environment. Record the equivalent for your stack. |
| UI verification | How to serve interactive HTML using synthetic data, identify the approved surface, run any automated visual checks, and validate the producing run's report. |
| Test isolation | Disposable data or databases, service ports, scratch, caches, reports, and teardown. Use distinct worktrees for concurrent runs and serialize any suite that still shares mutable resources. |
| Evidence | An approved private location that survives checkout removal, with the evidence retention and access rules. Keep output free of credentials and sensitive data. |
| Delivery | Target repository and branch, permitted provider writes, the tracker for nits, required checks, and the owner's grant and holds. Recheck current provider policy before delivery. |

## Run and resume

1. Record task scope, acceptance, checkout, base, current diff, and intended delivery. Give each deterministic criterion a reproducible assertion. Present a bounded implementation plan before editing.
2. Implement and run applicable cheap checks. For owner-facing UI, provide the exact interactive HTML URLs and synthetic fixture identities, bind the preview to the candidate surface, and pause for the owner's answer. Get new approval after a surface edit. Show rendered images only on request. Nonvisual work goes straight to CODE review.
3. Ask the independent CODE reviewer to inspect the candidate and scripted acceptance. Repair blocking findings before expensive gates. Then run applicable focused, broad, and visual checks. Bind any visual findings and freshness check to the report from that run. Execute deterministic checks within the project tool boundary and record live-only checks separately.
4. Ask the independent EVIDENCE reviewer to inspect the current candidate, CODE findings and repairs, gate outputs and scope, and owner decisions. Route the verdict only after required checks and reviews are complete.

On resume, inspect the actual checkout, original results, current approvals, active processes, and provider state before repeating work. Keep failures and interrupted results. Repair in scope and run the cheapest affected check first. Renew CODE review after material changes to scope, behavior, risk, or acceptance assertions. Renew EVIDENCE review when its candidate or evidence changes. Record elapsed time, reruns, and review returns. Continue repair within actual limits and explicit holds, without fixed time or iteration quotas.

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

Reuse a whole passing check only if the latest attempt completed successfully, the command and required coverage match, all recorded inputs and relevant runtime still match, and the original output is present with its digest intact. Record reuse against the current candidate. A newer failure, interruption, unresolved attempt, or invalidation supersedes an older pass. Re-run if any required comparison is unavailable. For link checks include target existence, and for visual checks bind the producer and findings reader to the same run and inputs.

## Independent review

Launch the roles `workflow-code-reviewer` and `workflow-evidence-reviewer` in a separate read-only Codex review session, with only the tools and evidence needed for review. Check the effective sandbox and available tools before using the role. A role's instructions do not set its sandbox. Reviewers must have no provider write tools or access to secrets, and no executable hooks should run in the review session. If the client cannot provide that boundary or the reviewer cannot inspect required evidence, keep the review pending. [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)

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
