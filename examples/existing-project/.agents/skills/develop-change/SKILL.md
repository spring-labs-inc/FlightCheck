---
name: develop-change
description: Run the repository's staged development workflow when the owner explicitly selects it for a bounded task or resumes that work.
---

Read the [project workflow](../../../docs/development-workflow.md) and the applicable repository instructions. Confirm the project setup, scope, acceptance, checkout, and delivery boundary before editing.

Run the configured cheap checks, including fast checks for affected behavior, and resolve failures before interactive HTML approval or conditional early CODE review. Follow the guide for remaining gates, receipt matching, final code and evidence review, and verdict routing. On resume, reconcile the current candidate, original results, owner decisions, and provider state before repeating work.

Use the guide's shared `handoff.py resume` summary before reopening saved evidence. Route an eligible clean resume directly to final review. For an applicable early CODE re-review, use `handoff.py code-review` to route an in-scope repair to the prior read-only reviewer. Build and validate the `handoff.py review` packet before launching the separate final reviewer. Resolve any blocked prerequisites and preserve the original outputs.

On activation or resume in interactive Codex, use the project's configured status card and [chat status instructions](references/task-status.md). Put the status link first in the opening reply and last in the closing reply, with any recorded verdict directly below the closing link.
