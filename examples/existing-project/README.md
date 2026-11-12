# Adopt FlightCheck in an existing repository

This directory mirrors the files you can add to your own repository. Open your project in Codex and review the examples before merging them into the corresponding paths. Keep existing instructions, nested overrides, rules, hooks, and dependency files. Resolve overlaps by editing the relevant entries in your project.

| Example | When to apply it |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Merge the workflow entry into the project instructions. Keep product rules and tool boundaries here or in the project's existing runbooks. |
| [`CLAUDE.md`](CLAUDE.md) | Optional one-line pointer to the shared instructions. If an existing file contains policy, migrate that policy before replacing it with the pointer. |
| [`SKILL.md`](.agents/skills/develop-change/SKILL.md) | Copy the skill folder to `.agents/skills/`. This is the Codex entry point for a selected task. |
| [CODE role](.codex/agents/workflow-code-reviewer.toml) and [EVIDENCE role](.codex/agents/workflow-evidence-reviewer.toml) | Use the EVIDENCE role for the final code and evidence review. Use the CODE role early when the task meets the configured criteria. Launch each applicable review in a separate session with a verified read-only tool boundary. |
| [Workflow guide](docs/development-workflow.md) | Copy into `docs/` and fill in the project setup table before the first selected task. Use your own check commands and delivery policy. |
| [Project resource index](docs/project-resources.md) | Optional. Fill in the entries your project uses, or point the workflow guide to your existing index. Remove the link from the guide if you omit the index. |
| [`hooks.json`](.codex/hooks.json) | Optional example with an empty handler map. Keep it empty or omit it unless you have a specific event and reviewed handler. Other active hook sources can still run. |
| [`github-reads.rules`](.codex/rules/github-reads.rules) | Optional GitHub CLI rule example. Replace the example repository only if you want this exact read to require an approval prompt when evaluated for outside-sandbox execution. |
| [`requirements.dev.txt`](requirements.dev.txt) | Optional dependency example for projects that choose pytest. Use your existing development manifest and lockfile conventions. |
| [`capture_check.py`](scripts/capture_check.py) | Optional output recorder and automatic pass reuse for native checks. Configure a gate identifier and a project-owned fingerprint probe to enable reuse. |
| [`proof.py`](scripts/proof.py) | Acceptance contracts, retained reviewer requests, and regression-proof validation used by `handoff.py`. |
| [`handoff.py`](scripts/handoff.py) | Use the recorder receipts to summarize resumed work and validate acceptance proof, reviewer obligations, and the final review packet. Copy its adjacent `proof.py` module too. |

Codex loads project instructions based on the working directory and active overrides. Skill discovery, project trust, and approval policy are separate. Review the effective project settings on the client that will run the workflow. The examples require no global configuration, plugin, hook, external package, or new CI service. [Project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md) · [Skills](https://learn.chatgpt.com/docs/build-skills) · [Hooks](https://learn.chatgpt.com/docs/hooks) · [Command rules](https://learn.chatgpt.com/docs/agent-configuration/rules)

## Verify the adoption

1. Review the diff for unrelated policy or permission changes. Include the skill directory and any new files when inspecting the candidate.
2. From a fresh Codex session at the target checkout, confirm the active instruction path and skill. Ask an ordinary question and confirm that it stays outside the workflow.
3. Select a small task with `$develop-change`. Run the configured checks on that candidate and verify that the final reviewer and any configured early reviewer can inspect it with read-only access. Rehearse verdict routing without provider writes until your project has a recorded delivery grant.
4. If you adopt the optional rules, probe matching and nearby nonmatching commands with `codex execpolicy check --rules .codex/rules/github-reads.rules -- <command tokens>`. The probe evaluates the rule without running the command. Review the result alongside user and managed rules.

Projects using other languages should use their own package manager, checks, and test isolation. A project with no preview or visual checks can record those as inapplicable for nonvisual work. A project that requires CI must wait for its checks on the actual candidate. A project with no CI requirement can record that fact and rely on its required local checks and reviews.
