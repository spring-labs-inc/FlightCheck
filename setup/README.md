# Install FlightCheck in an existing project

Use the complete installation flow below. It includes the shared workflow, all six evidence tools, the browser status card and the selected client adapter. A documentation-only installation is incomplete. Preserve existing project policy; record a concrete blocker or an explicit owner-approved exclusion rather than silently dropping a component.

The installer uses only Python's standard library and Git. Receipt and card tools require **Python 3.9+ on POSIX**. They can support projects using other languages. No PyPI release, plugin, account, global configuration change or new CI service is needed.

## Choose your coding surface

Use the same installation and configuration flow for all four surfaces. Select the `codex` adapter for Codex CLI or Codex Desktop, the `claude` adapter for Claude Desktop or Claude Code, or `both` when the project uses both families. The [skills and reviewers guide](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/skills-and-reviewers.md) describes the installed components.

| Surface | Adapter | Start or resume a flight | Setup checks |
| --- | --- | --- | --- |
| [Codex CLI](#codex-cli) | `codex` | `$develop-change` | Project instructions, skill discovery, reviewer boundaries, and browser route. |
| [Codex Desktop](#codex-desktop) | `codex` | Select `develop-change` or use `$develop-change` | Selected checkout and execution host, skill discovery, reviewer boundaries, and browser route. |
| [Claude Desktop](#claude-desktop) | `claude` | `/develop-change` in the Code tab | Project folder, desktop runtime version, skill discovery, reviewer boundaries, and browser route. |
| [Claude Code](#claude-code) | `claude` | `/develop-change` | Project instructions, skill discovery, reviewer boundaries, and browser route. |

Run installation from a normal terminal with access to the target checkout. Then start a fresh session in the chosen surface and complete [client verification](#6-verify-the-client-in-a-fresh-session). Record the exact client version, execution host, and observed results for each surface tested. An adapter installed for one family does not establish qualification of every surface in that family.

### Codex CLI

After installation, open the configured repository in your terminal and run `codex`. Select `$develop-change` for a small task. Confirm that the repository's instructions, skill, and both reviewer definitions are discovered. Open the printed status-card link in your browser and complete the common verification steps. [Official CLI setup](https://learn.chatgpt.com/docs/cli)

### Codex Desktop

Open the configured repository in Codex Desktop and start a fresh chat in the intended checkout. Select the `develop-change` skill. When using a worktree or remote host, verify that instructions and checks use that checkout and that the browser can reach the published card. Verify effective reviewer access in that desktop session. [Official skill discovery](https://learn.chatgpt.com/docs/build-skills)

### Claude Desktop

Open the configured project in a local session in Claude Desktop's Code tab and select `/develop-change`. Verify project instructions, skill discovery, and the effective tools and evidence access of both reviewer roles. Record the desktop app's version and its Code runtime version; the bundled runtime can differ from the terminal's `claude` command. Complete browser and repair/resume checks in this surface. [Official desktop setup](https://code.claude.com/docs/en/desktop)

### Claude Code

After installation, run `claude` from the configured repository and select `/develop-change`. Inspect the loaded instructions, available skill, reviewer definitions, and effective permission/hook state. Complete the common verification steps and use the [qualification procedure](#claude-code-qualification-procedure) for the retained native trial. [Official CLI setup](https://code.claude.com/docs/en/quickstart)

The [Claude qualification record](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/claude-trial-status.json) currently reports a partial Claude Code trial. Record desktop observations separately. Keep native qualification open when a required client capability or execution boundary is unavailable.

## 1. Obtain and pin the source

Run these commands outside the adopting repository, choosing an unused destination:

```sh
git clone https://github.com/spring-labs-inc/FlightCheck.git /path/to/FlightCheck
git -C /path/to/FlightCheck rev-parse HEAD
git -C /path/to/FlightCheck checkout --detach FULL_COMMIT_FROM_PREVIOUS_COMMAND
git -C /path/to/FlightCheck status --porcelain=v1 --untracked-files=all
```

Expected: a full immutable commit ID, a detached checkout and no status output. Record that ID with the setup. The source must stay clean. The installer records the commit, Git tree, manifest digest and each component's source/installed digest. New releases are adopted deliberately; the setup prompt does not permanently pin an old version.

Read the license accompanying that revision. Current FlightCheck uses FSL-1.1-MIT, permitting ordinary internal organizational commercial use without paid seats. Each version gains additional MIT rights after two years. Keep the version's license and notices with copied material; retain the adopting project's own license. Historical versions keep their historical terms.

## 2. Inspect before changing the project

From the adopting project's Git root:

```sh
python3 -B /path/to/FlightCheck/setup/install.py inspect --target .
```

Expected: JSON listing detected instruction/configuration files, a preferred Python interpreter, a default branch when `origin/HEAD` is known, safe activation/delivery defaults, and required configuration fields. This command writes nothing and does not run project checks.

Read the existing instructions and development commands. Detection is a starting point, not permission to replace policy. In particular, an existing `CLAUDE.md` may hold different policy from `AGENTS.md`; the installer appends a bounded FlightCheck section instead of replacing either file or redirecting it to the other.

Choose `codex`, `claude`, or `both` explicitly. Only that client's project-local skill and reviewer definitions are installed. Claude definitions are generated from the canonical reviewer instructions with `tools: Read, Grep, Glob`; actual effective boundaries still need the fresh-session probe below.

## 3. Resolve the project choices together

Reuse decisions already present in project policy. Ask the owner about only the unresolved items, in one batch:

- **Activation:** opt-in is the default. Use `default-for-coding` only with a recorded explicit owner decision. Ordinary questions remain outside the workflow.
- **Delivery:** default to no provider writes without approval. Record the exact grant if commits, pushes, PR creation, nit issues or merge are authorized. A passing verdict does not expand that grant.
- **Evidence:** an absolute, owner-only directory outside the checkout, and any narrowly scoped client read access needed by reviewers. No global read permission is installed automatically.
- **Checks and interpreter:** the project's actual non-mutating commands, selected Python and cheap/authoritative phases. Run formatters/autofix separately before freezing a candidate; the installer does not run those commands.
- **Default branch and nit tracker:** use the detected branch when available; otherwise resolve it explicitly. Record the actual tracker and any permissions needed to write there.

### Use a short configuration interview

When an AI assistant helps with setup, ask it to inspect the repository first and present a short set of suggested answers. Each suggestion should identify its source and let the owner confirm or correct it. Reuse existing confirmed configuration and ask only about missing, ambiguous, or changed values.

| Project context | Suggested source | What to confirm |
| --- | --- | --- |
| Repository, issue tracker, and board | Selected Git remote, existing project instructions, and accessible GitHub project metadata | The exact repository and board URL, especially when several boards are available. |
| Documentation and runbooks | Existing documentation index and project resource pointers | Which paths cover architecture, development, operations, and the task's component. |
| Application logs | Existing service runbooks and documented log lookup commands | The relevant service and approved lookup route when the task needs logs. |
| Checks and previews | Existing scripts, CI configuration, and development instructions | The actual commands, project runtime, applicable checks, and preview route. |
| Evidence and reviewer access | Existing FlightCheck configuration and project access policy | The private evidence location and the narrow access required for review. |
| Activation and delivery | Existing owner-approved project policy | Any unresolved explicit grant for workflow activation, commits, pushes, PRs, or merging. |

Validate required paths and configuration, and use permitted read-only probes to confirm repository and board access. An inferred value remains a suggestion until confirmed. Discovery does not authorize provider writes, permission changes, or installation of the adopting project's dependencies.

Save reusable documentation, board, and log lookup pointers in a project-owned resource index, using the [resource-index example](../examples/existing-project/docs/project-resources.md) as a reference. Keep shared pointers repository-relative where possible and host-specific log locations in private local configuration. Use the existing credential store for credentials.

At the first selected flight, consult the saved configuration and resource index. Resolve missing required information before freezing the flight. On later flights and resumes, reuse confirmed answers and revisit affected values when required resources or project policy have changed.

These questions guide the assistant's configuration work. The current installer consumes the reviewed JSON configuration below; a built-in first-flight interview is proposed in [#66](https://github.com/spring-labs-inc/FlightCheck/issues/66).

Save the resulting configuration outside the source checkout, for example `/private/project-flightcheck.json`:

```json
{
  "activation": "opt-in",
  "delivery": "No provider writes without owner approval",
  "evidence_dir": "/absolute/private/project-evidence",
  "python": "/absolute/project/.venv/bin/python",
  "default_branch": "trunk",
  "nit_tracker": "Project GitHub issues; owner approval required to create",
  "policy_reference": "Existing project development guide and owner setup decision",
  "checks": [
    {
      "name": "Project tests",
      "command": ["/absolute/project/.venv/bin/python", "-B", "-m", "pytest", "-q"],
      "phase": "authoritative"
    }
  ]
}
```

These are example paths, a branch name and a test command: replace them with the detected project values. The selected interpreter needs the project's dependencies for its own checks. The installer itself does not install dependencies. For default-for-coding, also supply `"activation_reference": "Actual owner decision reference"`; relying on the model to select a skill automatically is insufficient.

## 4. Preview and apply the complete installation

```sh
python3 -B /path/to/FlightCheck/setup/install.py plan --target . --agent claude --config /private/project-flightcheck.json
python3 -B /path/to/FlightCheck/setup/install.py apply --target . --agent claude --config /private/project-flightcheck.json
```

Expected from `plan`: `status: planned`, source identity and a complete list of create/update/unchanged operations, with no writes. Inspect the plan before applying. Unresolved configuration, modified managed files, collisions with existing files and symlink destinations produce `status: incomplete` with a nonzero exit.

Expected from successful `apply`: `status: ready_for_client_probe`, component count, source identity and passed local Python-tool/card-HTTP checks. It installs every selected component, appends marked instruction sections, creates a private evidence directory when needed, and runs a bounded synthetic card check. The test listener is stopped afterward. Runtime failure remains incomplete and is never a completed client qualification; correct the reported environment problem and rerun verification.

Interpreter detection has a 10-second timeout. The combined tool/card smoke check has a 15-second overall deadline, followed by at most seven seconds for process cleanup. A listener that stalls or trickles data cannot extend the verification indefinitely.

The complete source-to-destination inventory is [`manifest.json`](manifest.json). Shared assets live under `.flightcheck/`, with client discovery files at `.agents/skills/` and `.codex/agents/` for Codex, or `.claude/skills/` and `.claude/agents/` for Claude. The manifest is also copied to `.flightcheck/manifest.json`. No hooks, global settings, credentials or provider writes are installed/enabled by this flow.

Existing instructions outside the `FlightCheck:begin`/`FlightCheck:end` markers remain intact. Existing client settings are untouched. Repeating the same plan/apply is idempotent. A pristine previously managed file can be updated by an explicit plan/apply from a new clean pinned source; modifications to managed content cause a conflict instead of being overwritten. Changing client selection requires explicit reconciliation. Review changes with `git diff` and inspect new files too; the installer does not stage or commit them.

## 5. Verify from the installed project

```sh
python3 -B .flightcheck/install.py verify --target .
```

Expected: `status: ready_for_client_probe`. Verification checks the entire required inventory and recorded hashes, validates project configuration/interpreter, invokes the real installed tools, publishes a synthetic nine-stage snapshot in private scratch, and tests its real loopback HTTP route and printed task link. Missing or modified required components return incomplete and a nonzero exit. This works without keeping the original source checkout on disk.

`project.json` records choices; it does not create per-flight task contracts, fingerprints, baseline reports or reviewer verdicts. Configure those using the installed `.flightcheck/docs/development-workflow.md`. Reusable language-specific evidence adapters are separate work in #57.

## 6. Verify the client in a fresh session

Use the surface-specific setup above and retain a separate qualification record for each client/runtime combination. The detailed [Claude Code qualification procedure](#claude-code-qualification-procedure) follows the common installation steps.

Installation and HTTP tests do not prove that a client loaded its instructions, restricted reviewer tools or rendered the card. Start a fresh Claude/Codex session in the target checkout, especially after creating the first agent definitions. Use the installed client's discovery tools to inspect effective instructions, skill and role availability.

1. Ask an ordinary question; it must stay outside a flight. Select a small task through `$develop-change` (Codex) or `/develop-change` (Claude), or verify the explicitly approved default-for-coding route.
2. Probe each reviewer with synthetic canaries: required packet/evidence reads must work and writes, secrets, native check execution and provider tools must be unavailable. Inspect active hook sources too. Preserve existing settings; request only the narrow missing evidence access the project requires. Keep review pending if the boundary cannot be enforced.
3. Follow `.flightcheck/docs/status.md` to prepare a real task card before each controller reply and check the exact draft with `.flightcheck/status-card/reply.py check --task TASK_ID --phase update --reply-file /private/reply.txt`. Test all phases, including approval pauses, blockers and repair/resume. Ordinary chat and raw reviewer JSON must remain unchanged. Do not claim a Stop hook intercepts intermediate or interrupted replies without an observed native capability test. A TUI can keep using the terminal while the user opens the printed card URL in a browser. For SSH/remote checkouts, use approved localhost forwarding; do not expose the listener to the network.
4. Record host HTTP publication and browser reachability/rendering separately. Keep one task URL on resume. Test a stopped listener and a changed candidate; an old verdict must become Pending.
5. Rehearse the documented handoff path before provider writes. Label any mock reviewer output as a plumbing test; it does not establish real approval.

Record tested client/runtime versions, observed capabilities and outstanding blockers with the setup. Full native Claude end-to-end qualification is tracked in #14; installing the adapter alone does not complete it. The portable per-reply guard and TUI browser guidance are included; native event interception still needs a live capability probe. Card-completeness policy remains #55.

## Troubleshooting

- **Dirty source:** obtain a clean pinned source checkout. Do not discard unrelated work to make it clean.
- **Conflict:** inspect the reported file and existing installation record. Preserve owner edits and reconcile deliberately; there is no force-overwrite flag.
- **Runtime or loopback failure:** use the selected project interpreter and a host that allows `127.0.0.1` binds. Run sibling-import scripts by path with `-B`, not `-I`. Verify again after correcting the environment.
- **Missing default branch:** inspect the remote's actual default branch or ask the owner. Do not assume `main`.
- **Client probe fails:** keep setup qualification pending and record the actual boundary/discovery error. Fresh-session requirements and supported capabilities can vary by client version.

## Claude Code qualification procedure

Use this guide for a contributor checkout or a real existing-project trial. The installer supplies Claude adapters and the browser card. [Qualification status](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/claude-trial-status.json) distinguishes observations from pending checks; Python/HTTP success alone does not establish native Claude support. Keep #14 open until a real trial is reviewed and accepted.

### Contributor setup

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

Record the clean source revision, OS, interpreter and dependency versions. Resolve a missing Git identity locally before authorized commits. Public cloning or a fork does not grant contribution rights: [CONTRIBUTING.md](https://github.com/spring-labs-inc/FlightCheck/blob/main/CONTRIBUTING.md) currently restricts outside code intake and PR creation. GitHub authentication is needed for authorized delivery, not the local trial.

Install Claude separately using the [official quickstart](https://code.claude.com/docs/en/quickstart). On macOS with Homebrew:

```sh
brew install --cask claude-code
claude auth login
claude auth status --text
claude --version
claude --help
```

Use your own permitted account; record the authentication method without credentials/account identifiers. Claude Code **2.1.311** was observed on the implementation host. That version number alone is not a supported-client qualification. Check commands against the installed help and [CLI reference](https://code.claude.com/docs/en/cli-reference). No global setting changes or permission bypass are required.

### Instruction and reviewer discovery

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

### Existing-project trial

Prepare the supplied [first flight](https://github.com/spring-labs-inc/FlightCheck/blob/main/examples/existing-project/docs/first-flight.md) from the clean pinned source:

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

That commit is only in the disposable fixture. Retain the helper's original product archive, baseline, exact native witness, spec and original identity. Its emitted task JSON is a filled starting contract, not completed review. Choose a small new behavior, such as optional `lowercase=True` label normalization. Preserve the existing default behavior and `test_existing.py::test_normalization`; add `test_lowercase.py::test_lowercase` for lowercase/Unicode/empty text and invalid input. Before the first preflight, declare the genuine new criterion, native witness, original-product control and all three report artifacts using that task/request structure and the [bootstrap recipe](https://github.com/spring-labs-inc/FlightCheck/blob/main/examples/existing-project/examples/evidence-bootstrap/README.md). A compatibility control must pass on the original product; a new behavior's same-spec witness must fail there. Keep original product and test-overlay identities distinct.

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

Expect `ready_for_client_probe`. Verify the complete `.flightcheck/`, `.claude/skills/` and `.claude/agents/` inventory without a second discovery task. Existing instruction text, settings and permissions must survive. Follow the [complete setup guide](#1-obtain-and-pin-the-source) for conflicts/source cleanliness failures. In this fresh adopter session ask an ordinary question first, then explicitly use `/develop-change` for the bounded task. Verify opt-in routing and both reviewer definitions; do not import the contributor checkout's automatic activation into the adopter.

### Effective review boundary

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

### Execution, repair and final verdict

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

### Observed host limitation

The implementation trial reached native discovery and read-only role probes, but the strict controller shell could not start inside the enclosing automation sandbox: `sandbox-exec: sandbox_apply: Operation not permitted` (exit 71), including for `pwd`. No unsandboxed retry was used. Run the remaining selected-flight trial in a fresh local Claude TUI on a host where the configured command sandbox can start; keep its required boundary and record any equivalent enforced isolation. The existing Python/HTTP and read-only probes do not clear this blocker. See the [partial report](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/claude-trial-report.md).

### Report and contribute

Complete the [trial report](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/claude-trial-report.md) with source/candidate identities, versions/model/settings, commands, native outcomes, boundary and all-phase observations, controls/repair proof and the current-candidate final verdict. Keep durable private originals outside the checkout; publish only an approved sanitized summary. Another fresh session must reproduce the committed procedure. Keep unavailable combinations untested and #14 open until successful native qualification is reviewed and accepted.

Rerun affected Codex/adopter checks and the full suite on the final contribution candidate. Include the report and maintainer-accessible evidence references in an authorized PR. Creation and merge need their respective delivery grants; a successful trial or collaborator access does not expand licensing/contribution rights. Follow the current [contribution](https://github.com/spring-labs-inc/FlightCheck/blob/main/CONTRIBUTING.md) and [licensing](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/licensing.md) policies.
