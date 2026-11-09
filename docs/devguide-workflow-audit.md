# DevGuide practices for SpringDev

Audit for [SpringDev #8][issue], November 8, 2026. This document recommends which DevGuide practices Spring should adopt and where they belong. The [Codex workflow inventory][inventory] maps the available surfaces. The [cutover issue][cutover] will reconcile the agreed practices with Spring #454 before changes to Spring's active workflow.

## Evidence and scope

- **DevGuide source.** The clean local `main` and GitHub `main` both resolved to `25163b22ef33b490bc9a0878c10e22aeb281ca40`. The source links below pin that revision. I inspected the contributor instructions, consumer setup, contracts, implementation, and selected test cases. *Shipped* means the capability is in that source or has a recorded closeout. The audit uses source and tracker evidence rather than a new runtime exercise. [Contributor instructions][dg-agents] · [Product direction][product] · [MVP closeout][mvp]
- **Proposals.** The tracker had 26 open issues and no open pull requests. *Open* means a proposal or active upstream task, even when code may exist outside `main`. The tracker remains the source for its status and acceptance. [DevGuide project][board]
- **Spring baseline.** This comparison uses Spring's published `main` at `60da2477186bac9e04e369e47a0f8d0087859313` and the recorded Spring #454 shadow checkpoints. That issue reports eight successful checks on the migration candidate and independent review with observations. The cutover is open. [Spring instructions][spring-agents] · [Spring workflow rules][spring-claude] · [Spring #454][spring454]

## Practices to carry forward

**Keep** means carry the practice forward. **Adapt** means preserve the intent and use Spring's rules and tools to implement it. The table combines proposed guidance with the owner decisions recorded below. Existing Spring requirements, deterministic test assertions, and the owner's authority remain distinct from that guidance.

| Practice and evidence | Disposition and suggested Spring behavior | Proposed home |
| --- | --- | --- |
| **Explicit activation and bounded scope.** DevGuide's shipped integration instructions and activation fixtures distinguish owner-selected work from a question, routine edit, setup, or a Ready card. [Activation contract][activation] · [Activation tests][activation-tests] | **Keep.** Start the workflow when the owner clearly selects it for a bounded task. Record the issue or brief, scope, and plan. Continue the selected work across turns. Treat a clarification or side question as such. Bind new scope only when the owner's direction changes it. | Short startup and scope rules in Spring `AGENTS.md`. The issue or brief holds task-specific criteria. |
| **Worktree and resume.** Shipped tools can choose a durable workspace, bind it to scope, and resume or recover a known worker. Parallel increments have their own ownership and integration guards. [Setup][setup] · [Worker tests][worker-tests] · [Recovery tests][recovery-tests] | **Adapt.** When an isolated worktree is called for and authorized, record its path, branch and base, and keep evidence needed for resume outside the removable checkout. Resume the same bounded work from those facts. Establish the state of an interrupted command before retrying it. Target concurrent offline pytest across worktrees by giving each run exclusive ownership of its test database and outputs. Keep the existing guard on the shared database until the isolated route is proven. | Spring workspace rules and native Git/Codex worktrees. The active task summary records resume facts. |
| **Scripted acceptance and check lifetimes.** Shipped instructions map deterministic criteria to assertions and distinguish lasting regressions, maintained targeted checks, and one-off validation. [Scripted acceptance][acceptance] · [DevGuide #48][dg48] | **Keep.** For each material behavior, identify the Spring test or reproducible assertion that proves it. Reuse the native test framework. Decide whether any new check should become a regression, a maintained targeted check, or a one-off repro. Run deterministic checks automatically and return failures to repair. Ask for acceptance only for UI presentation changes. An owner-only prerequisite remains a separate action from acceptance. | A concise rule in `AGENTS.md` and the verification skill. Spring's test suite and task evidence hold the assertions. |
| **Cheap checks and repair.** DevGuide ships early review with partial evidence, same-flight repair, and proof of unchanged whole-check coverage. A cheaper iterative scheduling policy is still open. [Early review tests][early-tests] · [Applicability tests][applicability-tests] · [DevGuide #94][dg94] · [DevGuide #112][dg112] | **Adapt.** Start with applicable cheap checks and targeted diagnosis. Fix the cause of red results and preserve the original failure. Run required broad checks when the candidate is stable and eligible. Reuse a whole result only when the command, relevant inputs, environment and required coverage still match. Keep failed, missing, or stale evidence visible. A filtered pass is scoped coverage. Continue in-scope local repair without fixed Spring flight quotas. Measure reruns and contention before adding scheduling logic. | Spring-owned gates and freshness checks in [#3][gates]. The verification skill explains sequencing and repair. |
| **Evidence tied to the actual candidate.** Shipped results retain command output, source and environment identity, counts, and provenance. Content-identical commits and selected integrations may preserve applicable evidence when the proof holds. [Output proof][output-proof] · [Source continuity tests][continuity-tests] | **Adapt.** Keep the actual command, source or diff identity, relevant environment and inputs, outcome, coverage and skips, and a pointer to the original evidence. Preserve its original identity when carrying a result forward. Record uncertainty or rerun when relevant inputs cannot be established. | Existing Spring check outputs and a concise run summary. Add only the fields needed to make the parity and freshness assertions testable. |
| **Independent code and evidence reviews.** The shipped route records real reviewer findings and derives verdicts. Early CODE review can examine a candidate before full gates. Final EVIDENCE review verifies results and current review coverage. Explicit profiles for both reviewers are an open proposal. [Review contract][reviews] · [Verdict implementation][verdict] · [DevGuide #114][dg114] | **Keep the two roles and adapt their timing.** For nonvisual work, ask for independent CODE review after cheap checks and before expensive gates. For owner-facing UI, request interactive HTML approval immediately after the cheap checks, then run the CODE review. Final EVIDENCE review checks actual current coverage and repair dispositions. Re-review affected code after material fixes. Preserve the reviewer's findings and severity. A blocker returns to repair, a concern calls for owner direction before landing, and a missing review leaves the required coverage pending. | Portable review criteria and severity rules linked from `AGENTS.md`. Codex role files handle invocation. Record the observed reviewer profile when available. |
| **Separate owner judgment and preview evidence.** DevGuide ships an interactive candidate handoff, a distinct informational card, and scoped owner decisions. [Preview contract][preview] · [Presentation behavior][presentation] · [DevGuide #5][dg5] | **Adapt.** For owner-facing UI, present a working interactive HTML preview with the exact route and synthetic fixture identity immediately after cheap checks, then pause for current owner approval. Show renders only when the owner explicitly requests them. Any subsequent surface edit requires a fresh preview and approval. Run deterministic behavior tests automatically. Run VisualQA and its findings/freshness check as expensive authoritative gates after the checkpoint. Respect Spring's repository and application-access boundary when preparing or verifying previews. | Spring `AGENTS.md`, UI preview runbook, and Spring-owned VisualQA and findings reader. |
| **Delivery and recovery after an ambiguous effect.** DevGuide ships observed GitHub delivery and repair, including head and check verification and protected-route handling. Its standing landing authority is the model selected for SpringDev. [Delivery contract][delivery] · [Observer implementation][observer] · [DevGuide #23][dg23] | **Adapt.** Read the actual head, target, protections and required checks before an authorized effect. After a failed or ambiguous request, observe the provider before retrying. Report the result actually verified. Use the selected DevGuide-style standing authority for ordinary landing and apply the verdict routes below. Retain the applicable owner instruction and scope. Keep effects beyond that scope, including deploys, subject to their own authority. | Spring Git and delivery guidance in `AGENTS.md` and the PR procedure. GitHub and Spring checks supply the effect evidence. |
| **CI according to the repository.** Shipped DevGuide uses its own configured CI and retains attempt provenance. Full no-CI consumer delivery is active upstream work. [DevGuide CI config][ci-config] · [CI contract][ci] · [DevGuide #111][dg111] | **Adapt the policy.** Verify actual Spring repository and provider requirements at delivery time. Report CI as inapplicable only when it is intentionally absent and no provider rule requires it. Treat misconfigured or missing required CI as a gap. Account for required automatic CI triggers and honor the standing grant's named effects and spending limits. | Delivery guidance and [#5 pilot acceptance][pilot]. Keep Spring local checks independently verifiable. |
| **Informational status and handoff.** Shipped DevGuide projects a small dated view from retained evidence and supports private local and SSH viewing. Installed browser-route recovery is open upstream. [Status contract][status] · [Card projection][card] · [DevGuide #46][dg46] · [DevGuide #115][dg115] | **Adapt after the pilot.** Summarize linked issue, candidate, latest checks, verdict and next owner action. Separate freshness from connection health, label an unavailable view, and keep the application preview distinct. Use chat as the fallback. Verify publication, forwarding, and rendering separately on the actual airJoker-to-mac-mini route. | Read-only [#6 card prototype][card-issue]. The owner makes decisions in chat or the existing authorized channel. |
| **Private evidence, retention, and cleanup.** DevGuide ships bounded capture, local original output and retention policy, safe reclamation, and a storage inventory. Host collection coverage is limited to observed sources. [Capture limits][capture] · [Retention contract][retention] · [Cleanup guards][cleanup] · [DevGuide #110][dg110] | **Adapt the boundary and defer automation.** Keep selected failure output and owner and reviewer records in existing approved private locations, with only decision-relevant summaries on the card or tracker. Record partial or unavailable evidence. Separate landing from cleanup. Confirm ownership, inactivity, containment, and preserved evidence before any separately authorized reclamation. Carry Spring's historical FlightCheck reader and recovery obligations through the cutover. | Evidence and handoff guidance. Existing Spring storage and authorization policy govern cleanup. |

## Differences to resolve in the Spring cutover

| Decision | Recommended Spring behavior |
| --- | --- |
| **Review timing and UI.** DevGuide's standard sequence places early CODE review before UI validation. Spring's published owner-facing UI path holds formal review, authoritative focused and full tests, VisualQA and delivery until current owner acceptance. | Use the owner-selected order for UI work. Cheap checks lead directly to interactive HTML approval, then CODE review and expensive authoritative gates, including VisualQA when applicable. Nonvisual work skips the presentation checkpoint. All deterministic failures return to automated diagnosis and repair. [Spring preview rule][spring-agents] · [DevGuide workflow][workflow] |
| **Approving verdict and landing.** DevGuide's standing #39 authority can land certain verdicts automatically. Spring requires current task authority for the named GitHub and deployment effects. | Replace Spring's per-effect landing approvals at cutover with the DevGuide verdict and standing-authority policy below. Record the review result separately from the applicable authority. [DevGuide #39][dg39] · [Spring operating mode][spring-claude] |
| **Repairs, budgets, and gate reuse.** DevGuide's local loop has no fixed cycle quota, while the published Spring FlightCheck workflow can enforce per-flight limits. | Carry over targeted repair and conservative freshness. Remove Spring's fixed time, review-cycle and repair-iteration quotas from the new workflow. Measure cost and time without using them to stop in-scope local repair. Honor explicit holds and actual access, effect, and spending limits. [DevGuide workflow][workflow] · [Spring FlightCheck adapter][spring-adapter] |
| **Runtime and retirement.** Spring #454 prepared an installed DevGuide migration with useful shadow evidence and a return rehearsal. | Reuse the shadow catalog, Spring-native commands, and historical reader work as applicable. Agree with the Spring owner on the authoritative path during the pilot, the acceptance needed for cutover, and disposition of the installed-DevGuide candidate. Preserve the legacy evidence and return path as recorded. [Spring #454][spring454] · [SpringDev #2][cutover] |
| **Instruction consolidation.** Codex-facing Spring guidance currently links into substantive `CLAUDE.md` rules. | Extract agreed shared rules to `AGENTS.md` and put longer procedures in linked docs and focused skills. Make `CLAUDE.md` exactly one line, `@AGENTS.md`. Update old anchors, skills, roles and policy tests together. Use short descriptive skill names and qualify only actual collisions. [Codex inventory][inventory] · [SpringDev #4][codex-workflow] |

## Owner decisions for landing

The final independent EVIDENCE review supplies the current verdict after all applicable expensive gates pass. Use DevGuide's standing authorization model for the ordinary SpringDev landing path established at cutover. Honor repository protections, any applicable UI approval, required CI, spending limits, and explicit holds. Provider and tool permissions still apply. The owner selected one SpringDev tracking addition for nits. [DevGuide review routes][reviews] · [DevGuide delivery policy][delivery]

| Final review state | Action |
| --- | --- |
| `APPROVE` | Begin landing automatically once the current authoritative gates and final review are complete. |
| `APPROVE_WITH_NITS` | Update existing board items or create and add items for the nits, then begin landing automatically. Treat nits as follow-up work. |
| `APPROVE_WITH_OBSERVATIONS` | Present the actual observations and pause for explicit owner approval to land. This is a delivery decision separate from UI presentation approval and deterministic acceptance. Retain the owner's decision at its actual scope. |
| `REVISE` | Return to plan and implementation for affected repair, validation, and independent review. |
| Incomplete or missing current review | Keep landing pending until the required independent review is complete. |

## Concurrent pytest across worktrees

**Recommendation.** Allow independent offline pytest invocations to overlap across Spring worktrees once they have isolated test resources. Spring currently derives one PostgreSQL test database from the effective OS account, even when the worktree differs. The current lock protects that shared database. With the same database name, one run can migrate or flush the shared database, or drop it during teardown, while another is using it. The result can be a false failure or a false pass. Spring's bootstrap documents a prior collision. [Test environment implementation][spring-test-env] · [Pytest bootstrap][spring-pytest] · [Spring #454][spring454]

- **Isolation.** Start with a fresh, validated test database per invocation, using the existing local PostgreSQL instance and unprivileged test role. Enforce the exact assigned database identity as well as the disposable-name, loopback, role and offline network guards. Scope scratch, reports, VisualQA artifacts, any live-server ports, and evidence to the run or its exclusive worktree. The initial design runs independent pytest invocations across worktrees. [Django parallel test isolation][django-parallel] · [pytest-django database configuration][pytest-db]
- **Cost and retry.** The main expected cost is duplicate database setup and contention for CPU, memory, disk, and PostgreSQL connections. Compare wall time to finish both worktrees against serial execution, including setup and retries. If contention invalidates a run, preserve the failure and rerun the affected gate with clean isolated state or alone. Independently valid results can still carry forward under the existing proof rules. If database setup dominates, evaluate a separately locked reusable database per worktree with schema-change invalidation. [pytest-django database reuse][pytest-db]
- **Proof before cutover.** In [SpringDev #3][gates], overlap database-backed tests from two linked worktrees on mac-mini. Verify each reaches its own database, sees only its own data and expected schema, and produces evidence bound to the right run. Exercise a schema difference and interruption of one run while the other continues. Verify teardown touches only the database owned by that run and leaves orphaned resources identifiable. Exercise an applicable VisualQA run and its reader with the same isolation boundary. Use the current serial path for authoritative results until the parallel route passes these checks.

## Practices and proposals outside the first implementation

The open issues below are grouped by the decision they inform. Where a proposal contributes a useful acceptance criterion, its upstream implementation remains separate from SpringDev.

| DevGuide proposals | SpringDev disposition |
| --- | --- |
| [#112][dg112] redundant validation, [#114][dg114] reviewer profiles, [#111][dg111] optional consumer CI, [#115][dg115] browser-route recovery | **Adapt selectively.** Use targeted repair and measure reruns, record the effective reviewer settings, honor actual CI requirements, and verify the selected viewing route. Choose any reviewer defaults for Spring separately. DevGuide #111 is Active upstream. The other three are Ready. |
| [#6][dg6] optional VisualQA producer | **Defer extraction.** Keep the Spring producer, fixtures, and findings reader in the parity matrix. Revisit extraction when a real second consumer and a parity plan justify it. |
| [#38][dg38], [#42][dg42], [#69][dg69], [#80][dg80], [#102][dg102] card details, fallback identity, finding counts, and cached proof | **Adapt the display principles.** Preserve candidate identity on disconnect and report only known evidence. Keep the first card small. Defer commit-history polish, cross-phase aggregation, and cached proof machinery unless the Spring card needs them. |
| [#60][dg60], [#100][dg100], [#105][dg105], [#106][dg106] delivery wording, serial task descriptions, adapter authority, and retained-history performance | **Keep the principles and defer mechanics.** Describe verified effects and current scope accurately. Keep authority attached to the actual instruction. Revisit adapter continuity and retention performance if Spring's chosen route has those problems. |
| [#16][dg16] expanded capture, [#26][dg26] cross-platform reclamation, [#50][dg50] worktree naming and setup, [#53][dg53] combined-delivery cleanup | **Defer automation.** Keep durable paths and private minimal evidence. Use existing worktree tools and confirm actual ownership before cleanup. |
| [#24][dg24] post-MVP epic, [#30][dg30] release epic, and [#31][dg31] transfer, [#32][dg32] licensing, [#33][dg33] packaging, [#34][dg34] Spring adoption, [#35][dg35] Windows and Claude pilot, and [#36][dg36] public launch | **Leave upstream.** These are DevGuide product and distribution work. The small SpringDev pilot tests a Codex workflow and has its own acceptance. [SpringDev #5][pilot] |

Shipped DevGuide infrastructure also includes the Rust CLI and private installer, durable flight ledgers, private capture and retention tools, integration and parallel-worker coordination, and a benchmark kit. **Leave these out of the initial SpringDev implementation.** Their concepts are useful references, especially recovery, provenance, and measurement. Use existing Spring commands and a bounded pilot summary first. The benchmark guide treats a single pilot as a case study, so report observed duration, interruption and defect detection without extrapolating a general speed or cost gain. [Setup][setup] · [Parallel increments][parallel] · [Benchmark guide][benchmark]

## Handoff for owner review

I recommend the initial slice of explicit activation, scripted acceptance and in-scope repair, interactive HTML approval for UI changes immediately after cheap checks, independent code and evidence reviews, and automatic landing on the eligible DevGuide verdicts. Validate isolated pytest concurrency under #3 and prove the workflow on one low-risk change before building the card.

Carry the recorded owner decisions and any subsequently agreed dispositions into [#2][cutover], check parity and freshness criteria into [#3][gates], activation and reviewer behavior into [#4][codex-workflow], measured observations into [#5][pilot], and card scope into [#6][card-issue]. The audit records the source and rationale once. Each issue should get only the criteria it owns.

[inventory]: codex-workflow-inventory.md
[issue]: https://github.com/spring-labs-inc/SpringDev/issues/8
[cutover]: https://github.com/spring-labs-inc/SpringDev/issues/2
[gates]: https://github.com/spring-labs-inc/SpringDev/issues/3
[codex-workflow]: https://github.com/spring-labs-inc/SpringDev/issues/4
[pilot]: https://github.com/spring-labs-inc/SpringDev/issues/5
[card-issue]: https://github.com/spring-labs-inc/SpringDev/issues/6
[spring454]: https://github.com/spring-labs-inc/Spring/issues/454
[spring-agents]: https://github.com/spring-labs-inc/Spring/blob/60da2477/AGENTS.md
[spring-claude]: https://github.com/spring-labs-inc/Spring/blob/60da2477/CLAUDE.md
[spring-adapter]: https://github.com/spring-labs-inc/Spring/blob/60da2477/.flightcheck/adapter.json
[spring-test-env]: https://github.com/spring-labs-inc/Spring/blob/60da2477/spring/test_env.py
[spring-pytest]: https://github.com/spring-labs-inc/Spring/blob/60da2477/spring/pytest_bootstrap.py
[django-parallel]: https://docs.djangoproject.com/en/6.0/ref/django-admin/#cmdoption-test-parallel
[pytest-db]: https://pytest-django.readthedocs.io/en/stable/database.html
[board]: https://github.com/users/jeffmaddocks/projects/3
[dg-agents]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/AGENTS.md
[product]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/PRODUCT.md
[workflow]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/WORKFLOW.md
[activation]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/WORKFLOW.md#activation
[acceptance]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/WORKFLOW.md#scripted-acceptance-and-check-lifetimes
[setup]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/SETUP.md
[activation-tests]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/scripts/test-activation.py
[worker-tests]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/tests/worker_route.rs
[recovery-tests]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/tests/recovery_route.rs
[early-tests]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/tests/early_review_route.rs
[applicability-tests]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/tests/check_applicability_route.rs
[output-proof]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/src/core/output_proof.rs
[continuity-tests]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/tests/source_continuity_route.rs
[reviews]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/REVIEWS.md
[verdict]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/src/core/verdict.rs
[preview]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/PREVIEW.md
[presentation]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/PRESENTATION.md
[delivery]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/DELIVERY.md
[observer]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/src/core/delivery/observer.rs
[ci-config]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/.devguide/ci.json
[ci]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/CI.md
[status]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/STATUS.md
[card]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/src/core/status_card.rs
[capture]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/CAPTURE.md
[retention]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/RETENTION.md
[cleanup]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/CLEANUP.md
[parallel]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/PARALLEL.md
[benchmark]: https://github.com/jeffmaddocks/DevGuide/blob/25163b2/docs/BENCHMARK.md
[mvp]: https://github.com/jeffmaddocks/DevGuide/issues/8
[dg5]: https://github.com/jeffmaddocks/DevGuide/issues/5
[dg6]: https://github.com/jeffmaddocks/DevGuide/issues/6
[dg16]: https://github.com/jeffmaddocks/DevGuide/issues/16
[dg23]: https://github.com/jeffmaddocks/DevGuide/issues/23
[dg24]: https://github.com/jeffmaddocks/DevGuide/issues/24
[dg26]: https://github.com/jeffmaddocks/DevGuide/issues/26
[dg30]: https://github.com/jeffmaddocks/DevGuide/issues/30
[dg31]: https://github.com/jeffmaddocks/DevGuide/issues/31
[dg32]: https://github.com/jeffmaddocks/DevGuide/issues/32
[dg33]: https://github.com/jeffmaddocks/DevGuide/issues/33
[dg34]: https://github.com/jeffmaddocks/DevGuide/issues/34
[dg35]: https://github.com/jeffmaddocks/DevGuide/issues/35
[dg36]: https://github.com/jeffmaddocks/DevGuide/issues/36
[dg38]: https://github.com/jeffmaddocks/DevGuide/issues/38
[dg39]: https://github.com/jeffmaddocks/DevGuide/issues/39
[dg42]: https://github.com/jeffmaddocks/DevGuide/issues/42
[dg46]: https://github.com/jeffmaddocks/DevGuide/issues/46
[dg48]: https://github.com/jeffmaddocks/DevGuide/issues/48
[dg50]: https://github.com/jeffmaddocks/DevGuide/issues/50
[dg53]: https://github.com/jeffmaddocks/DevGuide/issues/53
[dg60]: https://github.com/jeffmaddocks/DevGuide/issues/60
[dg69]: https://github.com/jeffmaddocks/DevGuide/issues/69
[dg80]: https://github.com/jeffmaddocks/DevGuide/issues/80
[dg94]: https://github.com/jeffmaddocks/DevGuide/issues/94
[dg100]: https://github.com/jeffmaddocks/DevGuide/issues/100
[dg102]: https://github.com/jeffmaddocks/DevGuide/issues/102
[dg105]: https://github.com/jeffmaddocks/DevGuide/issues/105
[dg106]: https://github.com/jeffmaddocks/DevGuide/issues/106
[dg110]: https://github.com/jeffmaddocks/DevGuide/issues/110
[dg111]: https://github.com/jeffmaddocks/DevGuide/issues/111
[dg112]: https://github.com/jeffmaddocks/DevGuide/issues/112
[dg114]: https://github.com/jeffmaddocks/DevGuide/issues/114
[dg115]: https://github.com/jeffmaddocks/DevGuide/issues/115
