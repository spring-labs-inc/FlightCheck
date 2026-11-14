# FlightCheck with local Claude Code

Use this guide for a contributor checkout or a real existing-project trial. The installer supplies Claude adapters and the browser card. [Qualification status](claude-trial-status.json) distinguishes observations from pending checks; Python/HTTP success alone does not establish native Claude support. Keep #14 open until a real trial is reviewed and accepted.

## Contributor setup

Use Git and Python 3 on POSIX. The reference reporter is qualified for Python 3.13 with pytest 9.2.x. Choose unused paths outside the checkout for the environment and private evidence:

```sh
git clone https://github.com/spring-labs-inc/FlightCheck.git FlightCheck
cd FlightCheck
git rev-parse HEAD
git status --porcelain=v1 --untracked-files=all
git config user.name
git config user.email
umask 077
trial_area=$(mktemp -d)
python3 -m venv "$trial_area/venv"
trial_python="$trial_area/venv/bin/python"
"$trial_python" -m pip install -r examples/existing-project/requirements.dev.txt
flightcheck_source="$PWD"
```

Record the clean source revision, OS, interpreter and dependency versions. Resolve a missing Git identity locally before authorized commits. Public cloning or a fork does not grant contribution rights: [CONTRIBUTING.md](../CONTRIBUTING.md) currently restricts outside code intake and PR creation. GitHub authentication is needed for authorized delivery, not the local trial.

Install Claude separately using the [official quickstart](https://code.claude.com/docs/en/quickstart). On macOS with Homebrew:

```sh
brew install --cask claude-code
claude auth login
claude auth status --text
claude --version
claude --help
```

Use your own permitted account; record the authentication method without credentials/account identifiers. Claude Code **2.1.311** was observed on the implementation host. That version number alone is not a supported-client qualification. Check commands against the installed help and [CLI reference](https://code.claude.com/docs/en/cli-reference). No global setting changes or permission bypass are required.

## Instruction and reviewer discovery

Start `claude` in FlightCheck's root. Inspect `/memory` and `/context` (or the installed version's equivalent) for `CLAUDE.md` importing `AGENTS.md`. Every implementation in this repository selects FlightCheck automatically, before and after skill discovery. Ordinary questions and read-only reviews retain their normal entry points. `/develop-change` enters the same shared procedure. Its `disable-model-invocation: true` flag controls command invocation, not the root maintainer rule.

The root `.claude/skills/develop-change/SKILL.md` references the shared skill. The two `.claude/agents/workflow-*-reviewer.md` adapters retain the canonical reviewer criteria with `Read, Grep, Glob`. When canonical TOML roles change, update the Markdown adapters in the same change; `test_claude_support.py` checks parity. The example's wrapper uses source-layout paths. The installer generates destination-specific client files instead of copying that wrapper alone.

In a fresh session type `/` and verify `/develop-change` and both reviewer definitions. The `/agents` interface varies by version; inspect the effective definitions/tool inventories rather than assuming a particular wizard. Check parent/user/managed instructions and duplicate names for overrides. Restart after creating the first agent directory. Preserve existing policy when resolving conflicts. See [imports](https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools), [skills](https://code.claude.com/docs/en/skills), and [subagents](https://code.claude.com/docs/en/sub-agents). Discovery remains an observation to record, not a guarantee from file placement.

Run affected checks first, then the full suite with loopback permission:

```sh
git diff --check HEAD
"$trial_python" -B -m unittest discover -s tests -p test_claude_support.py -v
"$trial_python" -B -m unittest discover -s tests
```

Check untracked source whitespace too. Retain exact commands, native identities/outcomes, failures/skips and environment using the shared recorder. HTTP tests bind `127.0.0.1`; do not remove tests to accommodate a restricted client.

## Existing-project trial

Prepare the supplied [first flight](../examples/existing-project/docs/first-flight.md) from the clean pinned source:

```sh
"$trial_python" -B examples/existing-project/examples/first-flight/prepare.py \
  --project "$trial_area/project" --evidence "$trial_area/evidence" \
  --python "$trial_python" --default-branch main \
  --nit-tracker 'Private Claude trial notes; no provider writes'
cd "$trial_area/project"
printf '%s\n' '# Existing project policy' 'Keep ordinary questions outside a flight.' > AGENTS.md
printf '%s\n' '# Existing Claude policy' 'Preserve these instructions.' > CLAUDE.md
git add AGENTS.md CLAUDE.md
git -c user.name='Trial fixture' -c user.email=fixture@example.invalid \
  -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -m 'Existing fixture policy'
```

That commit is only in the disposable fixture. Retain the helper's original product archive, baseline, exact native witness, spec and original identity. Its emitted task JSON is a filled starting contract, not completed review. Choose a small new behavior, such as optional `lowercase=True` label normalization. Preserve the existing default behavior and `test_existing.py::test_normalization`; add `test_lowercase.py::test_lowercase` for lowercase/Unicode/empty text and invalid input. Before the first preflight, declare the genuine new criterion, native witness, original-product control and all three report artifacts using that task/request structure and the [bootstrap recipe](../examples/existing-project/examples/evidence-bootstrap/README.md). A compatibility control must pass on the original product; a new behavior's same-spec witness must fail there. Keep original product and test-overlay identities distinct.

Save the resolved project choices in `$trial_area/choices.json`, replacing these absolute paths with the values above:

```json
{
  "activation": "opt-in",
  "delivery": "Disposable local trial; no provider writes",
  "evidence_dir": "/absolute/trial-area/evidence",
  "python": "/absolute/trial-area/venv/bin/python",
  "default_branch": "main",
  "nit_tracker": "Private Claude trial notes; no provider writes",
  "policy_reference": "Existing fixture instructions and owner-selected trial",
  "checks": [{"name":"Native fixture tests","command":["/absolute/trial-area/venv/bin/python","-B","-m","pytest","-q"],"phase":"cheap"}]
}
```

```sh
"$trial_python" -B "$flightcheck_source/setup/install.py" inspect --target .
"$trial_python" -B "$flightcheck_source/setup/install.py" plan --target . --agent claude --config "$trial_area/choices.json"
"$trial_python" -B "$flightcheck_source/setup/install.py" apply --target . --agent claude --config "$trial_area/choices.json"
"$trial_python" -B .flightcheck/install.py verify --target .
claude
```

Expect `ready_for_client_probe`. Verify the complete `.flightcheck/`, `.claude/skills/` and `.claude/agents/` inventory without a second discovery task. Existing instruction text, settings and permissions must survive. Follow the [complete setup guide](../setup/README.md) for conflicts/source cleanliness failures. In this fresh adopter session ask an ordinary question first, then explicitly use `/develop-change` for the bounded task. Verify opt-in routing and both reviewer definitions; do not import the contributor checkout's automatic activation into the adopter.

## Effective review boundary

The controller owns execution, evidence, capture and card lifecycle. Each reviewer gets a separate context, the exact packet/diff and original evidence, without editing, native checks/services, providers, secrets, delegation or executable hooks. A declared tool list or verbal refusal is insufficient.

This is a candidate named-reviewer launch to **qualify on the installed version**, not a verified sandbox:

```sh
claude --agent workflow-code-reviewer --tools Read,Grep,Glob \
  --disallowedTools 'mcp__*' --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --settings '{"disableAllHooks":true}'
```

Use a separate `workflow-evidence-reviewer` session for Plan and final EVIDENCE. Inspect effective tools, settings, plugins and `/hooks`. Ordinary overrides cannot disable managed hooks; force-enabled plugin/SDK hooks may survive too. If executable hooks remain, retain the blocker. See [hook precedence](https://code.claude.com/docs/en/hooks#disable-or-remove-hooks).

Use synthetic canaries: one readable packet, a denied secret canary and unused source/evidence write targets. Configure narrow required-evidence access and a canary `Read` deny through the client's actual permission controls. Absolute rules use `//path`, not `/path`. Test effective rules and all available read/context paths; read rules are not an OS sandbox. If denial can be bypassed, retain the blocker or establish an independently verified host boundary. Do not grant a blanket home-directory read. See [permissions](https://code.claude.com/docs/en/permissions).

Ask each context to read the packet and attempt prohibited operations. Retain actual tool rejection/unavailability, unchanged write targets, denied canary access and unavailable execution/provider/delegation tools. Keep native transcripts. Controller-owned `capture_review.py` must retain the complete original final JSON before parsing; never retype or summarize it into evidence. Raw reviewer JSON and ordinary chat have no controller footer.

## Execution, repair and final verdict

Use `.flightcheck/scripts` and the private task. Finish setup/mutating hooks before freezing; bind explicit product/test/runtime inputs and a separate spec. Start with:

```sh
"$trial_python" -B .flightcheck/scripts/handoff.py preflight --task "$trial_area/evidence/task.json" --evidence-dir "$trial_area/evidence"
"$trial_python" -B .flightcheck/scripts/handoff.py challenge-brief --task "$trial_area/evidence/task.json"
```

Retain a real independent Plan proposal through `challenges --review ORIGINAL_CAPTURE`, map cases to witnesses and qualify controls before implementation. Record checks using the generated request's exact command, fingerprint, scope and artifacts with `capture_check.py`. Run cheap checks, explain why early CODE applies (this trial exercises both roles), obtain CODE, run remaining gates, then obtain separate EVIDENCE on the validated `review` packet.

Before every controller reply, use the installed `status-card/reply.py prepare` and `check` on its exact draft with complete stages/checks/links or explicit unavailable reasons. Proactively tell TUI users to open the browser card; retain one URL and its final footer through updates, approval pauses, blockers, repair/resume and final handoff. Observe ordinary chat/raw JSON remaining unaffected. Record host HTTP, browser reachability and actual browser rendering separately. Follow `.flightcheck/docs/status.md` for exact commands/schema, listener restoration and approved loopback forwarding with `--user-url`. An embedded browser is optional; a public listener is unnecessary.

Exercise these failures with fixture provider writes disabled:

| Probe | Expected refusal and recovery |
| --- | --- |
| `BROKEN_WITNESS`: violate the new behavior | Native witness fails. Restore the repair and retain identical-test before-failure/after-pass receipts. |
| missing/inaccessible evidence | Readiness stays false. Restore original bytes/access and revalidate; never invent a receipt. |
| failed required check | An older pass cannot authorize delivery. Repair and rerun through the recorder, preserving the failed attempt. |
| stale candidate/verdict | Change the candidate after approval; the old verdict cannot authorize delivery. Refresh bookkeeping, affected gates and review. |
| footer/listener failure | The exact-reply guard fails. Restore the same route, prepare current complete details and check the draft before replying. |

Recompute with `fingerprint.py candidate --root "$PWD"`, then use `handoff.py refresh --task ... --evidence-dir ... --candidate ID`. Run `resume` and `next-action --target final` with the same task/evidence arguments, execute its run/reuse/reproduce actions and ask again. Preserve frozen criteria/gates/baseline/witnesses. Retain an actual reviewer request across a restart and demonstrate that omission cannot erase it. Repaired proof needs fresh review; editing metadata cannot refresh an approval.

Capture native final messages with `capture_review.py --input ORIGINAL_FINAL_MESSAGE --evidence-dir EVIDENCE --kind review --validate`. Record actual requests, build `review`, obtain separate EVIDENCE and validate `verdict --review CAPTURE`. Structural validation is not approval. Preview is inapplicable to the non-UI product fixture, but its card is required. Stop at verified readiness without fixture provider writes.

## Observed host limitation

The implementation trial reached native discovery and read-only role probes, but the strict controller shell could not start inside the enclosing automation sandbox: `sandbox-exec: sandbox_apply: Operation not permitted` (exit 71), including for `pwd`. No unsandboxed retry was used. Run the remaining selected-flight trial in a fresh local Claude TUI on a host where the configured command sandbox can start; keep its required boundary and record any equivalent enforced isolation. The existing Python/HTTP and read-only probes do not clear this blocker. See the [partial report](claude-trial-report.md).

## Report and contribute

Complete the [trial report](claude-trial-report.md) with source/candidate identities, versions/model/settings, commands, native outcomes, boundary and all-phase observations, controls/repair proof and the current-candidate final verdict. Keep durable private originals outside the checkout; publish only an approved sanitized summary. Another fresh session must reproduce the committed procedure. Keep unavailable combinations untested and #14 open until successful native qualification is reviewed and accepted.

Rerun affected Codex/adopter checks and the full suite on the final contribution candidate. Include the report and maintainer-accessible evidence references in an authorized PR. Creation and merge need their respective delivery grants; a successful trial or collaborator access does not expand licensing/contribution rights. Follow the current [contribution](../CONTRIBUTING.md) and [licensing](licensing.md) policies.
