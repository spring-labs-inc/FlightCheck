# FlightCheck status cards

## Current task

The task card publishes a short summary and the verdict for the current candidate. Each task has one stable loopback route. The card shows `Pending` until a verdict is recorded for that exact candidate. Returning to a stage before Final Verdict clears the recorded verdict, including when the candidate is unchanged. A new verdict must be recorded after the repair is reviewed. The README screenshot shows this view with synthetic task data. In this repository, follow the [maintainer instructions](#maintainer-implementation-replies). The complete installation includes the card for selected adopter workflows.

For adoption in another project, keep this `status-card/` directory available to the workflow and record its path in the project setup. Keep the snapshot in a private directory outside the checkout. Assign a unique task ID and an available port per task. Record the directory, task ID, and port with the selected workflow so a resume uses the same route. Only the active workflow writes that task's curated snapshot. Keep raw output and secrets out of its title and summary.

```sh
task_dir="$(mktemp -d)"
task_id=example-task
task_url="http://127.0.0.1:8767/task/$task_id/"
python3 -B status-card/task_status.py --file "$task_dir/status.json" \
  --task "$task_id" --title "Example task" --mode minimal --url "$task_url"
python3 -B status-card/serve.py --port 8767 --task-status "$task_dir/status.json"
```

This low-level example is explicitly `minimal`: it verifies transport, never a ready active flight or a verdict. Its task page uses the existing unavailable presentation. Use `--mode flight --candidate CURRENT --details /private/flight-details.json` for an active low-level publication; maintainer and portable controller commands always select flight mode.

In a durable setup, use an owner-only directory that survives the chat session and keep the loopback listener running while the card is needed. Re-run the publisher with the same file and task ID when the candidate or review changes. Supply `--candidate` with the current identity. Supply `--verdict` and `--verdict-candidate` together only after the verdict is recorded. The publisher replaces the snapshot atomically. The task page polls the read-only endpoint and suppresses the verdict when the task, candidate binding, or connection cannot be verified.

Every user-facing controller reply in an active flight ends with the same task link, including progress, approval pauses, blockers, repairs and resume. Put any actual current verdict above that last paragraph. Ordinary chat and raw reviewer JSON are excluded. The low-level publisher supports `--chat-phase start`, `update`, and `end`; each keeps the link last, and `end` adds a current verdict above it. Use the portable prepare/check guard described in the [controller status instructions](../workflow/skills/develop-change/references/task-status.md) before sending each reply.

The shared [controller status instructions](../workflow/skills/develop-change/references/task-status.md) describe how the selected workflow uses the desktop controls on activation and resume. The optional [tab decision helper](../status-card/task_tab.py) returns the next action from observed tabs and capabilities. Codex uses the available browser controls to carry it out. The checkout-host response, desktop forwarding, and browser render are separate checks. CLI and clients without usable browser controls can continue in chat with the same task link. [Codex built-in browser](https://learn.chatgpt.com/docs/browser) · [Remote connections](https://learn.chatgpt.com/docs/remote-connections)

### Start a card over SSH

Service readiness on an SSH worker does not establish a route from the machine
running the browser. The worker detects `SSH_CONNECTION`, `SSH_CLIENT`, `SSH_TTY`,
`CODESPACES` and `REMOTE_CONTAINERS` as hints. Managed workers can omit these
markers; use the client's observed connection context and `--execution remote`
in that case. An explicit local override is for genuinely local execution.

Initialize the flight's private details on the worker using `reply.py prepare`.
Then run `flightcheck card connect` **on the browser machine**, using its existing
SSH alias, the absolute project path and the same private worker state directory:

```sh
flightcheck card connect --ssh WORKER_ALIAS \
  --checkout /absolute/remote/project --task TASK_ID \
  --remote-python /absolute/remote/python \
  --remote-state-dir /absolute/remote/private/status-card
```

A local installed project can use `flightcheck card --project . --task TASK_ID --details /private/flight-details.json`; it selects the configured project Python, verifies installed card bytes and preserves shared-helper failures. `flightcheck card check` delegates reply checking. Use `--json` for structured output.

The browser machine needs only the installed CLI for `card connect`, not a local project installation. Without the CLI, run the installed `.flightcheck/status-card/connect.py` directly. From a source checkout use `status-card/connect.py` and add
`--card-dir status-card`. If the first preparation needs its complete details,
pass `--details /absolute/remote/private/details.json`. The remote interpreter
must be the configured project interpreter. No AI session is needed on the
browser machine; the connector uses Python and the existing `ssh` executable.

The connector prepares/restores the remote service, starts a loopback-only SSH
forward, and verifies the expected task, candidate, publication port and page
through the local endpoint. Only then does it return a clickable `footer`,
`browser_reachability: verified` and `browser_rendering: unobserved`. Open that
footer in the regular browser. The connector does not open a browser on the
worker or claim rendering. SSH uses batch mode and existing authentication; a
failure never changes SSH configuration or prompts inside an agent session.

### Automatic route discovery and connection reuse

Current source helpers can consume supported native browser observations without
asking the owner to paste a URL. `reply.py prepare` and maintainer `card` accept
`--browser-observation /private/browser.json`. This is an adapter result captured
through existing client APIs, not a form for the owner to fill in. First prepare
the worker card to obtain its private `context`, candidate and publication port.
The adapter inventories browser tabs and reads the exact task's `status.json`
**on the browser machine**. It saves a mode-0600 file with this shape (synthetic
values below):

```json
{
  "schema": 1,
  "observed_at": 1795600000,
  "context": {"host": "worker", "repository": "/project/.git", "session": "current-session"},
  "can_reveal": true,
  "can_open": true,
  "tabs": [{
    "id": "observed-tab-id",
    "url": "http://localhost:43102/task/example/",
    "visible": false,
    "endpoint_reached": true,
    "snapshot": {"snapshot": "live", "task": "example", "candidate": "current-candidate",
                 "publicationPort": 43101, "completeness": {"ready": true}}
  }]
}
```

Use the actual current epoch time and exact returned context/snapshot. Fresh
observations expire after thirty seconds. The helper accepts only a unique
verified loopback task URL, matching current task, candidate and publication port.
It returns `browser_action: keep` or `reveal` with the existing `tab_id` where
supported. The controller carries out reveal through the native API and observes
the result; it must not open a duplicate tab. Visibility and endpoint reachability
do not establish rendering. Include `rendered_candidate` on a tab only after an
actual render observation for that candidate. Missing controls, ambiguous origins,
wrong identities or stale observations return a concrete fallback; queued preview
requests alone never become verified routes.

For a verified route without a tab yet, put the same endpoint observation in
`endpoints` and keep `tabs` empty. An actual native response may supply
`activation: {"status":"queued","url":"EXACT_VERIFIED_URL"}`. This returns
`browser_action: requested`, unobserved visibility/rendering, and never opens a
second tab. The candidate-aware action is authoritative for selected flights;
the legacy task-only helper cannot override it. Native and connector observations
retain their candidate/time/session verification and expire after thirty seconds.
The existing browser-side SSH monitor renews only its attempt's connector evidence
after a current endpoint probe; this never extends producer ownership. A failed
adoption or owned-forward teardown restores the prior verification. If rejection
cannot be confirmed, retain that forward and report its exact recovery action.
Worker publication and ordinary checks do not renew browser evidence.

An owner-confirmed manual destination is separate private connection
configuration. It retains the exact task, host, repository and recorded checkout,
the original declaration context/time, and explicitly authorized route callers.
An authorized second controller uses `--reconcile-route` once for this same-flight
handoff, without supplying the URL again; later ordinary preparations/checks reuse
the configuration. This transfers no editing or owned-transport/process authority.
Unregistered callers remain unavailable and preserve the known URL/provenance.
Manual reuse always reports browser reachability/rendering as unobserved; it does
not inherit a different session's fresh observation or renew native evidence. A
known failed or mismatched endpoint still makes the route unavailable.

The SSH connector retains successful connection configuration in the browser
machine's private `connection-profiles` directory. Profiles bind the SSH alias,
helper/interpreter/state settings and actual remote host/repository, separately
from task-specific URLs, candidates and owned forwards. A later `connect` can omit
`--ssh` when one compatible profile exists; pass the NEW task and checkout. The
exact recorded checkout is always required: a transport profile never supplies
another flight's execution location, including another checkout in the same clone.
The connector prepares and checks that new task/candidate, rather than displaying the
old flight. Multiple compatible profiles need an explicit `--profile ID`; initial
setup needs one existing SSH alias. No URL question or SSH configuration change is
needed. Profile files are private configuration, never published card content.
The connector first runs the worker helper's read-only `identify` operation for a
reused profile, before any task publication, listener or forward. Its preparation
preserves the selected controller session; route setup is not an ownership
transfer. It also refuses to publish an existing task from another recorded
checkout in the same clone. Matching current helpers are required for these source capabilities;
an unsupported identity operation reports unavailable and never upgrades an
installed project implicitly.

Resume preserves its established route. If the route must move, explicitly use
`--reconcile-route` with the verified replacement observation, or the connector's
replacement `--local-port`. A saved occupied/mismatched port is never reclaimed
from an unrelated process. For a new connection only, an occupied initial port
can use one OS-assigned loopback port without scanning. Existing owned-process
recovery, bounded attempts and authentication remain unchanged.

Some desktop APIs return only a queued request; browser inventory or browser
machine execution can also be unavailable. Report those concrete limits and offer
the existing connector command once per connection. An owner may observe that the
queued card rendered while its URL remains unavailable to automation; retain both
facts. Optional rendering does not add a new delivery gate. Route setup does not
approve changed product UI or bypass mandatory publication. Existing installed
copies and immutable packages remain pinned until separately authorized delivery.

The tunnel uses a separate foreground SSH connection. For that invocation only,
the connector disables connection sharing (`-S none`, `ControlMaster=no`,
`ControlPersist=no`) and backgrounding (`ForkAfterAuthentication=no`). Otherwise,
a multiplex client can hand its forward to an existing master and exit with no
error, leaving the connector unable to own that process. Host, authentication
and proxy settings remain in use; existing master connections remain running.
Failures include the SSH exit status and a bounded diagnostic excerpt when
available, with the full forward log retained privately.

The first connection uses the remote port locally unless `--local-port` is
explicitly supplied. Private connection state preserves that route on resume.
Re-running restores a stopped remote service and reuses a healthy forward.
An occupied port, wrong task/candidate, authentication error or interrupted
forward fails without a successful link. Existing route state remains available
for repair; the connector never silently chooses a different port or terminates
an unrelated listener. Connection diagnostics are in the private `ssh.log`.

If a desktop client provides forwarding, use its observed loopback route with
`reply.py prepare --user-url URL` instead. This records an externally supplied
route; the worker cannot verify the user's loopback socket. Host publication,
browser-machine reachability and actual rendering remain separate observations.
Record rendering only after desktop inspection or an owner observation.

### Progress, freshness and bounded recovery

A prepared task has separate clocks for meaningful progress, producer heartbeat/publication and the browser's last successful receipt. A successful HTTP poll proves transport at that instant; it does not renew the producer, evidence, review verdict or stage timestamps. A healthy long-running stage can retain the same progress time while its authorized producer remains alive. Missing or invalid freshness data means freshness is unknown, including for older task snapshots.

While the processes are scheduled, meaningful source/activity changes are published within five seconds, producer heartbeats run every ten seconds and the producer becomes stale after thirty seconds without a heartbeat. The browser polls every five seconds with a 4.5-second whole-request deadline: a transport failure becomes visible within 9.5 seconds of its onset, and a published change can take the next poll/deadline to appear. These are active-execution bounds, not promises while the computer is asleep. Visibility, online and resume observations trigger immediate revalidation and disclose the observation gap without inventing missed events.

The private publisher observes only the explicitly registered task, current details source and registered activities. It does not inspect historical evidence archives. Native check start, heartbeat and finish are projected as status; original logs, receipts and exit status remain authoritative. A controller registers worker/reviewer lifecycle observations without giving those sessions write access. An activity heartbeat reports observed liveness, not thinking, new proof or a favorable verdict. Stage advancement still requires its actual governing observation.

Owner leases expire after 120 seconds without a controller or registered live-work renewal. The monitor cannot renew its own ownership merely by polling. Detached monitoring is bounded to eight hours, with five-second sequential health observations and at most three recovery attempts. A listener recovery attempt is bounded to fifteen seconds; an SSH preparation has a twenty-second subprocess deadline. Only directly owned processes may be stopped. An occupied preserved port or ambiguous ownership produces an explicit recovery action rather than killing another listener, switching ports or retrying indefinitely. Expiry stops monitoring, never native work; resume re-establishes authorization on the same recorded route.

Publication staleness, listener failure and an SSH/browser route failure are distinct states. During an outage the card retains the last-known Work Links and stage observations with an age/disconnection warning, and suppresses an unverifiable current verdict. Transport loss alone does not make references invalid. Reconnection reads the newest valid task/candidate-bound snapshot; it cannot claim observation of intervening transitions. Terminal closeout preserves pending and skipped obligations and stops unnecessary active monitoring rather than painting every stage complete.

The controller can report a worker or reviewer lifecycle through the same private task directory, without changing that session's access:

```sh
python3 -B status-card/progress.py activity --directory /private/task-directory \
  --task TASK_ID --candidate CURRENT_CANDIDATE --id worker-1 \
  --kind worker --name "Implement scoped repair" --state running
```

Repeat the running observation only while liveness is actually observed; report `completed`, `failed`, `interrupted` or `unavailable` from the retained native outcome. The default native-check bridge finds the explicitly prepared task for its checkout automatically; no additional user flag is needed. `FLIGHTCHECK_TASK_ID` can disambiguate an explicitly selected task. Activity status is informational and cannot replace accepted evidence or grant review access.

Reconnecting without `--title` preserves the existing friendly heading. A new task without a title defaults to `FlightCheck TASK_ID`. An explicit nonempty title replaces the heading exactly; an explicitly blank title is rejected before replacing the snapshot. Task, candidate and route identity remain separate from this display label.

These reliability diagnostics preserve the existing Workflow Stages presentation. Issue #83 retains ownership of its undelivered presentation changes and must integrate this freshness contract when it lands. Its later-image maintenance rule does not authorize package publication or changes to immutable installed artifacts.

### Publish work links and evidence

Pass `--details /private/path/details.json` to the same publisher command. Initialize every required section first; later updates may supply only changed sections. For example, a synthetic update for `--candidate candidate-2` could contain:

```json
{
  "worktree": "setup-docs",
  "stages": {
    "Plan": "completed",
    "Implement": "completed",
    "Cheap Tests": "completed",
    "Interactive UI Approval": "skipped",
    "Independent Code Review": "current",
    "Authoritative Gates": "pending",
    "Skeptical Evidence Review": "pending",
    "Final Verdict": "pending",
    "PR & Merge": "pending"
  },
  "stage_updated_at": {
    "Independent Code Review": "2026-01-01T12:09:00Z"
  },
  "links": [
    {"kind": "epic", "label": "#10", "title": "Setup rollout", "description": "Make the project easier to set up.", "url": "https://example.com/issues/10", "created_at": "2026-01-01T09:00:00Z"},
    {"kind": "issue", "label": "#12", "title": "Clarify prerequisites", "description": "Document the tools needed for a clean checkout.", "url": "https://example.com/issues/12", "created_at": "2026-01-01T10:00:00Z", "flight": "setup-followup"},
    {"kind": "pr", "label": "#15", "title": "Document setup tools", "description": "Add the prerequisites to the setup guide.", "url": "https://example.com/pull/15", "created_at": "2026-01-01T12:08:00Z"}
  ],
  "tracked_flights": {
    "setup-followup": {"candidate": "followup-1", "stage_candidate": "followup-1", "stage": "Implement"}
  },
  "check_plan": ["Project tests"],
  "links_unavailable": {},
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
- **Stages** follow the nine names and fixed order defined in the [README](../README.md). Use the states `completed`, `current`, `skipped`, and `pending`, with at most one current stage. Active flights must declare all nine stages and one current stage, or mark a terminal flight completed/skipped with Final Verdict completed. Legacy/minimal maps may default unlisted stages to pending. A completed stage after the current stage resets to pending, including when reading older snapshots or returning to an earlier stage. Publish the new stage map when the workflow advances or returns for repair. State changes record their publication time in `stage_updated_at`. Supply that map explicitly when an original observation time is available. Unchanged stages keep their timestamps on resume. The card clears stages and timestamps on a candidate change unless the update supplies a new stage map.
- **Links** come from the agreed scope and recorded PR. Use a short reference such as `#12` for the label. Provide a title and a brief description when available. Selecting an item expands its details on the card. The `>` button opens the destination in a new tab or window. Use HTTPS destinations without credentials or query parameters. Include the tracker's `updated_at` and `created_at` timestamps with timezones when available. All link types appear together in recent activity order, with each item's kind identified beside it.
- **Linked issue stages** require an explicit `flight` on the issue link. Use the flight's task ID. For the displayed flight, the stage comes from its current candidate and stage map. For another flight, publish its observed candidate, recorded stage, and the candidate that stage applies to in `tracked_flights`. Refresh this map from the workflow records when tracked flights advance or change candidates. If no stage applies to the new candidate, publish only its candidate or omit that flight from the replacement map. The card shows a shared label when several linked issues use the same flight. The main stages always come from the displayed task.
- **Checks** summarize the latest observation per check group from the project's native evidence. Publish starts and outcomes as they occur. For the example capture script, use the `run.json` candidate, start or finish time, status and exit code. Add counts only when the tool reports them. A newer failure, interruption, or incomplete attempt takes the place of an earlier pass. Use `pending`, `running`, `passed`, `failed`, `interrupted`, or `unavailable`.
- **CI** is optional. Publish an observed `pr` or `post-merge` result with the commit the provider checked and the task candidate it belongs to. Include the run URL and attempt when known. Use `pending`, `running`, `passed`, `failed`, `cancelled`, `skipped`, or `unavailable`. The card shows the recorded observation time and does not query the provider.
- **Events** record actual `repair`, `rerun`, or `review` activity with a stable ID from the underlying run or record. An identical event can be published again without adding a row. A conflicting event with the same ID is rejected. The history stays with the private task snapshot on resume.

Each supplied `links`, `checks`, or `ci` list or `tracked_flights` map replaces that section in full. An empty list or map clears it. Omitted sections carry forward. A check or CI row from another candidate shows as stale, and rows carried through a candidate change stay stale until the workflow publishes current evidence. Use `"stale": true` if the workflow invalidates a row for the same candidate. Only the active workflow writes the snapshot, including when several checks produce evidence concurrently. Keep commands, raw logs, credentials, and private paths in the underlying evidence store.

Local checks, CI observations, iteration history, and work links show the latest activity first. Records use their most recent `observed_at`, `updated_at`, or `created_at` value. When a check, CI result, or work link changes without a newer observation or an explicit modification time, the publisher records the update time. Unchanged republication keeps the prior time. Timestamp ties keep their existing order. Undated legacy records follow dated records. Workflow stages always retain the README sequence. The synthetic example's gate list also uses activity timestamps when supplied.

### Completeness and readiness

A task title and HTTP 200 do not establish a complete flight. `completeness` is derived at publication and on each read. A ready active flight has a candidate, all nine explicitly declared stages, an honest current stage (or completed terminal flight), a `check_plan`, one nonstale current observation per planned check, and known issue/PR links or explicit reasons in `links_unavailable`. Do not invent a PR or create an issue just to fill the card.

Before tests run, use check state `pending`, the current candidate and observation time, and empty `counts`. Use `unavailable` with a `reason` when a planned check cannot run. If no checks apply, declare `"check_plan": []` and a `checks_unavailable` reason. Publishing a new nonempty `check_plan` removes the previous no-checks reason unless the update explicitly supplies a reason too; that contradictory combination remains incomplete. If an issue or PR does not exist, use, for example, `"links_unavailable": {"pr": "Local review; no PR yet."}` alongside the known issue link. Replace the reason when the real link exists.

Incomplete flight snapshots return HTTP 503 with actionable JSON diagnostics. The existing browser view hides details and shows **Snapshot unavailable**; `prepare`/`check` fail with `status: incomplete`, preserve the task URL and explain the missing sections. The maintainer command uses the same preparation guard as `reply.py`: it returns a nonzero exit and a plain status label when publication, completeness or remote routing is unavailable. It prints a clickable footer only after current publication and a browser-facing route are available. Diagnostics go to stderr; neither startup nor a supplied route is approval or proof of rendering. The native Stop guard also requires completeness. Explicit low-level minimal snapshots return 200 with `snapshot: minimal` and `ready: false`; they cannot establish flight readiness or a verdict.

A candidate edit invalidates carried stages and checks until refreshed. A same-candidate change to check/CI observations also clears the verdict; only a newly recorded verdict can bind the new observations. Listener repair/restart preserves these rules. Completeness verifies structure and freshness, not whether the supplied narrative or results are true: publish only actual evidence.

### Loopback request boundary

The server binds only `127.0.0.1`. Snapshot and asset reads require one valid loopback Host (`127.0.0.1`, `localhost`, or `[::1]`, with an optional valid port). An Origin, when present, must be a single loopback HTTP origin without a path. Foreign/malformed/duplicate authorities, foreign/null origins and absolute-form request targets are rejected. Forwarding may change the loopback port or Host; forwarded headers cannot authorize a foreign Host. No CORS grant is added. This closes the adopter journal's forged-Host read without publishing the raw journal. The policy follows HTTP's [Host authority](https://www.rfc-editor.org/rfc/rfc9110.html#section-7.2) and Fetch's [Origin header](https://fetch.spec.whatwg.org/#origin-header) boundaries.

This is not authentication against local processes or other local users. Keep snapshots private, publish only curated short labels, and retain raw evidence elsewhere. Optional project-specific deny-pattern/content filters are a separate data-boundary policy, not a replacement for Host/Origin checks. The worker never configures a public listener. The browser-machine connector explicitly starts a loopback SSH forward using existing SSH configuration.

### Rehearse on desktop

Use a synthetic task on both a local checkout and an SSH-connected checkout. Confirm the same task link is last in every controller reply: activation, progress, approval pause, blocker, repair, resume and final handoff. Ordinary chat and raw reviewer JSON omit it. Proactively offer TUI users the regular browser. Activate the workflow with the card absent, then resume with the card visible and again with its tab hidden. Check that the same task route stays open in one tab. Confirm that the current task and `Snapshot rendered` appear in the desktop view.

Record a verdict for the synthetic candidate, then change the candidate while retaining the old verdict binding in the test input. Confirm the card shows `Pending` and the closing block omits the stale verdict. Stop the listener and check the chat fallback, then restore the original port and reload the same tab. Record host HTTP, the desktop route, and the rendered task as separate observations.

## Maintainer implementation replies

The [root instructions](../AGENTS.md) select FlightCheck for implementation in this repository. Start or resume the card from the implementation checkout. Keep the same task ID for the life of the task.

```sh
python3 -B status-card/maintainer.py card --task example-change --title "Example change"
```

At activation, add `--details /private/flight-details.json` using the schema above, with pending check observations for the current candidate. Run the command before an implementation reply and use its output as the reply's last paragraph. The command fingerprints the current checkout, publishes the private snapshot, and verifies the task endpoint through the shared prepare guard. It detects common SSH/container markers; pass `--execution local` or `remote` when the environment is ambiguous. An SSH worker without a browser route returns a plain status label and a nonzero exit, rather than presenting its own loopback address as a working user link. It gets the checkout label from Git. A named branch in the primary checkout shows **Branch** with its full name. A linked worktree shows **Worktree** with its directory name. A detached HEAD in the primary checkout hides the row. On resume the command reuses the recorded port and restores a stopped listener if that port is available. Pass `--summary` and `--details` to update the curated card content. Supply `--verdict` and `--verdict-candidate` together after a verdict for that candidate has been recorded.

The default state directory is `$XDG_STATE_HOME/flightcheck` or `~/.local/state/flightcheck`. If the session restricts that path, set `FLIGHTCHECK_STATE_DIR` to the same absolute, owner-only directory outside the checkout for Codex and its hooks. Use a host that permits IPv4 loopback binds. The listener runs in the background while the card is needed. The maintainer command replaces an older managed listener that omits current card metadata and reuses its port. Its startup log is in the private task directory.

Keep maintainer hook configuration in the ignored root `.codex/` directory and review and trust it locally in Codex. This private configuration is not distributed with the repository. The hook compares the checkout to its state at the start of the turn and also checks turns that ran the maintainer card command. If the last reply is missing the current task link, the hook requests a correction once. This Stop-only hook does not prove interception of intermediate or interrupted replies. The root/shared instructions and portable prepare/check guard cover the controller pre-send procedure. No new hooks or permission changes are installed; disable executable hooks in read-only reviewer sessions and qualify actual client event coverage before claiming native enforcement. [Codex hook trust](https://learn.chatgpt.com/docs/hooks#review-and-trust-hooks)

The native apps rely on the controller invoking that procedure. They can display an intermediate or interrupted message before a check if the controller skips it. The [accepted native-app scope](claude-trial-report.md#accepted-native-app-scope) records this owner's explicit acceptance of that limitation. Every selected-flight reply still requires preparation, an exact-draft check and the current footer. Retain a skipped check as a failure and correct the following reply; no correction proves that the earlier message was intercepted. Evidence, reviewer isolation and delivery rules remain unchanged.

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


### Prepare Work Link metadata

Normal flight publication resolves the existing Epic, Issue and PR controls before
committing their initial coherent snapshot. The controller and changed-link monitor
use the selected project's configured GitHub repository (or its single existing Git
remote). Only canonical items in that repository are read through the existing `gh`
subscription/login environment with explicit GET requests. This does not authorize
provider writes or arbitrary endpoints. Unsupported providers remain visibly
unavailable; no provider registry or configuration migration is introduced.

The task-private `link-metadata` observation cache binds each safe projection to its
repository/configuration authority, task and canonical item. Publication also binds
it to the current candidate and content digest. A changed candidate may rebind
valid cached bytes; wrong tasks, items or changed content cannot supply ready
metadata. The cache contains a short title/summary and supported source state and
times, never raw bodies or errors. Private descriptions and sensitive-looking
content are withheld; open the tracker for full details. Public summaries are
conservatively reduced to the first safe paragraph (240 characters), rendered as
text, and never interpreted as instructions or HTML. This filter is deliberately
conservative; it is not a general secret-classification service. Avoid putting
secrets in public tracker titles/descriptions.

Safe item observations are fresh for 15 minutes. A batch that fetches new body
data first rechecks repository visibility; cached public classification cannot
authorize sharing a newly private body. Cache hits, polling and selection still
perform no provider reads. Failed lookups back off for 30 seconds.
One preparation has at most eight GETs, a two-second deadline per subprocess and
an eight-second overall lookup deadline, with up to 0.2 seconds for owned-process
cleanup after a timeout. Added/changed links use the same bounded path on a
background worker, leaving progress and heartbeat publication independent. Browser
polling, selection, and ordinary heartbeats never fetch provider metadata. Normal
explicit preparation reuses fresh cache and refreshes expired observations; no
new click-to-refresh control is added.

`link_details.ready` reports whether all required link details are currently
verified. Existing `completeness.ready` still reports the flight frame's structural
readiness, so unavailable tracker details do not disable monitoring or hide an
otherwise usable card. A never-loaded, loading, unavailable/denied, stale last-known
or confirmed-empty description is shown honestly in the existing expansion.
“No description published” is reserved for a successfully observed empty source.
Safe cached details and selected links survive outages. A metadata failure cannot
renew evidence, change Workflow Stages, alter ownership, or imply fresh progress.
Technical diagnostics remain in private records; the approved concise warning and
two-line operational footer are unchanged. #83 retains the separate visual/status
indicator and canonical-image design scope.
