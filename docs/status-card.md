# FlightCheck status cards

## Current task

The task card publishes a short summary and the verdict for the current candidate. Each task has one stable loopback route. The card shows `Pending` until a verdict is recorded for that exact candidate. The README screenshot shows this view with synthetic task data. In this repository, follow the [maintainer instructions](#maintainer-implementation-replies). Adopters can enable the card for selected workflows.

For adoption in another project, keep this `status-card/` directory available to the workflow and record its path in the project setup. Keep the snapshot in a private directory outside the checkout. Assign a unique task ID and an available port per task. Record the directory, task ID, and port with the selected workflow so a resume uses the same route. Only the active workflow writes that task's curated snapshot. Keep raw output and secrets out of its title and summary.

```sh
task_dir="$(mktemp -d)"
task_id=example-task
task_url="http://127.0.0.1:8767/task/$task_id/"
python3 -B status-card/task_status.py --file "$task_dir/status.json" \
  --task "$task_id" --title "Example task" --url "$task_url"
python3 -B status-card/serve.py --port 8767 --task-status "$task_dir/status.json"
```

In a durable setup, use an owner-only directory that survives the chat session and keep the loopback listener running while the card is needed. Re-run the publisher with the same file and task ID when the candidate or review changes. Supply `--candidate` with the current identity. Supply `--verdict` and `--verdict-candidate` together only after the verdict is recorded. The publisher replaces the snapshot atomically. The task page polls the read-only endpoint and suppresses the verdict when the task, candidate binding, or connection cannot be verified.

Use `--chat-phase start` to format the status line for the top of the opening reply. Use `--chat-phase end` to format the status block for the bottom of the closing reply. Only the `< status />` label links to the task card. The closing block puts any recorded verdict for the current candidate on a separate line below the link. Publish intermediate snapshot updates without a chat phase.

The [Codex skill instructions](../examples/existing-project/.agents/skills/develop-change/references/task-status.md) describe how the selected workflow uses the desktop controls on activation and resume. The optional [tab decision helper](../status-card/task_tab.py) returns the next action from observed tabs and capabilities. Codex uses the available browser controls to carry it out. The checkout-host response, desktop forwarding, and browser render are separate checks. CLI and clients without usable browser controls can continue in chat with the same task link. [Codex built-in browser](https://learn.chatgpt.com/docs/browser) · [Remote connections](https://learn.chatgpt.com/docs/remote-connections)

### Publish work links and evidence

Pass `--details /private/path/details.json` to the same publisher command. Use only the sections being updated. For example, a synthetic update for `--candidate candidate-2` could contain:

```json
{
  "worktree": "setup-docs",
  "stages": {
    "Plan": "completed",
    "Implement": "completed",
    "Cheap Tests": "completed",
    "Interactive UI Approval": "skipped",
    "Independent Code Review": "current"
  },
  "links": [
    {"kind": "epic", "label": "#10", "title": "Setup rollout", "description": "Make the project easier to set up.", "url": "https://example.com/issues/10", "created_at": "2026-01-01T09:00:00Z"},
    {"kind": "issue", "label": "#12", "title": "Clarify prerequisites", "description": "Document the tools needed for a clean checkout.", "url": "https://example.com/issues/12", "created_at": "2026-01-01T10:00:00Z", "flight": "setup-followup"},
    {"kind": "pr", "label": "#15", "title": "Document setup tools", "description": "Add the prerequisites to the setup guide.", "url": "https://example.com/pull/15", "created_at": "2026-01-01T12:08:00Z"}
  ],
  "tracked_flights": {
    "setup-followup": {"candidate": "followup-1", "stage_candidate": "followup-1", "stage": "Implement"}
  },
  "checks": [
    {"name": "Project tests", "candidate": "candidate-2", "state": "passed", "observed_at": "2026-01-01T12:10:00Z", "counts": {"passed": 37, "skipped": 2}}
  ],
  "ci": [
    {"kind": "pr", "name": "CI", "candidate": "candidate-2", "commit": "0123456789abcdef", "attempt": 1, "state": "running", "observed_at": "2026-01-01T12:11:00Z", "url": "https://example.com/runs/18"}
  ],
  "events": [
    {"id": "check-run-002", "kind": "rerun", "candidate": "candidate-2", "observed_at": "2026-01-01T12:10:00Z", "summary": "Reran project tests after repairing the failing case."}
  ]
}
```

- **Checkout** appears below Candidate. Supply either `"branch"` with the full branch name or `"worktree"` with the linked worktree's display name. Either field replaces the previous checkout label. Use `"branch": null` to clear it. Omit both fields to keep the previous label. Keep filesystem paths in the private workflow record.
- **Stages** reflect the workflow's recorded progress. Use the nine stage names from the README and the states `completed`, `current`, `skipped`, and `pending`. Supply at most one current stage. Unlisted stages default to pending. Publish the new stage map when the workflow advances or returns for repair. The card keeps the last map for the same candidate and clears it on a candidate change unless the update supplies a new map.
- **Links** come from the agreed scope and recorded PR. Use a short reference such as `#12` for the label. Provide a title and a brief description when available. Selecting an item expands its details on the card. The `>` button opens the destination in a new tab or window. Use HTTPS destinations without credentials or query parameters. Include the tracker's `created_at` timestamp with a timezone when available. Epics come first, followed by issues and then PRs. Each group is ordered newest first. Ties retain their supplied order, and undated links follow the dated links in their group.
- **Linked issue stages** require an explicit `flight` on the issue link. Use the flight's task ID. For the displayed flight, the stage comes from its current candidate and stage map. For another flight, publish its observed candidate, recorded stage, and the candidate that stage applies to in `tracked_flights`. Refresh this map from the workflow records when tracked flights advance or change candidates. If no stage applies to the new candidate, publish only its candidate or omit that flight from the replacement map. The card shows a shared label when several linked issues use the same flight. The main stages always come from the displayed task.
- **Checks** summarize the latest observation per check group from the project's native evidence. Publish starts and outcomes as they occur. For the example capture script, use the `run.json` candidate, start or finish time, status and exit code. Add counts only when the tool reports them. A newer failure, interruption, or incomplete attempt takes the place of an earlier pass. Use `pending`, `running`, `passed`, `failed`, `interrupted`, or `unavailable`.
- **CI** is optional. Publish an observed `pr` or `post-merge` result with the commit the provider checked and the task candidate it belongs to. Include the run URL and attempt when known. Use `pending`, `running`, `passed`, `failed`, `cancelled`, `skipped`, or `unavailable`. The card shows the recorded observation time and does not query the provider.
- **Events** record actual `repair`, `rerun`, or `review` activity with a stable ID from the underlying run or record. An identical event can be published again without adding a row. A conflicting event with the same ID is rejected. The history stays with the private task snapshot on resume.

Each supplied `links`, `checks`, or `ci` list or `tracked_flights` map replaces that section in full. An empty list or map clears it. Omitted sections carry forward. A check or CI row from another candidate shows as stale, and rows carried through a candidate change stay stale until the workflow publishes current evidence. Use `"stale": true` if the workflow invalidates a row for the same candidate. Only the active workflow writes the snapshot, including when several checks produce evidence concurrently. Keep commands, raw logs, credentials, and private paths in the underlying evidence store.

### Rehearse on desktop

Use a synthetic task on both a local checkout and an SSH-connected checkout. Confirm the status link appears at the top of the opening reply and the bottom of the closing reply. Check that ordinary chat, intermediate replies, and resumes of the same flight omit it. Activate the workflow with the card absent, then resume with the card visible and again with its tab hidden. Check that the same task route stays open in one tab. Confirm that the current task and `Snapshot rendered` appear in the desktop view.

Record a verdict for the synthetic candidate, then change the candidate while retaining the old verdict binding in the test input. Confirm the card shows `Pending` and the closing block omits the stale verdict. Stop the listener and check the chat fallback, then restore the original port and reload the same tab. Record host HTTP, the desktop route, and the rendered task as separate observations.

## Maintainer implementation replies

The [root instructions](../AGENTS.md) select FlightCheck for implementation in this repository. Start or resume the card from the implementation checkout. Keep the same task ID for the life of the task.

```sh
python3 -B status-card/maintainer.py card --task example-change --title "Example change"
```

Run the command before an implementation reply and use its output as the reply's last paragraph. The command fingerprints the current checkout, publishes the private snapshot, and verifies the task endpoint. It gets the checkout label from Git. A named branch in the primary checkout shows **Branch** with its full name. A linked worktree shows **Worktree** with its directory name. A detached HEAD in the primary checkout hides the row. On resume the command reuses the recorded port and restores a stopped listener if that port is available. Pass `--summary` and `--details` to update the curated card content. Supply `--verdict` and `--verdict-candidate` together after a verdict for that candidate has been recorded.

The default state directory is `$XDG_STATE_HOME/flightcheck` or `~/.local/state/flightcheck`. If the session restricts that path, set `FLIGHTCHECK_STATE_DIR` to the same absolute, owner-only directory outside the checkout for Codex and its hooks. Use a host that permits IPv4 loopback binds. The listener runs in the background while the card is needed. The maintainer command replaces an older managed listener that drops the checkout label and reuses its port. Its startup log is in the private task directory.

Review and trust the [repository-local hooks](../.codex/hooks.json) in Codex once. The hook compares the checkout to its state at the start of the turn and also checks turns that ran the maintainer card command. If the last reply is missing the current task link, the hook requests a correction once. The root instructions also cover replies sent before the stop hook runs. [Codex hook trust](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)

In a fresh chat here, request a small docs change and open the card from the last line of the reply. Resume the task and verify that the link is the same. In a separate Git checkout with only the adoption example, make the same request and verify that a flight starts only when you select `$develop-change`.

## Synthetic snapshot

The default read-only card shows a completed example with eight sample checks, an independent verdict, and separate presentation and landing decisions.

### View the example card

From the FlightCheck checkout, start the loopback-only server and keep its terminal open.

```sh
python3 -B status-card/serve.py --port 8766
```

Open the card in the Codex desktop browser. The browser can use a different local port when it forwards the route. The footer identifies the stages observed by the page. [Open the card](http://127.0.0.1:8766/)

If the forwarded tab reports `ERR_CONNECTION_RESET`, check the listener on the checkout host first. A task-managed preview process can stop when its session ends. Restart the loopback server, verify that `/` and `/status.json` respond, then reload the forwarded tab. If the tab still resets, reopen the original loopback URL from Codex to establish a fresh route.

| Stage | What to look for | If it fails |
| --- | --- | --- |
| Publication | The server prints its loopback URL. On the checkout host, a GET of `/status.json` returns the curated snapshot. | Check the server output and port. |
| Browser route | The card reports **Forwarded endpoint reached** when the browser-facing port differs from the publication port, or **Endpoint reached** when they match. | If publication works but the page will not open, reopen the server URL in the Codex desktop browser and check its forwarded route. |
| Rendering | The card reports **Snapshot rendered** and shows eight sample gate results and `APPROVE_WITH_NITS`. | If the shell opens but the snapshot is unavailable, check `/status.json` on the checkout host. |

A connection loss retains the last rendered snapshot and labels the route disconnected. A reachable endpoint with unusable data is labeled unavailable. Pending gates have their own section.

The server reads the example data from `status-card/pilot.json` at startup and exposes it through the read-only status endpoint. Use the [current task](#current-task) route to publish evidence for your own workflow.
