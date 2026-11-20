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
2. Implement the change and run the cheap tests. Deterministic testing is always scripted.
3. For UI changes, obtain user approval using interactive HTML before broader testing.
4. **Early CODE review:** run an independent skeptical review when the change’s risk or uncertainty warrants it, helping catch defects before broader testing.
5. **Authoritative testing:** run the remaining required project checks, including applicable regression and integration tests.
6. **Final code and evidence review:** independently review the current change, acceptance criteria, and verified evidence. Every flight receives this review.
7. Use the verdict to determine whether to land the change, return for repair, or request a user decision.

| Verdict | Action |
| --- | --- |
| `APPROVE` | Begin landing under the recorded delivery grant after applicable gates pass. |
| `APPROVE_WITH_NITS` | Track the nits, then begin authorized landing. |
| `APPROVE_WITH_OBSERVATIONS` | Ask the owner to approve the specific observations before landing. |
| `REVISE` | Return to the plan or implementation and renew affected checks and reviews. |

Handoffs carry check receipts and original output between stages. Fingerprints tie each result to the code, command, coverage, and environment that produced it. Before review or reuse, FlightCheck verifies those records and identifies missing, changed, or failed evidence. Repairs renew the affected checks and reviews while preserving earlier results for inspection.

## Guides

| Guide | Use |
| --- | --- |
| [Workflow](examples/existing-project/docs/development-workflow.md) | Follow the stages, delivery rules, and [skills and reviewers](docs/skills-and-reviewers.md). |
| [Status Card](docs/status-card.md) | Publish and view task progress and the current verdict. |
| [Evidence handoff](examples/existing-project/docs/development-workflow.md#carry-checks-across-the-handoff) | Record original output, verify receipts, and carry evidence into review. |
| [Benchmarks](docs/benchmark.md) | Read results and reproduce the pinned trials. |
| [Setup](setup/README.md) | Configure Codex CLI, Codex Desktop, Claude Desktop, or Claude Code and verify the installation. |
| [Contributing](CONTRIBUTING.md) | Read the contribution policy and run FlightCheck's own tests. |

## Get started

**Supported environments:** Claude Desktop, Claude Code TUI, Codex Desktop, and Codex CLI/TUI. FlightCheck has been verified in all four environments.

Install from Git with [pipx](https://pipx.pypa.io/stable/installation/), then run setup from your terminal. Requires Git and Python 3.9+ on POSIX.

```sh
pipx install "git+https://github.com/spring-labs-inc/FlightCheck.git"
cd /path/to/your/project
flightcheck init . --agent claude
flightcheck doctor .
```

Use `--agent codex` for Codex or `--agent both` for both clients. Setup confirms the project choices, previews the changes, and asks before applying them. It preserves existing instructions, permissions, dependencies, and delivery policy.

After verification, start a fresh session in your coding tool and select a small first flight with `/develop-change` (Claude) or `$develop-change` (Codex). TUI users can open the printed status-card URL in their regular browser.

The [setup guide](setup/README.md) covers configuration, saved plans, recovery, and current client qualification limits. PyPI installation will replace this Git channel after a release is published and verified.

## License and commercial use

FlightCheck is available under the [Functional Source License 1.1, with MIT as its future license (FSL-1.1-MIT)](LICENSE). Personal and internal organizational use—including commercial work—is free. No account, subscription, or license key is required. Competing commercial offerings require separate permission during the applicable two-year period. Each version becomes available under MIT two years after publication. For additional permissions, contact [jeff@springfinance.io](mailto:jeff@springfinance.io). Subscriptions remain deferred.

Before copying workflow files, read the [licensing and adoption guide](docs/licensing.md). Outside code contributions are currently deferred; [bug reports and feature requests are welcome](CONTRIBUTING.md).
