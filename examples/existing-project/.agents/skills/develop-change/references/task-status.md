# Status in interactive Codex

Use the status card only within a selected workflow. On first activation with a configured publisher, allocate a task ID, private snapshot, and available loopback port. Record them with the workflow, start the configured listener, and reuse the same task route on resume. Publish only a short task title and summary, the current candidate identity, and a verdict recorded for that exact candidate. On any candidate change or unresolved review, publish `Pending` immediately.

## Open or reuse the card

On activation and resume, check publication on the checkout host. Verify that the task page and its `status.json` respond with the expected task. Restore a stopped listener using the recorded local URL and port if available and permitted. A successful host request verifies publication.

When the desktop browser controls are available, inspect the current chat's built-in browser for the exact task route. The forwarded origin may differ from the checkout URL. Match the full `/task/<id>/` path on loopback. Use the task card's `task_tab.py --task <id>` decision helper if installed. Provide the observed inventory as JSON on stdin with `tabs` (objects with `id`, `url` and `visible` when known), `can_reveal`, and `can_open`. Use `tabs: null` if inventory is unavailable. Set a capability to true only if the client exposes the action.

| Browser state | Action |
| --- | --- |
| The matching card is visible | Leave it in place. Reload that tab only if its route needs recovery. |
| A matching tab exists and is hidden or inactive | Reveal or select the existing tab using the desktop controls. |
| Tab inventory is available and the card is absent | Open the recorded loopback URL visibly in the built-in browser. |
| Inventory or required controls are unavailable | Give the usable task link in chat and let the owner reveal or open it. |

An existing matching tab with unknown visibility also uses the fallback. Ask the owner to select it. Recheck the inventory before opening a new tab when navigation is still settling.

Check the displayed task, route diagnostic, and `Snapshot rendered` separately. On a forwarded connection reset, restore the checkout-host listener first, then reload the existing tab. If the client needs a fresh forward, use its supported navigation or ask the owner to reopen the recorded URL. Avoid creating duplicate tabs when the original tab still exists. Report browser verification only from the desktop view or an owner's observation.

## End the reply

Use the publisher's footer, or format it as `**[SpringDev </> status](TASK_URL) · Verdict: Pending**`. Use the current candidate's recorded verdict when available. When no task URL is usable, use the same footer without a link. Put it on the last line of each interactive workflow reply, including pauses and fallback messages. Keep progress and next steps in chat when publication or browser access is unavailable.
