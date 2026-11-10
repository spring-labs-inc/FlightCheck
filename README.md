```text
 ██████  ██████   ██████   ██████  ██    ██   ██████  █████    ███████  ██    ██
██       ██   ██  ██   ██    ██    ███   ██  ██       ██  ██   ██       ██    ██
██       ██   ██  ██   ██    ██    ████  ██  ██       ██   ██  ██       ██    ██
 █████   ██████   ██████     ██    ██ ██ ██  ██ ████  ██   ██  ██████    ██  ██
     ██  ██       ██ ██      ██    ██  ████  ██   ██  ██   ██  ██        ██  ██
     ██  ██       ██  ██     ██    ██   ███  ██   ██  ██  ██   ██         ████
██████   ██       ██   ██  ██████  ██    ██   █████   █████    ███████     ██


    01 PLAN
      02 IMPLEMENT
      03 CHEAP TESTS

    04 INTERACTIVE UI APPROVAL
      05 INDEPENDENT CODE REVIEW
      06 AUTHORITATIVE GATES
      07 SKEPTICAL EVIDENCE REVIEW
      08 FINAL VERDICT
      09 PR & MERGE
```

# SpringDev

<img align="right" width="380" src="docs/status-card-preview.png" alt="SpringDev example status card showing seven passing automated checks, test counts, and an APPROVE verdict">

SpringDev is a set of repository instructions and Codex configuration examples for taking a change from request to verified merge. It gives maintainers a repeatable way to run their own checks, review interactive HTML for UI changes, and see the evidence behind a landing decision.

### Get started

Open your **existing project** in Codex. Review the [example project layout](examples/existing-project/README.md), then merge the relevant files into your repository at the paths shown. Keep your project's instructions, test tools, and permissions. SpringDev runs through those tools and requires no module installation.

1. Merge the workflow entry into your `AGENTS.md`. Add the skill, workflow guide, and two reviewer role files.
2. Set the exact local checks, test isolation, preview method, evidence location, and delivery policy in the workflow guide. Use commands from your own stack and require the checks your repository actually uses.
3. Start a fresh Codex session in the target checkout. Verify the instructions, skill, and read-only reviewer setup on a small task. Ask Codex to use `$develop-change` for that task.

To have Codex adapt the configuration, give it access to the example files and use this prompt in your existing repository:

> Review the SpringDev example project and my repository's current instructions, test commands, permissions, and delivery rules. Propose the smallest project-local diff. Adapt the workflow and reviewer files to my tools, preserve my existing policy, and verify the setup. Ask me to resolve any permission or delivery decisions that are missing.

<br clear="right">

### The workflow

1. Select a bounded task and agree on acceptance criteria. Work in a dedicated checkout and give each deterministic criterion a reproducible check.
2. Implement the change and run the cheap checks. For owner-facing UI, then show interactive HTML with synthetic data and pause for approval of that surface. Show renders only on request.
3. Run independent CODE review, then applicable focused and broad tests and expensive visual checks. Run tests automatically where the project's permissions and fixtures allow.
4. Run independent EVIDENCE review against the candidate and original check output. Route the final verdict below.

| Verdict | Action |
| --- | --- |
| `APPROVE` | Begin landing under the recorded delivery grant after applicable gates pass. |
| `APPROVE_WITH_NITS` | Track the nits, then begin authorized landing. |
| `APPROVE_WITH_OBSERVATIONS` | Ask the owner to approve the specific observations before landing. |
| `REVISE` | Return to the plan or implementation and renew affected checks and reviews. |

Repair failures with the cheapest affected check first. Reuse a pass only when the command, coverage, inputs, environment, and original output still match. Run tests concurrently across worktrees when they have independently verified databases, ports, scratch space, and reports as applicable.

### Configuration and references

| Location | Use |
| --- | --- |
| [Example project layout](examples/existing-project/README.md) | Review the exact paths for instructions, skill, reviewer TOML, hooks JSON, rules, and optional Python test dependencies. |
| [Workflow guide](examples/existing-project/docs/development-workflow.md) | Adapt gate commands, evidence, review, and landing to your project. |
| [Status card guide](docs/status-card.md) | View an optional read-only example of check outcomes, review verdicts, and owner decisions. |
| [Project board](https://github.com/orgs/spring-labs-inc/projects/2) | Track changes to SpringDev. |
