# Claude qualification report

Status: **partial; full native qualification and acceptance remain pending**. See the [machine-readable status](claude-trial-status.json) and [reproduction guide](claude-code.md). This report records actual preparatory/native probes and a concrete execution blocker; it is not a successful end-to-end flight.

## Environment and fixture

- Source base: `070d9c0bb2cd0eb964860ea584bcfb48372c1782`, with the uncommitted contributor/example adapters and guide copied into a private source snapshot (`5d91568fe01aa8e4ceb11da9a852521670e3b671`). Snapshot-only commits do not modify the contributor branch.
- Fixture: disposable label normalization from the first-flight example, existing independent `AGENTS.md`/`CLAUDE.md`, opt-in activation, private synthetic evidence, and no GitHub remote/provider-write grant. Starting policy commit: `249a8b7b9cc18473935277250850ae5b227f1d86`.
- Client: local Claude Code **2.1.311**, `claude.ai` authentication; native request metadata reported **claude-sonnet-4-6**. The interactive header showed high effort; per-request effective effort was not independently established.
- Host: macOS/POSIX under an enclosing automation sandbox. The selected contributor interpreter is Python 3.13.18 with pytest 9.2.0. Other clients/platforms are untested by these probes.

Only copied FlightCheck sources, the toy project and toy evidence were approved for model context. Original private maintainer evidence, customer material and credential-store files were excluded from model tools. The CLI used its normal sign-in. Raw transcripts, prompts, exact commands, runtime records and source/fixture manifests are retained privately outside the checkout; publish only this sanitized summary.

## Observed portable preparation

The source snapshot's installer completed `inspect`, `plan`, `apply --agent claude` and installed `verify`, returning `ready_for_client_probe`. It retained both independent instruction texts and installed shared tools, the card and client definitions. The helper captured the real existing normalization witness/baseline and separate spec. None of those outputs constituted a reviewer approval or native client qualification.

## Observed native probes

| Context | Actual observation | Limit |
| --- | --- | --- |
| Contributor discovery | Native metadata included `develop-change`, `workflow-code-reviewer` and `workflow-evidence-reviewer`; the client read/resolved the shared sources | Read-only discovery, not an implementation flight |
| Installed adopter discovery | Native metadata found the same command/roles; existing policy remained present and the response identified opt-in/ordinary-question routing | No completed selected flight or all-phase card observation |
| Interactive contributor TUI | `/context` displayed `CLAUDE.md`, `AGENTS.md` and both custom reviewers; `/hooks` displayed disabled | A trust prompt for the reviewed synthetic source was accepted; this is a version/host-specific observation |
| Separate named CODE and EVIDENCE contexts | Actual inventories contained only Read/Grep/Glob; each read the toy packet and received a tool-level denied-directory error for the synthetic secret canary | Probe observations, not full review verdicts; advisory JSON must not be used as approval |
| Enclosing read-only host boundary | Actual exclusive-create probes in source/evidence and a synthetic-secret read were denied; required toy reads worked | This extra host boundary is part of the observed setup, not something the Markdown frontmatter installs |

Reviewer launches used explicit read tools, no MCP servers/provider tools, `dontAsk`, a session-only hooks override and narrow evidence access. No Edit/Write/Bash/Agent capability appeared in the actual reviewer inventories. Required accesses and denials were observed rather than inferred from a role name. The TUI's hooks-disabled display and the absence of role frontmatter hooks were recorded separately. General read-only profiles, different managed hooks/settings and other versions still need their own probes.

## Remaining qualification

The strict synthetic controller probe enabled the command sandbox with fail-if-unavailable and no unsandboxed retry. Its actual Bash tool result for `pwd` was `sandbox-exec: sandbox_apply: Operation not permitted`, exit **71**. The synthetic canary command was also refused before execution. This is a host/sandbox initialization failure, not a failing product witness and not proof of a usable controller sandbox. No permissions were broadened to bypass it.

Consequently these remain unperformed:

- A real selected Claude TUI flight changing public behavior, with independent Plan, exact behavioral/compatibility witnesses, qualified controls, actual early CODE, authoritative checks, separate final EVIDENCE and a validated current-candidate verdict.
- Controller-owned native check execution and functional repair/resume, retained requests across restart, and missing/inaccessible evidence, failed-check and stale-verdict refusal/recovery within that native flight.
- Proactive browser guidance and one stable, complete card/footer through every Claude controller phase; actual trial-card browser rendering and forwarding where supported. Native read-only discovery and Python HTTP tests do not substitute for those observations.
- Reproduction by another fresh session, final integrated compatibility checks and review/acceptance of a completed sanitized trial report. No contribution PR or issue closure is authorized by the current uncommitted-review task.

Run the remaining procedure on a local Claude host where the required command sandbox starts, preserving review isolation and recording any equivalent verified host boundary. Do not disable safeguards to make the trial appear complete. #14 remains open.

## Completion record

When the remaining trial succeeds, add exact source/candidate/spec identities, environment/model/settings, native commands and outcomes, original reviewer capture references, boundary/repair/failure-control receipts, each browser/footer observation, final validated verdict and maintainer acceptance. Retain original private evidence durably and link only approved sanitized material. Never replace an unavailable observation with an inferred pass.
