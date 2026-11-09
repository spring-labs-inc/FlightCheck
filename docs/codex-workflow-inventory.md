# Codex workflow inventory for Spring

Audited November 8, 2026 for [SpringDev #1][issue]. This inventory identifies where SpringDev can put workflow guidance, executable checks, and permission boundaries in the Codex setup used for Spring. [SpringDev #8][devguide-audit] owns the separate review of which DevGuide practices to adopt. [SpringDev #2][cutover] reconciles those choices with the existing Spring migration, and [SpringDev #4][codex-workflow] applies the agreed workflow to Spring.

## Baselines and evidence

| Surface | Evidence |
| --- | --- |
| Published Spring | GitHub `main` and the local `origin/main` both resolved to `60da2477186bac9e04e369e47a0f8d0087859313`. Repository links below point to that snapshot. |
| Primary Spring checkout | `/Volumes/exdsk/Spring` was on `development` at `43ec92acc57de5ba3575a3cf111d2b6f982630b8` with local changes. The instruction files, three Codex skills, the GitHub read rules, and the FlightCheck adapter differ locally. Treat those edits as a separate overlay when reconciling policy. |
| Spring #454 candidate | The copied candidate under `/Volumes/exdsk/Spring-issue-454-devguide-migration` is readable. Its Git pointer still targets the former volume, so its branch, diff, and effective Codex setup could not be verified through Git. On disk it has DevGuide-oriented instructions, `.devguide/checks.json` and `source-pin.json`, the same set of 11 Codex skill paths, and an empty Codex hook map. The recorded shadow results belong to [Spring #454][spring454]. |
| SpringDev checkout | `/Volumes/exdsk/SpringDev` at `d0c05d8286498a3cbe070a16797ca2ee45ce0260` had only `README.md` tracked at the start of the audit. Spring is a separate checkout. |
| Execution host | Shell and session run on mac-mini. airJoker is the SSH client. The active session and standalone CLI report `0.167.0`. The installed ChatGPT app reports `26.1103.41825` and bundles Codex CLI `0.167.0-alpha.3.2`. The existence of that bundled binary does not identify which binary a separate Spring desktop chat uses. |

**Evidence terms.** *Observed* means inspected on disk, in Git, or via the GitHub API. *Configured* means a file declares the behavior. *Probed* means a named read-only command tested a specific property. A declared hook, skill, or reviewer is not evidence that a live Spring chat loaded or ran it.

## Codex config layers and when to use them

For ordinary Codex configuration, the table runs from highest to lowest precedence. Project config layers are scoped to the Git root and working-directory chain and require trust. Launch context, trust, skills, instructions, hooks, command rules, and managed restrictions have their own selection or merge rules. [OpenAI config basics][config] · [Advanced configuration][advanced]

| Layer | When to use it for SpringDev | Observed or applicable here |
| --- | --- | --- |
| CLI flags and `--config` | Use for a specific run or a controlled probe. Record nondefault launch settings with evidence when they affect reproducibility. | The SpringDev chat has a session-supplied workspace and permission boundary. No separate Spring CLI invocation was inspected. |
| Trusted `.codex/config.toml` from the project root to the working directory | Use for Codex-specific defaults that should travel with Spring. A deeper file wins on a conflicting key. Introduce a deeper layer only when a subtree has a distinct operational need. | No root or nested project config found in published Spring, the primary checkout, or the copied candidate. Spring has separate `.codex` files for roles, rules, and hooks. |
| Selected `$CODEX_HOME/<profile>.config.toml` | Use for a named developer-side mode with deliberate opt-in, such as a diagnostic profile. Keep repository requirements reproducible without it. | No named profile files found in the active Codex home. |
| User `$CODEX_HOME/config.toml` | Use for personal model and effort defaults, notifications, developer-specific MCP, and per-path project trust. Keep shared Spring workflow guidance in the repo. | Present on mac-mini. The file declares workspace-write and on-request approvals, along with user model, UI, notification, plugin, MCP, and trust settings. No instruction fallback, byte-limit override, profile selection, `[agents]` defaults, or inline executable hook was found. |
| Cloud-managed `config.toml` defaults | Use for organization-wide starting preferences where the signed-in workspace provides them. | Workspace-delivered values were not visible from this audit. |
| System `/etc/codex/config.toml` | Use for an administrator-owned machine baseline shared by users of a managed host. | File absent at the documented path. |
| Built-in defaults | Use unless the project can explain a reproducible need for an override. Confirm behavior on the runtime that will execute the workflow. | CLI and desktop runtime versions recorded above. |

**Managed requirements and permissions.** A system `requirements.toml`, workspace Agent Security requirements, legacy managed-device policy, and macOS MDM can constrain otherwise valid config. Their precedence is separate from the table, and some fields have their own merge rules. The conventional `/etc/codex/requirements.toml`, `/etc/codex/managed_config.toml`, and inspected macOS managed preference paths were absent. This SpringDev chat nevertheless received a managed permission profile with workspace writes and restricted command networking. Treat approval, sandbox, and organization policy as execution boundaries. Use admin-managed requirements for organization policy and owner-approved host permission settings for a particular checkout. [OpenAI managed configuration][managed]

**Trust after relocation.** The user config has exact trust records for SpringDev and the former Spring and migration paths under `/Volumes/SANDISK SSD`. It has no exact entries for the corresponding Spring paths under `/Volumes/exdsk` or their inspected parent paths. One Spring-related hook trust record exists, but it was not matched to a live hook execution at the new path. Verify the actual Spring launch path, effective project trust, and hook hash trust separately in a fresh session before relying on project rules or hooks. Keep repo config and local trust decisions separate. [Advanced configuration][advanced] · [Codex hooks][hooks]

**Runtime and launch context.** CLI working directory and flags, desktop primary folder and worktree selection, IDE workspace, and remote app-server host determine what Codex can discover. For Spring implementation chats, select Spring as the primary repository or launch inside the intended Spring worktree. Use SpringDev as the primary repository for planning and this audit. Desktop preferences and connected providers or plugins can change which tools are available. Record the effective cwd, runtime, and nonsecret config sources for the pilot. [Projects and chats][projects] · [Codex worktrees][worktrees]

## Instructions and referenced Markdown

Codex checks its home for a nonempty `AGENTS.override.md` or `AGENTS.md`, then walks the project root-to-cwd chain. At each directory it uses at most one file, preferring `AGENTS.override.md`, then `AGENTS.md`, then configured fallback names. The documented default project instruction budget is 32 KiB. Start a fresh session to verify what was loaded after editing. Linked docs are references the agent opens when relevant. Skill frontmatter is discoverable separately from the full skill body. [Instruction discovery][agents-md] · [Skill discovery][skills]

| Source | Current activation and content | Recommended SpringDev use |
| --- | --- | --- |
| Global `AGENTS.md` and overrides | mac-mini's `$CODEX_HOME/AGENTS.md` is empty. No global override was found. | Keep genuinely personal, cross-project guidance here. |
| Spring root `AGENTS.md` | Startup project guidance on safe command tiers, owner-facing UI, test isolation, FlightCheck, architecture, and documentation. The published file is 271 lines and about 20 KiB. No nested `AGENTS.md`, override, or configured fallback name was found in the inspected Spring setup. The local overlay also describes explicitly selected DevGuide work. | Make it the shared, harness-neutral entry point. Keep durable project rules, explicit workflow activation, safe command boundaries, review and owner checkpoints, and links to task-specific procedures. Add nested files only for genuine subtree-specific rules. [Spring AGENTS.md][spring-agents] |
| Spring root `CLAUDE.md` | The published file has 1,022 lines and about 72 KiB. Codex reaches it through references from `AGENTS.md`, skills, and runbooks. It currently carries substantive verification, application access, owner decisions, execution policy, Git/workspace, UI, and documentation rules. | Extract the agreed shared rules into `AGENTS.md` and the appropriate Spring docs or checks. The final `CLAUDE.md` is one line containing `@AGENTS.md`. Claude Code documents that import as a way to share the same instructions across tools. [Spring CLAUDE.md][spring-claude] · [Claude Code instruction imports][claude-import] |
| README and architecture docs | Spring `README.md` is a human setup and navigation entry. Root guidance links to architecture invariants, test environment and network exposure, and the FlightCheck package ADR. The UI workflow links to the style guide and VisualQA. | Keep setup and orientation in README, product constraints in architecture and style docs, and a short pointer from `AGENTS.md` where a rule is load-bearing. [Spring README][spring-readme] · [Invariants][invariants] · [UI style guide][ui-style] · [Test environment][test-env] · [Network exposure][network] |
| Runbooks and AI references | `docs/ai/FlightCheck.md` is the consumer workflow reference. `subagents.md` and `slash-commands.md` describe mostly Claude definitions. Staging, release versioning, feature flags, documentation maintenance, the roadmap, recent changes, and the deprecation queue are opened through links or relevant skills. The isolated Claude worker runbook describes a separate harness. | Move agreed reusable detail into small task-focused docs. Retarget links and section references to their new owners. Keep historical records discoverable and label their scope. [FlightCheck integration][flightcheck] · [Subagent catalog][review-catalog] · [Command catalog][command-catalog] · [Documentation maintenance][doc-maintenance] |
| Session prompt, issue brief, and memories | The user's request and linked issue select the task and scope. Host-supplied instructions and available tools affect this chat. Personal history and memory contents were outside the inspected surfaces. | Use current instructions for task scope and owner decisions. Put recurring Spring policy in `AGENTS.md`, reusable steps in skills, and durable evidence in project-native output. |

### Spring's Codex skills and reviewer roles

The published and primary Spring checkouts each have 11 `.agents/skills/*/SKILL.md` files. These are repo-scoped skills with explicit invocation and description-based discovery where enabled. No additional per-skill metadata was found in the published tree. Six `source-command-*` skills parallel the older Claude command catalog, and the other five have counterparts in `.claude/skills`. Codex discovers its `.agents/skills` copies through the repository. Claude files are source or reference material when linked. [Codex skill catalog][spring-skills] · [Legacy command catalog][command-catalog]

| Codex skill | Trigger and current purpose | Recommendation |
| --- | --- | --- |
| `source-command-grill` | Adversarial pre-ship review of staging and failure risks | Keep the useful prompts in one review procedure and check for overlap with the early independent code review. |
| `source-command-precommit-review` | Pre-commit readiness and review handoff | Adapt around current check and review evidence. Retarget its `CLAUDE.md` references. |
| `source-command-release-candidate` | Release or staging readiness | Keep as a release-specific advisory procedure. |
| `source-command-review-changes` | Review the uncommitted diff for risk, tests, docs, and architecture | Reuse checks that add value to independent code review and consolidate repeated guidance. |
| `source-command-techdebt` | End-of-session debt inventory | Keep separate from the default implementation workflow and from authority to make follow-up edits. |
| `source-command-verify-and-fix` | Interactive FlightCheck run, repair, and review | Adapt the chosen repair loop and converge with `spring-verify` once the parity gates are defined. |
| `spring-verify` | Pre-commit verification, offline tests, UI gate, and handoff | Reuse as the main verification skill backed by Spring-owned commands. Replace FlightCheck-specific entry points after cutover. |
| `spring-docs-update` | Changelog, deprecation queue, and docs placement | Keep as an on-demand maintenance procedure and link to the shared documentation policy. |
| `spring-phase-status` | Current work, phase, gates, or resume status | Adapt to report current evidence and owner action. Keep project status distinct from implementation authority. |
| `spring-pr` | Prepare or open a pull request | Adapt to the agreed branch and authorization policy. Reconcile published fixed branch guidance with the local overlay's selected-flight routing. |
| `spring-roadmap` | Roadmap, shipped phases, or what is next | Keep as navigation to the roadmap and board. |

Project roles `build-validator`, `code-architect`, and `staff-reviewer` live under `.codex/agents/`. Their TOML files define descriptions and review instructions, with no role-specific model or effort settings. They are advisory role definitions that apply when invoked. The installed FlightCheck adapter separately names `.claude/agents/flightcheck-reviewer.md` and expects its structured findings submission. For SpringDev, extract a portable review brief and evidence format, then use Codex role files for invocation and role-specific settings. Preserve the distinction between independent code review, independent evidence review, and release advice. An instruction to act read-only is separate from the runtime permissions inherited by a role. [Spring Codex roles][spring-roles] · [FlightCheck adapter][adapter] · [Codex custom agents][subagents]

Personal skills belong in user scope and machine-wide skills in admin scope. mac-mini has bundled system skills. No personal `~/.agents/skills` or admin `/etc/codex/skills` directory was found. The current host also supplies plugin skills. Keep Spring verification and review entry points in repo-scoped skills so they travel with the checkout. [Codex skill locations][skills]

## Hooks, triggers, and checks

| Surface | Trigger and target | Observed behavior and recommendation |
| --- | --- | --- |
| `.codex/hooks.json` | Spring's published and primary checkout declare `PermissionRequest`, with no matcher, a 10-second timeout, and target `.venv/bin/flightcheck-permission-hook`. Codex raises this event when it is about to request approval. | Spring documents this handler as logging-only. Live firing on the moved checkout was unverified. The copied #454 candidate declares no handlers. Adopt a hook only for a demonstrated event-based need with narrow, observable behavior. Ordinary workflow activation and owner decisions belong in instructions and the session. [Spring hook][spring-hook] · [Codex hook events][hooks] |
| User, managed, inline, and plugin hooks | Codex can load event handlers alongside active config, from plugin manifests, and through managed policy. Matching handlers can coexist. Hook trust and event support apply separately. | No user `hooks.json` or inline executable hook found. User config holds trust state and a separate notification setting. No Spring workflow dependency on the notification or a plugin hook was identified. Leave user notification preferences in user scope and confirm effective hook sources during rollout. [Codex hooks][hooks] |
| `.codex/rules/spring-github-reads.rules` and user `rules/default.rules` | Codex evaluates applicable argument prefixes for execution outside the sandbox. The most restrictive matching decision wins. | Published Spring defines five narrow allow prefixes covering Spring issue list, development-to-main PR list, and project #1 view, fields, and items. The local file has seven, adding a one-issue list and pinned issue #454 lookup, and broadening the PR list selectors. A separate user rule file exists. Keep shared exceptions in trusted repo rules, evaluate them alongside user and managed rules, and require parser-rejection tests before copying a prefix. [Spring GitHub rules][spring-rules] · [Codex command rules][rules] |
| `.flightcheck/adapter.json`, installed pin, and bootstrap | A selected FlightCheck run uses gate applicability and relevant-input rules. The offline pytest bootstrap enforces test-environment and FlightCheck dependency constraints. | The eight published gates are lint, docs, agent policy, FlightCheck policy, focused pytest, full offline pytest, VisualQA pytest, and the separate VisualQA findings/freshness check. The adapter, pinned package, evidence, and review CLI supply orchestration. Carry Spring commands, applicability, test isolation, and evidence semantics into [SpringDev #3][verification]. Keep the VisualQA producer and its findings reader in Spring. [Adapter][adapter] · [Consumer contract][flightcheck] · [Package ADR][flightcheck-adr] |
| `scripts/check_agent_policy.py` and `scripts/check_docs.py` | Run through the declared verification route or directly as documented. Policy tests consume the harness files, and docs checks verify links and command conventions. | Keep objective checks in scripts and native tests. The current policy checker depends on FlightCheck and checks both Codex and Claude surfaces. Adjust the expected policy and doc anchors alongside the migration. [Agent policy checker][agent-checker] · [Docs checker][docs-checker] |
| Git hooks and repository scripts | Git can invoke a configured hook at its lifecycle event. Spring also has explicit setup, release, and deployment scripts. | No `core.hooksPath` override, tracked hook manager config, or executable non-sample hook was found in the primary checkout. Treat scripts as explicit entry points with the Spring command boundary. Use repo checks for required validation so it is repeatable in any worktree. |
| GitHub Actions, branch rules, and webhooks | These can trigger on push or PR, independently of any agent. | GitHub reported zero Spring Actions workflows, no active ruleset rules for `main` or `development`, `main` marked unprotected, and no repository webhooks. This is a dated observation. Recheck actual provider requirements before the pilot or delivery. |
| GitHub project automations | Project workflows react to item and issue events. Enabled Spring project #1 workflows include auto-add, sub-issue addition, auto-close, item added, and item closed. SpringDev project #2 also has enabled PR-linked and PR-merged workflows. | Keep tracking and product automation separate from Codex activation. Verify board behavior before automating issue close or landing. [Spring project][spring-board] · [SpringDev project][springdev-board] |
| Desktop worktree setup, actions, and scheduled tasks | Desktop environment setup can run on creation of an app-managed worktree. Actions run on explicit selection. Scheduled tasks run from their saved prompt and context on the selected schedule. | No Spring `.codex/environments/` or `.worktreeinclude` was found in the primary or published tree. App-only action settings and Scheduled entries were not verified. Consider explicit actions for convenient Spring commands and a worktree setup script only for repeatable, secret-free setup. Keep scheduled work separate from normal workflow activation. [Local environments][environments] · [Scheduled tasks][scheduled] |
| MCP, plugins, cloud, IDE, and programmatic launches | Config, plugin activation, or a specific client launch supplies tools, settings, and context. The GitHub integration can also expose review or delegation triggers on supported deployments. | The user config declares Node and computer-use MCP servers and enabled plugins. There is no repo MCP declaration or evidenced dependency for Spring verification. Spring's instructions limit application access. Spring desktop/IDE-specific overrides, cloud settings, and external GitHub integration state were not verified. Keep the default workflow on repo files and Spring's native tools, with any selected integration documented separately. [Codex customization][customization] · [Spring application boundary][spring-claude] |

### Read-rule probe

`codex execpolicy check` matched Spring's canonical project-view command against both the published and local rule files. The pinned #454 issue view matched only the local file. A representative issue edit matched neither. An extra positional token still matched the Codex prefix, and the installed `gh` parser rejected it before a request under the offline proxy probe. This verifies the tested rule and parser behavior separately. It does not establish live project trust or cover every input shape. [Spring rule tests][agent-tests] · [Codex command rules][rules]

## Spring migration requirements

1. **Extract shared policy before reducing `CLAUDE.md`.** Preserve the owner-approved Spring rules for secret-free and user-run commands, application access, product and trading invariants, test isolation, owner-facing previews, human decisions, delivery authority, and documentation. Put concise rules and pointers in Spring's `AGENTS.md`, longer explanations in Spring runbooks, and objective assertions in Spring checks. Bring in DevGuide suggestions only after the dispositions in [#8][devguide-audit] are agreed.
2. **Replace Spring's `CLAUDE.md` with the one-line reference.** Its target content is exactly `@AGENTS.md` followed by a newline. Update links to old `CLAUDE.md` sections across `AGENTS.md`, skills, custom roles, runbooks, and documentation catalogs. Migrate the meaningful assertions in `test_agent_policy.py`, `test_flightcheck_consumer.py`, and `test_operational_document_contracts.py` that currently refer to those files or the active FlightCheck wiring. Preserve the behavior the assertions protect. [Policy tests][agent-tests] · [FlightCheck consumer tests][consumer-tests] · [Operational document tests][operations-tests]
3. **Keep suggestions, checks, and authority distinct.** Use `AGENTS.md` and skills for advice and workflow selection. Use repo scripts and tests for current verification, deterministic requirements, and proof. Use Codex role files for independent reviewer invocation. Use permission policy for enforceable execution boundaries. Record actual owner decisions at their scope. Treat the status card and board as information. [SpringDev workflow issue][codex-workflow] · [DevGuide workflow reference][devguide-workflow]
4. **Verify the applied workflow in the real Spring checkout.** Start a fresh Codex chat on the selected Spring root and an applicable linked worktree. Confirm loaded instruction sources, selected skill paths, trusted rules and hooks, and an ordinary request versus an explicitly activated workflow. Exercise a review return and stale or failed gate in the pilot. Inspect approved project settings or the Scheduled view on mac-mini only if a desktop action, schedule, or managed integration is selected. Validate the one-line reference and all moved anchors during the migration. [SpringDev pilot][pilot]

## Reproducing the inventory

- Compare `git rev-parse HEAD origin/main`, `git ls-tree -r --name-only origin/main`, `git status --short`, and `git worktree list --porcelain` from Spring. Inspect published config or instructions with `git show origin/main:<path>` so local edits stay distinguishable.
- Parse the relevant TOML and JSON using an allowlist of keys. Report presence, project trust, and relevant trigger configuration without printing credentials, private prompts, hook trust hashes, or unrelated host settings.
- Check `core.hooksPath` with `git config --show-origin --get-all core.hooksPath` and inspect the executable files in the resolved hook directory. Inspect `.codex/hooks.json` and `[hooks]` in relevant config layers. Use a controlled event in a fresh session if a proposed hook needs runtime proof.
- Use `codex execpolicy check --rules <file> -- <command>` to probe tokens without executing the target. Test the provider parser separately. Verify configured CI, active rules and webhook presence via the GitHub API, and project workflows via `ProjectV2.workflows`.
- Record what cannot be observed from the selected host and session. In this audit, live Spring desktop discovery and hook firing, workspace-managed defaults, Scheduled entries, and the relocated candidate's Git state remain unverified.

[issue]: https://github.com/spring-labs-inc/SpringDev/issues/1
[cutover]: https://github.com/spring-labs-inc/SpringDev/issues/2
[verification]: https://github.com/spring-labs-inc/SpringDev/issues/3
[codex-workflow]: https://github.com/spring-labs-inc/SpringDev/issues/4
[pilot]: https://github.com/spring-labs-inc/SpringDev/issues/5
[devguide-audit]: https://github.com/spring-labs-inc/SpringDev/issues/8
[spring454]: https://github.com/spring-labs-inc/Spring/issues/454
[spring-board]: https://github.com/orgs/spring-labs-inc/projects/1
[springdev-board]: https://github.com/orgs/spring-labs-inc/projects/2
[spring-readme]: https://github.com/spring-labs-inc/Spring/blob/60da2477/README.md
[spring-agents]: https://github.com/spring-labs-inc/Spring/blob/60da2477/AGENTS.md
[spring-claude]: https://github.com/spring-labs-inc/Spring/blob/60da2477/CLAUDE.md
[spring-skills]: https://github.com/spring-labs-inc/Spring/tree/60da2477/.agents/skills
[spring-roles]: https://github.com/spring-labs-inc/Spring/tree/60da2477/.codex/agents
[spring-hook]: https://github.com/spring-labs-inc/Spring/blob/60da2477/.codex/hooks.json
[spring-rules]: https://github.com/spring-labs-inc/Spring/blob/60da2477/.codex/rules/spring-github-reads.rules
[adapter]: https://github.com/spring-labs-inc/Spring/blob/60da2477/.flightcheck/adapter.json
[flightcheck]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/ai/FlightCheck.md
[flightcheck-adr]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/06-architecture/20-flightcheck-package-consumption.md
[review-catalog]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/ai/subagents.md
[command-catalog]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/ai/slash-commands.md
[doc-maintenance]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/ai/documentation-maintenance.md
[test-env]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/08-operations/21-local-test-environment.md
[network]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/08-operations/17-container-network-exposure.md
[invariants]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/06-architecture/01-invariants.md
[ui-style]: https://github.com/spring-labs-inc/Spring/blob/60da2477/docs/07-ui-and-design/01-style-guide.md
[agent-checker]: https://github.com/spring-labs-inc/Spring/blob/60da2477/scripts/check_agent_policy.py
[docs-checker]: https://github.com/spring-labs-inc/Spring/blob/60da2477/scripts/check_docs.py
[agent-tests]: https://github.com/spring-labs-inc/Spring/blob/60da2477/spring-web/common/tests/test_agent_policy.py
[consumer-tests]: https://github.com/spring-labs-inc/Spring/blob/60da2477/spring-web/common/tests/test_flightcheck_consumer.py
[operations-tests]: https://github.com/spring-labs-inc/Spring/blob/60da2477/spring-web/spring_web/tests/test_operational_document_contracts.py
[devguide-workflow]: https://github.com/jeffmaddocks/DevGuide/blob/main/docs/WORKFLOW.md
[config]: https://learn.chatgpt.com/docs/config-file/config-basic
[advanced]: https://learn.chatgpt.com/docs/config-file/config-advanced
[managed]: https://learn.chatgpt.com/docs/enterprise/managed-configuration
[agents-md]: https://learn.chatgpt.com/docs/agent-configuration/agents-md
[skills]: https://learn.chatgpt.com/docs/build-skills
[hooks]: https://learn.chatgpt.com/docs/hooks
[rules]: https://learn.chatgpt.com/docs/agent-configuration/rules
[subagents]: https://learn.chatgpt.com/docs/agent-configuration/subagents
[projects]: https://learn.chatgpt.com/docs/projects
[environments]: https://learn.chatgpt.com/docs/environments/local-environment
[worktrees]: https://learn.chatgpt.com/docs/environments/git-worktrees
[scheduled]: https://learn.chatgpt.com/docs/automations
[customization]: https://learn.chatgpt.com/docs/customization/overview
[claude-import]: https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools
