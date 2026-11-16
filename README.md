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

FlightCheck is a lightweight set of repository instructions that guides AI-assisted changes from request to landing.

- **Follow a consistent workflow.** Each flight moves through planning, implementation, cheap checks, and UI approval when needed, followed by broader testing and skeptical review.
- **Carry evidence into every review.** Fingerprinted check results and original output pass between stages, helping reviewers catch defects and identify stale or incomplete evidence before approving a change.
- **Make delivery decisions explicit.** The final verdict determines whether the change lands under the project’s delivery rules, returns for repair, or needs a user decision.
- **See where the work stands.** A live status card shows the current stage, check results, verdict, and linked issues.

<br clear="right">

## The workflow

1. Select a bounded task, agree on acceptance criteria, and define reproducible checks in a dedicated checkout.
2. Implement the change and run the cheap checks. For owner-facing UI, review interactive HTML with synthetic data and record approval before broader testing.
3. Apply the [early CODE review criteria](examples/existing-project/docs/development-workflow.md#decide-on-early-code-review). When early review is needed, supply the current change and check evidence. Then run the remaining required tests and visual checks.
4. Hand the current change, acceptance criteria, and verified evidence to a separate final reviewer. Use the verdict below to determine the next step.

Handoffs carry check receipts and original output between stages. Fingerprints tie each result to the code, command, coverage, and environment that produced it. Before review or reuse, FlightCheck verifies those records and identifies missing, changed, or failed evidence. Repairs renew the affected checks and reviews while preserving earlier results for inspection.

| Verdict | Action |
| --- | --- |
| `APPROVE` | Begin landing under the recorded delivery grant after applicable gates pass. |
| `APPROVE_WITH_NITS` | Track the nits, then begin authorized landing. |
| `APPROVE_WITH_OBSERVATIONS` | Ask the owner to approve the specific observations before landing. |
| `REVISE` | Return to the plan or implementation and renew affected checks and reviews. |

## Guides

| Guide | Use |
| --- | --- |
| [Setup](setup/README.md) | Install the workflow, evidence tools, client adapters, and status card. |
| [PyPI distribution](docs/pypi-distribution.md) | Review the planned package installation and project setup flow. |
| [Workflow](examples/existing-project/docs/development-workflow.md) | Follow the checks, reviews, repair, and delivery rules. |
| [Evidence handoff](examples/existing-project/docs/development-workflow.md#carry-checks-across-the-handoff) | Record original output, verify receipts, and carry evidence into review. |
| [Claude Code](docs/claude-code.md) | Configure the adapter and check native qualification status. |
| [Status card](docs/status-card.md) | Publish and view task progress and the current verdict. |
| [Benchmarks](docs/benchmark.md) | Read results and reproduce the pinned trials. |
| [Contributing](CONTRIBUTING.md) | Read the contribution policy and run FlightCheck's own tests. |

## Get started

Open your existing project in your AI coding tool and paste this prompt.

> Install FlightCheck from https://github.com/spring-labs-inc/FlightCheck into this project. Follow setup/README.md, preserve this project's instructions, dependency management, and delivery permissions, and verify the complete installation for my coding tool. Ask me about unresolved project choices together. Keep changes uncommitted.

The [setup guide](setup/README.md) covers installation, project configuration, and verification. Codex and Claude Code adapters are included. Complete a small first flight using your tool's workflow entry point before taking on larger changes.

## License and commercial use

FlightCheck is available under the [Functional Source License 1.1, with MIT as its future license (FSL-1.1-MIT)](LICENSE). Personal and internal organizational use—including commercial work—is free. No account, subscription, or license key is required. Competing commercial offerings require separate permission during the applicable two-year period. Each version becomes available under MIT two years after publication. For additional permissions, contact [jeff@springfinance.io](mailto:jeff@springfinance.io). Subscriptions remain deferred.

Before copying workflow files, read the [licensing and adoption guide](docs/licensing.md). Outside code contributions are currently deferred; [bug reports and feature requests are welcome](CONTRIBUTING.md).
