# Codex workflow inventory

This guide maps Codex configuration, instructions, verification, and permission boundaries to the [SpringDev adoption example][adoption]. The original inspection is recorded in [SpringDev #1][issue]. Historical migration and recovery evidence is indexed in [Spring #454][migration] and the [SpringDev retention decision][retention].

## Codex configuration layers

Ordinary configuration resolves from highest to lowest precedence in the order below. For trusted project configuration, a file nearer the working directory wins on conflicting keys. Launch context, instructions, skills, hooks, and command rules have their own discovery or merge rules. [OpenAI config basics][config] · [Advanced configuration][advanced]

| Layer | When to use it |
| --- | --- |
| CLI flags and `--config` | Set a value for a single run or controlled probe. Record overrides that affect verification. |
| Trusted project `.codex/config.toml` | Share Codex defaults with a project. Add a nested layer only for a subtree with distinct needs. |
| Selected `$CODEX_HOME/<profile>.config.toml` | Use a named, opt-in setup such as a diagnostic profile. Keep project requirements reproducible without it. |
| User `$CODEX_HOME/config.toml` | Set personal defaults for model, effort, notifications, and tools. Keep project workflow guidance with the project. |
| Cloud-managed `config.toml` defaults | Set workspace defaults where the signed-in workspace supplies them. |
| System `/etc/codex/config.toml` | Set an administrator-owned baseline on a managed host. |
| Built-in defaults | Keep defaults unless a run or project needs a specific override. Verify the effective values on the runtime that will execute the workflow. |

Managed requirements can constrain settings independently of this precedence. Check system requirements, workspace policy, and device management where applicable. Verify the effective sandbox and approval policy before running checks or independent reviews. After moving a checkout, check project trust and hook trust for the actual launch path. [OpenAI managed configuration][managed] · [Codex hooks][hooks]

## Instructions, skills, and reviewers

Codex loads one nonempty instruction file from its home, then walks the project root-to-working-directory chain. At each project directory it prefers `AGENTS.override.md`, then `AGENTS.md`, then configured fallback names. The default project instruction budget is 32 KiB. Start a fresh session to verify what loads. [Instruction discovery][agents-md]

| Surface | SpringDev use |
| --- | --- |
| Global `AGENTS.md` or override | Keep personal guidance that applies across repositories. |
| Project `AGENTS.md` or nested override | Record durable project rules, command boundaries, and workflow selection. Use nested instructions for scoped requirements. |
| `CLAUDE.md` | Use the [example's one-line import][claude-example] when sharing instructions with Claude Code. Keep the shared policy in `AGENTS.md`. [Claude Code instruction imports][claude-import] |
| README and runbooks | Keep setup in README and link task-specific procedures from the relevant instructions or skill. |
| Session prompt and issue brief | Use the current request to select a flight and record its scope, acceptance, and delivery authority. |
| `.agents/skills/*/SKILL.md` | Put reusable workflow steps in a project skill. Use the skill description for discovery and open linked procedures when needed. [Codex skills][skills] |
| `.codex/agents/*.toml` | Configure independent CODE and EVIDENCE reviewers. Verify the actual role, read-only permissions, and access to the required evidence in each review session. [Codex custom agents][subagents] |

## Hooks, tools, and triggers

| Surface | SpringDev use |
| --- | --- |
| `.codex/hooks.json` and other hook sources | Use a hook for an observable need tied to a supported event. Inspect active user, project, managed, and plugin sources. Confirm trust and test the event before relying on it. Use the owner request to select a workflow. [Codex hooks][hooks] |
| `.codex/rules/*.rules` and user rules | Use narrow command prefixes for execution outside the sandbox. Check the effective decision and test the command parser separately. [Codex command rules][rules] |
| Git hooks and repository scripts | Keep deterministic checks in project-native scripts or tests. Inspect `core.hooksPath` when auditing which Git hooks can run. |
| CI, branch rules, and webhooks | Verify the provider's actual delivery requirements and configured triggers. Use current check results for the candidate being delivered. |
| Project board automations | Track work and follow-ups. Review enabled workflows before relying on automatic issue or board updates. |
| Desktop setup, actions, and scheduled tasks | Use worktree setup for repeatable setup, desktop actions for commands the owner chooses, and schedules for separately configured work. [Local environments][environments] · [Scheduled tasks][scheduled] |
| MCP, plugins, and client integrations | Check which tools the chosen client and execution host expose. Document any integration the project relies on. [Codex customization][customization] |

## Verify the effective setup

1. Record the repository root, working directory, branch, and runtime. Compare the tracked revision with local changes and the remote base. Desktop, IDE, CLI, worktree, and SSH launches can expose different sources and tools. [Projects and chats][projects] · [Codex worktrees][worktrees]
2. Inspect relevant configuration keys and instruction files. Check which skills, roles, rules, and hooks the actual session can use. Keep credentials and private settings out of the record.
3. Exercise an ordinary request and an explicitly selected workflow. Use `codex execpolicy check --rules <file> -- <command>` to evaluate command tokens without running the target. Record what was configured, what was observed, and what still needs a live probe.
4. Verify the project's native checks, evidence locations, and independent review boundaries on a small task. Use the [workflow guide][workflow] for check scope, evidence reuse, and landing decisions.

[issue]: https://github.com/spring-labs-inc/SpringDev/issues/1
[migration]: https://github.com/spring-labs-inc/Spring/issues/454
[retention]: https://github.com/spring-labs-inc/SpringDev/issues/11
[adoption]: ../examples/existing-project/README.md
[claude-example]: ../examples/existing-project/CLAUDE.md
[workflow]: ../examples/existing-project/docs/development-workflow.md
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
