# SpringDev status cards

## Current task

For a selected Codex workflow, the optional task card publishes a short summary and the verdict for the current candidate. Each task has one stable loopback route. The card shows `Pending` until a verdict is recorded for that exact candidate. The historical pilot is available separately below.

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

- **Worktree** is a short display name for the checkout, shown below Candidate. Keep the filesystem path in the private workflow record. The name carries forward until the workflow publishes a new one.
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

## Historical pilot

The read-only card shows the Contact us pilot's reviewed candidate, eight observed checks, independent verdict, and separate presentation and landing decisions. [Pilot closeout and rollout record](https://github.com/spring-labs-inc/SpringDev/issues/5)

### View the pilot card

From the SpringDev checkout, start the loopback-only server and keep its terminal open.

```sh
python3 -B status-card/serve.py --port 8766
```

Open the card in the Codex desktop browser. The browser can use a different local port when it forwards the route. The footer identifies the stages observed by the page. [Open the card](http://127.0.0.1:8766/)

If the forwarded tab reports `ERR_CONNECTION_RESET`, check the listener on the checkout host first. A task-managed preview process can stop when its session ends. Restart the loopback server, verify that `/` and `/status.json` respond, then reload the forwarded tab. If the tab still resets, reopen the original loopback URL from Codex to establish a fresh route.

| Stage | What to look for | If it fails |
| --- | --- | --- |
| Publication | The server prints its loopback URL. On the checkout host, a GET of `/status.json` returns the curated snapshot. | Check the server output and port. |
| Browser route | The card reports **Forwarded endpoint reached** when the browser-facing port differs from the publication port, or **Endpoint reached** when they match. | If publication works but the page will not open, reopen the server URL in the Codex desktop browser and check its forwarded route. |
| Rendering | The card reports **Snapshot rendered** and shows eight gate results and `APPROVE_WITH_NITS`. | If the shell opens but the snapshot is unavailable, check `/status.json` on the checkout host. If it reports **Shell only**, use issue #5 while diagnosing the card. |

A connection loss retains the last rendered snapshot and labels the route disconnected. A reachable endpoint with unusable data is labeled unavailable. Pending gates have their own section. A historical result is labeled stale for live use even while the route is connected.

### Observed airJoker verification

On November 9, 2026, the forwarded tab reported `ERR_CONNECTION_RESET` after the mac-mini preview listener stopped. After restarting the loopback server in a detached process, both `/` and `/status.json` returned HTTP 200 on mac-mini. The owner then confirmed that the Codex desktop browser on airJoker displayed **Snapshot rendered**. Codex browser control was unavailable, so the owner directly verified the browser route and render.

### Historical snapshot boundary

The card serves only the HTML, CSS, JavaScript, and the curated `status-card/pilot.json` snapshot. It exposes no raw evidence files and accepts only reads. It has no owner-response, issue mutation, delivery, or deployment controls.

The server reads the curated JSON at startup. Its review time is the observed pilot verdict time, and its cutover time is the verified merge time. Update the snapshot from verified evidence when a new observation is recorded, then restart the loopback server. Owner decisions and the warning-capture follow-up stay on the tracker. [SpringDev #5](https://github.com/spring-labs-inc/SpringDev/issues/5) · [SpringDev #6](https://github.com/spring-labs-inc/SpringDev/issues/6)
