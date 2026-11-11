# Developing FlightCheck

Every implementation task in this Git checkout automatically selects FlightCheck. This includes code, docs, tests, configuration, and edits to the adoption examples. Start or resume a flight before editing. Read-only questions and reviews use their normal entry points. This file governs development of FlightCheck itself. Adopters use the opt-in instructions under `examples/existing-project/`.

Follow the [development workflow](examples/existing-project/docs/development-workflow.md) and [shared skill](examples/existing-project/.agents/skills/develop-change/SKILL.md). Use these repository settings for the selected workflow.

- Record the task scope, acceptance criteria, and authorized delivery before editing. Use `git diff --check` and focused checks first. Run `python3 -B -m unittest discover -s tests` with pytest and loopback permission for the full contributor suite. Record evidence with the shared recorder and handoff when preparing the review packet.
- Use the [CODE](examples/existing-project/.codex/agents/workflow-code-reviewer.toml) and [EVIDENCE](examples/existing-project/.codex/agents/workflow-evidence-reviewer.toml) roles in separate read-only sessions when the workflow calls for them. Record only verdicts received for the current candidate.
- Start the task card from the repository root with `python3 -B status-card/maintainer.py card --task TASK_ID --title "Task title"`. Pick a unique task ID and retain it on resume. For an issue, use an ID such as `issue-36`. Keep the card and evidence in private storage outside the checkout.
- Before any user-facing reply that reports implementation work, including an approval pause after edits, run the same card command from the implementation checkout to publish the current candidate and verify the listener. Paste its exact output as the last line of the reply in its own paragraph, outside any code block. Put any verdict above that line. Use the same URL on resume. If publication fails, restore the listener or resolve the permission blocker before reporting completion.

The [maintainer card setup](docs/status-card.md#maintainer-implementation-replies) covers state storage, hook trust, and verification.
