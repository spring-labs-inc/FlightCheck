```text
   ████  ████   ████   █████  █   █   ████  ████   █████  █   █
  ██     ██ ██  ██ ██    █    ██  █  ██     ██ ██  ██     █   █
  ██     ██ ██  ██ ██    █    ██  █  ██     ██  █  ██     █   █
   ███   ████   ████     █    █ █ █  ██ ██  ██  █  ████   █   █
     ██  ██     ███      █    █  ██  ██  █  ██  █  ██      █ █
     ██  ██     ██ █     █    █  ██  ██  █  ██ ██  ██      █ █
  ████   ██     ██ ██  █████  █   █   ███   ████   █████    █

    01 PLAN
      02 IMPLEMENT
      03 CHEAP CHECKS
      04 INTERACTIVE HTML APPROVAL  (UI only)

    05 INDEPENDENT CODE REVIEW
      06 AUTHORITATIVE GATES
      07 SKEPTICAL EVIDENCE REVIEW
      08 FINAL VERDICT
      09 LAND UNDER THE RECORDED GRANT
```

# SpringDev

SpringDev helps Spring maintainers use Codex to take a scoped change from request to verified merge. It brings DevGuide's staged checks, repair loop, and independent reviews into Spring's own tools. Maintainers can review an actual UI before expensive checks run and trace a landing decision back to the candidate, original results, and review findings.

The owner approved cutover after reviewing the Contact us pilot, which ran under FlightCheck. The selected workflow was verified separately and merged into Spring's `main`. The pilot's product change has a separate delivery decision, and its warning-capture follow-up remains open. [Spring PR #455][rollout] · [SpringDev #5][pilot]

### The approach

- Codex plans, implements, and runs Spring's scripted checks in a dedicated worktree. Deterministic failures go back to the implementer for repair. Live or credential-backed checks follow Spring's user-run boundary.
- Two independent, read-only Codex reviewers inspect the code and then the evidence. The implementer records their actual findings and the disposition of each.
- The isolated offline pytest launcher gives each run its own disposable loopback database under `spring_test`, scratch space, JUnit report, and evidence. Separate worktrees can run concurrently. The launcher locks each checkout, and the ordinary shared-database invocation retains its single-owner lock. The [isolation proof][isolation] verified distinct live schemas and data, independent interruption and teardown, and a corrected full suite.
- The optional status card projects a curated Contact us snapshot with eight gate outcomes, the independent verdict, and separate owner decisions. Its route diagnostics distinguish server publication, browser forwarding, and rendering. The workflow can proceed with the tracker and original evidence when the card is unavailable. [Status card prototype][card]

### The workflow

1. Explicitly select a bounded task. Record acceptance criteria, checkout, base, and intended delivery before editing. Give each deterministic criterion a reproducible check.
2. Implement and run the applicable cheap checks in Spring's gate catalog. These cover Ruff, Markdown, agent policy, and workflow policy.
3. For owner-facing UI, show the exact interactive HTML URLs and synthetic fixture identities, bind them to the current surface, and pause for owner approval. A later surface edit requires fresh acceptance. Show rendered images only on request. Nonvisual work proceeds directly to CODE review.
4. Get independent CODE review, then run focused and full offline pytest as applicable on the stable candidate. For applicable UI changes, run VisualQA and its separate findings and freshness check against the report from that run. VisualQA belongs to the expensive gates.
5. Get independent EVIDENCE review. Resolve earlier findings and check that every applicable result still covers the current candidate before following the verdict.

| Final verdict | What happens |
| --- | --- |
| `APPROVE` | Begin authorized landing automatically once the authoritative gates and review pass. |
| `APPROVE_WITH_NITS` | Update or add board items for the nits, then begin authorized landing automatically. |
| `APPROVE_WITH_OBSERVATIONS` | Present the observations and get explicit owner approval to land this candidate, separately from UI approval. |
| `REVISE` | Return to scope or plan, repair, and renew affected checks and reviews. |
| Review pending | Keep landing pending until the independent review is complete. |

Landing follows the recorded grant and the provider's actual head, protections, and required CI. Reconcile an ambiguous provider result before retrying it. [Selected workflow and landing rules][workflow]

**Repair and reuse.** Keep failed and interrupted attempts, diagnose them, and rerun affected checks cheapest first. Continue in-scope repair without fixed time or iteration quotas, honoring actual limits and explicit holds. Reuse a whole passing result only when its exact command, coverage, input fingerprints, runtime identity, and original output digest still match. A newer failure or interruption supersedes the pass. Record the reuse decision against the current candidate. For Markdown also compare link-target manifests, and for VisualQA retain the producer, findings check, and run-specific report together. [Gate reuse safeguards][reuse]

### More info

| Location | What belongs there |
| --- | --- |
| [SpringDev board][board] | Issue scope, acceptance, decisions, and follow-ups |
| [Spring's selected workflow][workflow] and [gate catalog][gates] | Operating rules, applicability, exact commands, and fingerprint inputs |
| [Codex workflow inventory](docs/codex-workflow-inventory.md) | Configuration layers and where workflow guidance belongs |
| [DevGuide workflow audit](docs/devguide-workflow-audit.md) | Adopted practices, differences, and deferred proposals |
| [Contact us pilot][pilot] and [shared rollout][rollout] | Pilot results, cutover decision, and merged Spring implementation |
| [Status card guide](docs/status-card.md) | Launch the read-only viewer and diagnose its browser route |
| [FlightCheck return][return] and [Spring #454][history] | Preserved historical evidence and the owner-directed return procedure |

### Get started

1. Open a dedicated Spring checkout carrying the merged workflow in Codex. Use Git, an installed Codex client, and access to the private Spring and FlightCheck repositories. For tracker or delivery work, use the authorized GitHub CLI login.
2. Set up Spring's Python environment with its [documented venv and development dependencies][instructions]. Provision the disposable test role on loopback PostgreSQL with `./scripts/setup_test_db.sh`. For VisualQA, provision Chromium and WebKit with `.venv/bin/python -m playwright install chromium webkit`. The owner runs the one-time provisioning steps. Offline tests use the disposable role and synthetic credentials. [Local test setup][test-env]
3. Confirm that Codex sees Spring's instructions, skill, and reviewer roles. Use a separate evidence store with no active FlightCheck flight. On the CLI, launch from the Spring checkout with `codex --disable hooks`. Where hooks cannot be disabled, verify the separate store boundary before proceeding. The [reviewer launch guidance][roles] records the CLI configuration exercised during rehearsal.
4. Ask Codex to use `$develop-change` for a specific Spring issue or bounded change. Routine questions and edits use their ordinary entry points. A Ready card, skill discovery, hook event, or review response does not start a new task.

For selected offline testing, the implementer runs the launcher from each Spring checkout root. Here is a focused example followed by the broad default suite when applicable.

```sh
.venv/bin/python -m spring.isolated_pytest spring-web/authn/tests/test_contact.py -q
.venv/bin/python -m spring.isolated_pytest -q
```

See the [selected workflow][workflow] for the four cheap commands, VisualQA and its findings reader, and how to direct checker telemetry to approved private scratch using `FLIGHTCHECK_LOG_ROOT`.

### Configuration

| Spring surface | Role |
| --- | --- |
| `AGENTS.md` and `CLAUDE.md` | Portable project policy and guardrails live in [AGENTS.md][instructions]. `CLAUDE.md` contains the single line `@AGENTS.md`. |
| `.agents/skills/develop-change/SKILL.md` | [Explicit Codex entry point][skill] for selected work and resume. |
| `.codex/agents/workflow-*-reviewer.toml` | Independent CODE and EVIDENCE roles. Launch with a verified read-only tool boundary. |
| `.codex/hooks.json` and `.codex/rules/` | The retained `PermissionRequest` hook logs FlightCheck permission telemetry. Repo rules allow narrow read-only GitHub commands. Workflow activation comes from the owner's request. |
| `.flightcheck/adapter.json` and `requirements-dev.txt` | Spring's [gate catalog][gates] and pinned FlightCheck dependency supply static policy checks and fingerprints. Selected evidence stays separate from the legacy store. |

The isolated launcher defaults to loopback PostgreSQL on port `5432`. Set `SPRING_ISOLATED_TEST_PORT` in the runner environment when the offline test cluster is provisioned on a different loopback port. Run packets and reports are under `.local/tmp/pytest-runs/` in each Spring checkout. [Local test setup][test-env]

To view the read-only status card, use Python 3 from the SpringDev root.

```sh
python3 -B status-card/serve.py --port 8766
```

Keep the loopback server running on the checkout host and open the card in the Codex desktop browser. The card reads `status-card/pilot.json` and has no approval or delivery controls. [Open the card](http://127.0.0.1:8766/) · [Viewing and recovery guide](docs/status-card.md)

### Scope and deferred work

Codex is the supported agent for the selected workflow. The shared instructions leave room for a future Claude deployment. Claude setup and verification, VisualQA extraction, and automatic evidence cleanup are deferred. Spring retains VisualQA, FlightCheck's pinned return path, and the original historical evidence. [DevGuide workflow audit](docs/devguide-workflow-audit.md)

[board]: https://github.com/orgs/spring-labs-inc/projects/2
[rollout]: https://github.com/spring-labs-inc/Spring/pull/455
[history]: https://github.com/spring-labs-inc/Spring/issues/454
[isolation]: https://github.com/spring-labs-inc/SpringDev/issues/3
[pilot]: https://github.com/spring-labs-inc/SpringDev/issues/5
[card]: https://github.com/spring-labs-inc/SpringDev/issues/6
[workflow]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/docs/ai/selected-development-workflow.md
[reuse]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/docs/ai/selected-development-workflow.md#gate-reuse
[roles]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/docs/ai/selected-development-workflow.md#codex-entry-points
[return]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/docs/ai/selected-development-workflow.md#flightcheck-return
[gates]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/.flightcheck/adapter.json
[instructions]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/AGENTS.md
[test-env]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/docs/08-operations/21-local-test-environment.md
[skill]: https://github.com/spring-labs-inc/Spring/blob/2a9aaafae20208fd87f340ccb0ef23375e2f7508/.agents/skills/develop-change/SKILL.md
