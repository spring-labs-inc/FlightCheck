# Status in interactive Codex

Use the status card only within a selected workflow. On first activation with a configured publisher, allocate a task ID, private snapshot, and available loopback port. Record them with the workflow, start the configured listener, and reuse the same task route on resume. Publish a short task title and summary, the current candidate identity, and a verdict recorded for that exact candidate. On any candidate change or unresolved review, publish `Pending` immediately.

## Publish work links and evidence

Use the publisher's `--details` option for curated JSON updates. At activation publish the agreed issue and epic links, and add the verified PR link when it exists. On each check start and outcome, publish the latest check summaries from recorded native evidence, including counts only when reported. When the project uses CI and the workflow observes a provider result, publish its PR or post-merge status with the checked commit, candidate, observation time, and run URL when known.

Publish a `stages` map using the SpringDev stage names. Mark stages completed after their requirements are met, skipped when they do not apply, and current at the actual active stage. On a repair return, update the map to show the return and the stages whose evidence remains valid. On a candidate change, provide the newly verified map alongside the candidate or leave stages unpublished until verified.

Append iteration events for actual repair returns, check reruns, and independent review outcomes. Reuse IDs from the underlying records so a resume or retry cannot duplicate history. Keep earlier events and record new attempts separately. The active workflow publishes updates from parallel checks through the same task snapshot. Keep raw evidence and secrets private. Treat all card content as informational.

## Open or reuse the card

On activation and resume, check publication on the checkout host. Verify that the task page and its `status.json` respond with the expected task. Restore a stopped listener using the recorded local URL and port if available and permitted. A successful host request verifies publication.

When the desktop browser controls are available, inspect the current chat's built-in browser for the exact task route. The forwarded origin may differ from the checkout URL. Match the full `/task/<id>/` path on loopback. Use the task card's `task_tab.py --task <id>` decision helper if installed. Provide the observed inventory as JSON on stdin with `tabs` (objects with `id`, `url` and `visible` when known), `can_reveal`, and `can_open`. Use `tabs: null` if inventory is unavailable. Set a capability to true only if the client exposes the action.

| Browser state | Action |
| --- | --- |
| The matching card is visible | Leave it in place. Reload that tab only if its route needs recovery. |
| A matching tab exists and is hidden or inactive | Reveal or select the existing tab using the desktop controls. |
| Tab inventory is available and the card is absent | Open the recorded loopback URL visibly in the built-in browser. |
| Inventory or required controls are unavailable | Refer the owner to the status link in the opening reply. |

An existing matching tab with unknown visibility also uses the fallback. Ask the owner to select it. Recheck the inventory before opening a new tab when navigation is still settling.

Check the displayed task, route diagnostic, and `Snapshot rendered` separately. On a forwarded connection reset, restore the checkout-host listener first, then reload the existing tab. If the client needs a fresh forward, use its supported navigation or direct the owner to the opening link. Avoid creating duplicate tabs when the original tab still exists. Report browser verification only from the desktop view or an owner's observation.

## Opening and closing replies

Put the status line at the top of the opening workflow reply when the owner first invokes SpringDev for a flight. Put the closing status block at the bottom of the reply that ends that flight. Use the same task URL at both boundaries. Leave the status block out of intermediate updates, approval pauses, repairs, resumes of the same flight, and ordinary chat.

Use the publisher's `--chat-phase start` or `--chat-phase end` output, or format the line as `SpringDev: [&lt; status /&gt;](TASK_URL)`. When no task URL is usable, leave the label as plain text. At the end, put `Verdict: <actual verdict>` on its own line below the status line if the current candidate has a recorded verdict. Leave that line out when the verdict is pending. Keep publishing snapshot updates without `--chat-phase` between the two replies.
