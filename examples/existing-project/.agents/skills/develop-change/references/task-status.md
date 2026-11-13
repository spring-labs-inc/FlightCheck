# Browser status throughout a selected flight

Use the standard browser card in every selected workflow, including Codex desktop/CLI and Claude TUI. On activation, allocate a task ID, private snapshot and available loopback port. Record them, start the listener and reuse the same task URL on resume. Publish the current candidate and only its actual verdict. On a candidate change or unresolved review, publish `Pending` immediately.

Before the first TUI reply, proactively tell the user: "Open the live FlightCheck card in your regular browser using the status link below; you can continue working in the terminal." Do not wait for a request to install or render it. Browser controls are optional; a text/ASCII replacement is unnecessary.

## Prepare and check every controller reply

Use the installed `.flightcheck/docs/status.md` for the configured interpreter, state directory and command paths. In the FlightCheck source checkout, the portable commands are:

```sh
python3 -B status-card/reply.py prepare --task TASK_ID --title "Task title" --details /private/flight-details.json
python3 -B status-card/reply.py check --task TASK_ID --phase update --reply-file /private/reply.txt
```

Initialize the private details file before the first reply. Declare all nine stages, one honest current stage, `check_plan`, and one current pending observation per applicable check (empty counts until real results exist). Include known issue/PR links or explicit `links_unavailable` reasons; do not invent work links. An empty check plan requires a `checks_unavailable` reason. Publishing a new nonempty `check_plan` removes the previous no-checks reason unless the update explicitly supplies a reason too; that contradictory combination remains incomplete. A planned unavailable check needs its own `reason`. See the complete [details schema](https://github.com/spring-labs-inc/FlightCheck/blob/main/docs/status-card.md#publish-work-links-and-evidence) in the upstream repository; installed projects use the schema below.

```json
{
  "stages": {
    "Plan": "current", "Implement": "pending", "Cheap Tests": "pending",
    "Interactive UI Approval": "pending", "Independent Code Review": "pending",
    "Authoritative Gates": "pending", "Skeptical Evidence Review": "pending",
    "Final Verdict": "pending", "PR & Merge": "pending"
  },
  "check_plan": ["Project checks"],
  "checks": [{"name": "Project checks", "state": "pending", "candidate": "CURRENT_CANDIDATE",
              "observed_at": "2026-01-01T00:00:00Z", "counts": {}}],
  "links": [],
  "links_unavailable": {"issue": "No tracked issue for this task.", "pr": "No PR yet."}
}
```

Use the actual current candidate and observation time, agreed gate names and known links. Later updates may omit unchanged sections. On candidate changes refresh the stage map and check observations explicitly. A title-only card is incomplete: active-flight HTTP returns 503, the existing browser view shows Snapshot unavailable, and prepare/check fail with actionable completeness diagnostics while retaining the URL. An observed listener is not readiness. Same-candidate changed check/CI observations clear old verdicts too. Low-level `--mode minimal` is only a labeled transport fixture and never active-flight readiness.

`prepare` publishes and verifies the checkout-host task page and current task/candidate snapshot, restoring a stopped listener on the recorded port. It returns JSON with `footer`, browser `guidance`, publication state and separate unobserved browser reachability/rendering. Put the exact planned controller reply in a private file; `check` verifies its footer and current publication before sending. A zero exit means this explicit check passed, not that the client intercepted a message.

Use this sequence for **every user-facing controller reply**: start, progress/update, approval pause, blocker, repair, resume and final handoff. The `--phase` names are `start`, `update`, `approval`, `blocker`, `repair`, `resume`, and `end`; they share the same final-footer requirement. Put any actual current verdict above the link. Keep the footer in its own last paragraph, outside code fences. `--chat-phase start`, `update`, and `end` on the low-level publisher also keep the link last; only `end` adds a current verdict above it.

If publication or routing fails, report the concrete unavailable state and repair guidance with the known task link; if no URL was established, use the returned plain status label. A nonzero guard result never means live/ready. Keep the same route; do not silently allocate another port, omit the status, or broaden the bind address.

Ordinary chat and raw reviewer JSON are excluded. `reply.py --context ordinary` and `--context reviewer` bypass before reading a draft, invoking Git/services or writing state. These commands return a separate diagnostic; they never rewrite the caller's reply. Do not append the diagnostic or a footer to native reviewer JSON. Reviewers must not run the controller commands or hooks at all; establish the enforced read-only and hook-disabled boundary separately.

## Local and remote browser routes

`--execution auto` uses common SSH/container markers as hints; use `--execution local` or `remote` when the environment is ambiguous. On a remote checkout, host HTTP success alone leaves the browser route unavailable. Arrange an approved loopback forward or use the client's supported preview forwarding, then pass its exact browser-facing loopback task URL with `--user-url http://127.0.0.1:LOCAL_PORT/task/TASK_ID/`. The listener remains on `127.0.0.1`; never bind it to a public interface. Preserve the prepared browser URL on every reply and resume. A changed execution context needs preparation again; a conflicting established URL needs explicit reconciliation.

The remote command prints an SSH forwarding example with placeholders; it does not connect or grant permission. The check validates the declared route, not whether the user's machine actually reached it. Record host HTTP, client forwarding/reachability, and browser rendering as distinct observations. Only report rendering after desktop inspection or an owner observation.

## Client capabilities and hooks

The portable guard is an explicit controller pre-send check, usable without modifying client permissions or settings. It does not intercept streaming, intermediate or interrupted messages automatically. The existing Codex Stop guard checks only the event it receives. A Stop hook alone is not proof of coverage for progress, permission pauses, interruptions or reviewer isolation. Do not enable new hooks by default or translate client hook schemas mechanically. If a client offers a message adapter, probe its actual event coverage and keep executable hooks disabled in read-only reviewers before claiming enforcement. Full native client qualification remains in #14.

## Publish work links and evidence

Use the publisher's `--details` option for curated JSON updates. At activation publish the agreed issue and epic links, and add the verified PR link when it exists. On each check start and outcome, publish the latest check summaries from recorded native evidence, including counts only when reported. When the project uses CI and the workflow observes a provider result, publish its PR or post-merge status with the checked commit, candidate, observation time, and run URL when known.

Give each work link a short reference such as `#12`. Include the title, a brief description, and the tracker's `updated_at` and `created_at` times when available. The card shows the title and description when the user selects the item. Links, local checks, CI observations, and history appear newest first across their section. Use original observation and modification times when available so the order reflects the latest activity.

Publish the checkout's short display name as `worktree`. Keep the filesystem path in the private workflow record. Update the name if the task moves to another checkout.

Publish a `stages` map using the fixed FlightCheck stage names and order from the README. Mark stages completed after their requirements are met, skipped when they do not apply, and current at the actual active stage. Stages after the current stage cannot remain completed. The publisher records state-change times in `stage_updated_at` while preserving the defined sequence. Supply original stage times in that map when available. On a repair return, update the map to show the current stage and reset later completions to pending. On a candidate change, provide the newly verified map alongside the candidate or leave stages unpublished until verified.

For a linked issue with a recorded flight association, include that flight's task ID as `flight`. For other flights, publish candidate-bound stages in `tracked_flights` using the actual workflow records. Refresh those observations on stage or candidate changes. If the new candidate has no recorded stage, clear the previous stage for that flight.

Append iteration events for actual repair returns, check reruns, and independent review outcomes. Reuse IDs from the underlying records so a resume or retry cannot duplicate history. Keep earlier events and record new attempts separately. The active workflow publishes updates from parallel checks through the same task snapshot. Keep raw evidence and secrets private. Treat all card content as informational.

## Optional embedded-browser integration

On activation and resume, check publication on the checkout host. Verify that the task page and its `status.json` respond with the expected task. Restore a stopped listener using the recorded local URL and port if available and permitted. A successful host request verifies publication.

When the desktop browser controls are available, inspect the current chat's built-in browser for the exact task route. The forwarded origin may differ from the checkout URL. Match the full `/task/<id>/` path on loopback. Use the task card's `task_tab.py --task <id>` decision helper if installed. Provide the observed inventory as JSON on stdin with `tabs` (objects with `id`, `url` and `visible` when known), `can_reveal`, and `can_open`. Use `tabs: null` if inventory is unavailable. Set a capability to true only if the client exposes the action.

| Browser state | Action |
| --- | --- |
| The matching card is visible | Leave it in place. Reload that tab only if its route needs recovery. |
| A matching tab exists and is hidden or inactive | Reveal or select the existing tab using the desktop controls. |
| Tab inventory is available and the card is absent | Open the recorded loopback URL visibly in the built-in browser. |
| Inventory or required controls are unavailable | Proactively offer the regular browser through the footer in every controller reply. |

An existing matching tab with unknown visibility also uses the fallback. Ask the owner to select it. Recheck the inventory before opening a new tab when navigation is still settling.

Check the displayed task, route diagnostic, and `Snapshot rendered` separately. On a forwarded connection reset, restore the checkout-host listener first, then reload the existing tab. If the client needs a fresh forward, use its supported navigation or direct the owner to the opening link. Avoid creating duplicate tabs when the original tab still exists. Report browser verification only from the desktop view or an owner's observation.

The portable reply rule above applies whether embedded controls are available or not. A desktop tab is an optional presentation of the same task snapshot.
