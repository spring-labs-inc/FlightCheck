```text
██████  ██      ██████   █████  ██  ██  ██████   █████  ██  ██  ██████   █████  ██  ██
██      ██        ██    ██      ██  ██    ██    ██      ██  ██  ██      ██      ██ ██
██      ██        ██    ██      ██  ██    ██    ██      ██  ██  ██      ██      ████
█████   ██        ██    ██ ███  ██████    ██    ██      ██████  █████   ██      ███
██      ██        ██    ██  ██  ██  ██    ██    ██      ██  ██  ██      ██      ████
██      ██        ██    ██  ██  ██  ██    ██    ██      ██  ██  ██      ██      ██ ██
██      ██████  ██████   █████  ██  ██    ██     █████  ██  ██  ██████   █████  ██  ██


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

# FlightCheck

<img align="right" width="380" src="docs/status-card-preview.png" alt="Synthetic FlightCheck task status card with an expanded issue, workflow stages, local checks, and CI observations">

FlightCheck is a lightweight set of repository instructions that guides AI-assisted changes from request to verified merge. Each flight starts with planning, implementation, cheap checks, and UI approval when needed, followed by broader testing and skeptical review. The final verdict determines whether the change lands under the project’s delivery rules, returns for repair, or needs a user decision. A live status card shows the current stage, check results, and linked issues.

## License and commercial use

FlightCheck is available under the [Functional Source License 1.1, with MIT as its future license (FSL-1.1-MIT)](LICENSE). Personal and internal organizational use—including commercial work—is free. No account, subscription, or license key is required. Competing commercial offerings require separate permission during the applicable two-year period. Each version becomes available under MIT two years after publication. For additional permissions, contact [jeff@springfinance.io](mailto:jeff@springfinance.io). Subscriptions remain deferred.

Before copying workflow files, read the [licensing and adoption guide](docs/licensing.md). Outside code contributions are currently deferred; [bug reports and feature requests are welcome](CONTRIBUTING.md).

## Get started

Open your existing project in your AI coding tool and paste this prompt. The [complete installation guide](setup/README.md) describes each step and its expected result.

> Install FlightCheck from https://github.com/spring-labs-inc/FlightCheck into this existing project. Clone the source outside this checkout, resolve and record its full commit ID, and use that clean pinned revision. Follow `setup/README.md` and the complete manifest in `setup/manifest.json`; the shared adoption files are under `examples/existing-project/`. Inspect my existing instructions, checks, interpreter, default branch, and permissions first. Preserve that policy and batch only unresolved owner decisions. Preview and apply the project-local installer for my coding tool, including all shared evidence tools, its agent adapter, and the browser status card. Do not silently substitute a documentation-only installation. Run installed verification and fresh-session discovery/reviewer/browser probes; report any remaining blocker honestly. Keep changes uncommitted unless I authorize delivery.

Your tool must support repository instructions, running project checks, and separate reviewers with [enforced read-only access](examples/existing-project/docs/development-workflow.md#independent-review). Evidence tooling requires Python 3 on a POSIX host.

The installer supplies Codex and Claude Code adapters. Use the [Claude setup and trial guide](docs/claude-code.md) for contributor discovery, review boundaries and a real adoption trial. Native Claude end-to-end qualification remains pending in [#14](https://github.com/spring-labs-inc/FlightCheck/issues/14).

[Verify the setup](examples/existing-project/README.md#verify-the-adoption) on one small task before using it for larger changes. Explicitly select the workflow using your tool's entry point.

<br clear="right">

## The workflow

1. Select a bounded task and agree on acceptance criteria. Work in a dedicated checkout and give each deterministic criterion a reproducible check.
2. Implement the change and run the cheap checks. For owner-facing UI, then show interactive HTML with synthetic data and pause for approval of that surface. Show renders only on request.
3. Apply the [early CODE review criteria](examples/existing-project/docs/development-workflow.md#decide-on-early-code-review) and record the reason for the decision. Then run the remaining required tests and visual checks within the project's permissions.
4. Give one independent final reviewer the current candidate, acceptance criteria, and verified gate evidence. Route the final verdict below.

| Verdict | Action |
| --- | --- |
| `APPROVE` | Begin landing under the recorded delivery grant after applicable gates pass. |
| `APPROVE_WITH_NITS` | Track the nits, then begin authorized landing. |
| `APPROVE_WITH_OBSERVATIONS` | Ask the owner to approve the specific observations before landing. |
| `REVISE` | Return to the plan or implementation and renew affected checks and reviews. |

## Guides

| Guide | Use |
| --- | --- |
| [Setup](setup/README.md) | Install the complete manifest, configure your project, and verify adoption. |
| [Workflow](examples/existing-project/docs/development-workflow.md) | Follow the checks, reviews, repair, and delivery rules. |
| [Status card](docs/status-card.md) | Publish and view task progress and the current verdict. |
| [Benchmarks](docs/benchmark.md) | Read results and reproduce the pinned trials. |
| [Contributing](CONTRIBUTING.md) | Read the contribution policy and run FlightCheck's own tests. |
