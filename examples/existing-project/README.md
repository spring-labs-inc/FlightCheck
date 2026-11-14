# Adopt FlightCheck in an existing repository

This directory contains the shared adoption sources. Use the [complete installation flow](../../setup/README.md) to install the standard workflow, evidence tools, browser status card and selected client adapter together. Keep existing instructions, nested overrides, permissions, rules, hooks, and dependency files.

## License when adopting

These example files are covered by the repository's [Functional Source License 1.1, MIT Future License (FSL-1.1-MIT)](../../LICENSE). Internal organizational use, including commercial work, is free. Each version becomes available under MIT two years after it is first published under FSL; newer releases do not reset that version's clock.

Before copying them, read the [licensing and adoption guide](../../docs/licensing.md). Carry the applicable license text or a link to it, preserve copyright notices, and identify the FlightCheck-derived files or portions separately. Keep your project's own license in place for independently created application code.

Competing commercial offerings, as defined in the license, require separate permission during the applicable two-year period. Contact [jeff@springfinance.io](mailto:jeff@springfinance.io) for additional permissions. An inquiry does not grant permission. No account, subscription, or license key is required for FSL-permitted use.

## Install and configure

Use Git, Python 3.9+ on POSIX, and a coding tool that can read repository instructions, run project checks, and launch separate reviewers with [enforced read-only access](docs/development-workflow.md#independent-review). The installer provides Codex files and generates Claude-native files from the same canonical reviewer instructions. Native Claude end-to-end qualification remains pending in [#14](https://github.com/spring-labs-inc/FlightCheck/issues/14).

1. Obtain a clean pinned source and run the installer's `inspect` step. Read existing project policy and resolve only missing configuration decisions together.
2. Follow the [configuration, plan and apply steps](../../setup/README.md#3-resolve-the-project-choices-together). The default activation is opt-in and the default delivery grant permits no provider writes. Default-for-coding needs an explicit owner decision. Your project supplies its actual checks, isolation, evidence and any required CI.
3. Run the installed verifier and then start a fresh client session for [adoption verification](#verify-the-adoption). Successful file/HTTP checks alone do not establish a working reviewer boundary or browser rendering.

The standard installation includes all six files in [`scripts/`](scripts): `capture_check.py`, `handoff.py`, `proof.py`, `recovery.py`, `behavior.py`, and `disposition.py`, kept adjacent under `.flightcheck/scripts/`. They use the Python standard library; the recorder uses POSIX process controls and `fcntl` locking. The complete source-to-destination list, including card dependencies, is in the [installation manifest](../../setup/manifest.json).

Configure the [task JSON](docs/development-workflow.md#resume-summary-and-final-packet), a [private evidence directory outside the checkout](docs/development-workflow.md#capture-native-check-output), and a [project-owned fingerprint command for each recorded gate](docs/development-workflow.md#reuse-a-result). If you enable coverage verification, use the documented [coverage report and frozen baseline format](docs/development-workflow.md#verify-native-test-coverage).

### Shared source files

The installer preserves original source/installed hashes and license provenance in `.flightcheck/installation.json`. It appends marked instructions to the selected client's existing policy file rather than replacing it. The following table explains the source material; use the manifest for installed paths and complete component verification.

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
| [`capture_check.py`](scripts/capture_check.py) | Standard output recorder and automatic pass reuse for native checks. Configure a gate identifier and a project-owned fingerprint probe to enable reuse. |
| [`proof.py`](scripts/proof.py) | Acceptance contracts, retained reviewer requests, and regression-proof validation used by `handoff.py`. |
| [`recovery.py`](scripts/recovery.py) | Plan missing or stale prerequisites from the complete retained obligation history. |
| [`behavior.py`](scripts/behavior.py) | Validate observable cases, independent challenge proposals, and qualified baseline or mutation controls. |
| [`disposition.py`](scripts/disposition.py) | Retain independently acknowledged refutations without deleting original claims. |
| [`handoff.py`](scripts/handoff.py) | Summarize resumed work and validate acceptance proof, reviewer obligations, and review packets. Copy all six adjacent Python files together. |
| [Status card](../../status-card/) | Standard browser card and portable publisher/server, installed with their sibling dependencies. See the [setup guide](../../setup/README.md#6-verify-the-client-in-a-fresh-session) for terminal/browser and remote verification. |

## Verify the adoption

1. Review the diff for unrelated policy or permission changes. Include the skill directory and any new files when inspecting the candidate.
2. From a fresh session at the target checkout, confirm the active instruction path and skill. Ask an ordinary question and confirm that it stays outside the workflow.
3. Explicitly select a small task using your tool's entry point (`$develop-change` in the bundled Codex setup). Run the configured checks on that candidate and verify that the final reviewer and any configured early reviewer can inspect it with read-only access. Rehearse verdict routing without provider writes until your project has a recorded delivery grant.
4. Verify the real task card using the installed `.flightcheck/docs/status.md`. Record HTTP publication and browser rendering separately; terminal users can open the same live card in a regular browser. Keep unsupported capabilities explicit rather than silently omitting the card.

Projects using other languages should use their own package manager, checks, and test isolation. A project with no preview or visual checks can record those as inapplicable for nonvisual work. A project that requires CI must wait for its checks on the actual candidate. A project with no CI requirement can record that fact and rely on its required local checks and reviews.

## Claude integration

Use the [Claude contributor/setup and trial guide](../../docs/claude-code.md). The source-layout `.claude/` wrappers reference shared policy; the complete installer generates destination-specific skills and reviewer Markdown with explicit adopter selection. Verify loaded instructions and effective tools/hooks in a fresh native session before claiming support.

## Codex integration

Codex loads project instructions based on the working directory and active overrides. Skill discovery, project trust, and approval policy are separate. Review the effective project settings on the client that will run the workflow. The examples require no global configuration, plugin, hook, external package, or new CI service. [Project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md) · [Skills](https://learn.chatgpt.com/docs/build-skills) · [Hooks](https://learn.chatgpt.com/docs/hooks) · [Command rules](https://learn.chatgpt.com/docs/agent-configuration/rules)

If you adopt the optional GitHub CLI rule, use an authenticated `gh` and adapt its repository. Probe matching and nearby nonmatching commands with `codex execpolicy check --rules .codex/rules/github-reads.rules -- <command tokens>`. The probe evaluates the rule without running the command. Review the result alongside user and managed rules.
