# Skills and reviewers

FlightCheck installs the [develop-change skill](../examples/existing-project/.agents/skills/develop-change/SKILL.md) for your selected coding tool. It coordinates planning, implementation, checks, evidence handoff, review, and delivery.

| Coding tool | Start or resume a flight |
| --- | --- |
| Codex | `$develop-change` |
| Claude Code | `/develop-change` |

Adopting projects use explicit selection by default. The installer also supplies two reviewer roles that the workflow invokes at the applicable stage.

| Reviewer role | Purpose |
| --- | --- |
| [workflow-code-reviewer](../examples/existing-project/.codex/agents/workflow-code-reviewer.toml) | Early code review when the change meets the workflow's risk criteria. |
| [workflow-evidence-reviewer](../examples/existing-project/.codex/agents/workflow-evidence-reviewer.toml) | Independent final review of the current change, acceptance criteria, and verified evidence. |

See the [setup guide](../setup/README.md#choose-your-coding-surface) for client discovery, reviewer access, and qualification checks.
