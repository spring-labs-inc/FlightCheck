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
      03 CHEAP CHECKS
      04 INTERACTIVE HTML APPROVAL  (UI only)

    05 EARLY CODE REVIEW  (when warranted)
      06 AUTHORITATIVE GATES
      07 FINAL CODE AND EVIDENCE REVIEW
      08 FINAL VERDICT
      09 LAND UNDER THE RECORDED GRANT
```

# SpringDev

SpringDev is a set of repository instructions and Codex configuration examples for taking a change from request to verified merge. It gives maintainers a repeatable way to run their own checks, review interactive HTML for UI changes, and see the evidence behind a landing decision.

### Get started

Open your **existing project** in Codex. Review the [example project layout](examples/existing-project/README.md), then merge the relevant files into your repository at the paths shown. Keep your project's instructions, test tools, and permissions. SpringDev runs through those tools and requires no module installation.

1. Merge the workflow entry into your `AGENTS.md`. Add the skill, workflow guide, and final reviewer role. Add the early CODE role for tasks that meet the project's early review criteria.
2. Configure the fast checks, remaining required gates, test isolation, preview method, evidence location, and delivery policy in the workflow guide. Use commands from your own stack and require the checks your repository actually uses.
3. Start a fresh Codex session in the target checkout. Verify the instructions, skill, and read-only reviewer setup on a small task. Ask Codex to use `$develop-change` for that task.

To have Codex adapt the configuration, give it access to the example files and use this prompt in your existing repository:

> Review the SpringDev example project and my repository's current instructions, test commands, permissions, and delivery rules. Propose the smallest project-local diff. Adapt the workflow and reviewer files to my tools, preserve my existing policy, and verify the setup. Ask me to resolve any permission or delivery decisions that are missing.

### The workflow

1. Select a bounded task and agree on acceptance criteria. Work in a dedicated checkout and give each deterministic criterion a reproducible check.
2. Implement the change and run the configured cheap checks, including fast tests for affected behavior. Repair failures and confirm the affected checks pass before moving on. For owner-facing UI, then show interactive HTML with synthetic data and pause for approval of that surface. Show renders only on request.
3. Use early independent CODE review for high-risk changes or when checking the proposed approach before expensive gates could avoid substantial rework. Run the remaining required tests and visual checks within the project's permissions. Carry forward matching receipts for required checks already completed.
4. Give one independent final reviewer the current diff, acceptance criteria, gate results and receipts, and open findings or owner decisions. Use their verdict to route the work.

| Verdict | Action |
| --- | --- |
| `APPROVE` | Begin landing under the recorded delivery grant after applicable gates pass. |
| `APPROVE_WITH_NITS` | Track the nits, then begin authorized landing. |
| `APPROVE_WITH_OBSERVATIONS` | Ask the owner to approve the specific observations before landing. |
| `REVISE` | Return to the plan or implementation and renew affected checks and reviews. |

Repair failures with the cheapest affected check first. Use automated receipts to reuse expensive checks when their command, coverage, inputs, runtime, and original output still match. Run tests concurrently across worktrees when they have independently verified databases, ports, scratch space, and reports as applicable.

### Configuration and references

| Location | Use |
| --- | --- |
| [Example project layout](examples/existing-project/README.md) | Review the exact paths for instructions, skill, reviewer TOML, hooks JSON, rules, and optional Python test dependencies. |
| [Workflow guide](examples/existing-project/docs/development-workflow.md) | Adapt gate commands, evidence, review, and landing to your project. |
| [Status card guide](docs/status-card.md) | View an optional read-only example of check outcomes, review verdicts, and owner decisions. |
| [Project board](https://github.com/orgs/spring-labs-inc/projects/2) | Track changes to SpringDev. |
