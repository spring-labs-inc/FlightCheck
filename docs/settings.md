# Shared configuration and local Settings

Setup, `flightcheck config`, source `setup/install.py config`, and Settings use the
same private `.flightcheck/project.json`. Its revision is the SHA-256 of the stored
bytes. `_flightcheck.fields` records source, project/host scope, confirmation,
confirmation reference and last validation. Resource entries retain individual
provenance. Discovered values are suggestions until explicitly confirmed.

The ordinary task card is read-only. Select Settings to view the access explanation.
To enable private editing, explicitly launch a capability for the exact project,
task and session, using the existing private task `status.json`:

```sh
python3 -B setup/install.py settings /path/to/project \
  --task selected-task --session actual-session \
  --card-status /private/task/status.json \
  --registry /private/flight-associations \
  --authorize-local-settings /private/owner-settings-decision.json
```

The terminal `flightcheck settings` and current copied `.flightcheck/install.py
settings` accept the same arguments. This enables only the explicit local Settings
session on the existing task listener. It reuses the task's discovered browser
route, including SSH forwarding. A host listener address is not the forwarded
browser address. If discovery is unavailable, establish the existing connector's
once-per-connection profile and retry. There is no additional forwarding service.

Keep the returned capability URL private. The page removes its fragment before
making requests. The capability is absent from task snapshots and request logs;
private API requests require its exact project/task/session binding. Launching a
new session rotates the capability; removing its private `settings-session.json`
revokes it. Loopback Host validation alone does not authorize a write.

## Fields and authority

Settings uses ordinary location fields, an activation checkbox, classified check
rows, checkout choices and separate cleanup checkboxes. Empty optional resources
are **Not configured**. Known unavailable resources retain their explicit reason
under Details; clearing that record is deliberate. An optional resource update
of `null` removes its pointer through the common updater, including CLI updates.
It does not fabricate an unavailable reason or probe access automatically.

The Project board section owns the board location, synchronization switch and
status mapping. **Read board details** authorizes a bounded read of that exact
existing GitHub project through the existing provider transport and credentials.
It shows observed board/status names without saving, granting access or changing
membership. Ambiguous or incomplete fields are reported inline. Saved IDs are
reused; manual connection IDs appear once under Advanced when names cannot be
read. The single **Use this connection** fallback action confirms the current
board and supplied IDs without requiring a fake edit; changing them invalidates
that confirmation. It does not claim discovery or verified access.
A changed, unbound board URL cannot enable synchronization with another
board's old IDs, including after saving while synchronization is off. Mappings
hide when off, preserving the configured connection and option values. The
advisory/required failure policy is a separate meaningful Advanced choice.

Choose Review changes, then Save changes or Back to editing. Cancel changes
reloads saved values. Settings records deliberate decisions internally under the
existing launch authorization. Technical provenance and validation remain under
Advanced → Details; recovery appears only for an interrupted transaction.

The bottom [ STATUS ] link returns to the card in this tab. Its bottom
[ Settings ] link returns to the same project/task. After a successful authorized read, the exact
capability/context is retained only in same-origin, exact-task `sessionStorage`
for this tab for up to 30 minutes. It is never in a public link, cookie or
persistent `localStorage`. The server verifies every request; wrong task/project/
session or revoked authorization remains blocked. Authorization failures clear
this navigation record. Closing the tab ends its browser context, and Details
provides an explicit Clear Settings navigation session action. An ordinary card
in a fresh tab does not acquire editing permission; use the authorized launcher.

| Group | Common fields | Boundaries |
| --- | --- | --- |
| Project | `resources`, `default_branch`, `protected_branches` | Repository identity comes from the actual checkout. Resource pointers may name an explicit unavailable reason. Shared pointers should be repository-relative; private log paths and references stay local. Synchronization's confirmed project identity is `status_sync`, not a second independent board configuration. |
| Workflow | `activation`, `activation_reference`, `checks`, `required_runtimes`, `preview` | Commands and runtime requirements are recorded data, never executed by read, preview or Save. Default-for-coding needs explicit owner authorization. Only managed activation text changes; surrounding project instructions survive. |
| Checkout | `checkout_policy` mode, branch prefix, Git fallback and reference | Native choice remains the default. Worktree-required never silently weakens. Default/protected branches, verified ownership, same-checkout resume and detached delivery safeguards are mandatory. Native capability may honestly be unavailable; client worktree count/retention/archive settings remain in the client. |
| Cleanup | `cleanup_policy` local branches, actual remote branches, temporary worktrees and retained preferences | These are separately confirmed future preferences. Launch captures the configuration revision and separately records exact artifact grants/inventory. Save neither deletes anything nor changes an existing grant or reservation. Required safe disposition and all preservation rules remain mandatory. |
| Evidence/delivery | `evidence_dir`, `review_client`, `reviewer_access`, `delivery`, `nit_tracker`, `policy_reference` | Private host values remain outside published projections. These are requirements/defaults and references, not provider/reviewer permission, credential, hook, delivery or cleanup grants. |

`python` and its observed/pinned identity are displayed read-only. Structural
reads/previews/saves do not execute an interpreter, including an unavailable pin.
A changed executable's bytes block ordinary updates. An explicit terminal runtime
reconciliation is separate:

```sh
python3 -B setup/install.py config runtime-preview /path/to/project \
  --python /approved/existing/python --execute-approved-runtime \
  --expected-revision CURRENT_SHA256 --reference /private/runtime-decision.json \
  --plan /private/runtime-plan.json
python3 -B setup/install.py config apply /path/to/project \
  --apply /private/runtime-plan.json --execute-approved-runtime
```

Only that explicit operation executes fixed runtime identity probes. Its reviewed
transaction updates the runtime pin and private status instructions together.
Settings Save cannot invoke it. No runtime is installed.

For a board destination, `resources.project_board` may hold `{ "url": "https://…", "provider": "github-projects-v2", "project_id": "CONFIRMED_ID" }`. Its provider/project identity must equal the canonical `status_sync` identity; it cannot choose a second board. The URL is an owner-confirmed resource pointer, not a claim of provider inspection or write permission. Legacy string pointers remain readable, with opening withheld until bound; an explicit unavailable reason remains supported.

## Preview, save and recover

Read with `config read`, preview with `config preview --changes FILE
--expected-revision SHA --reference OWNER_REFERENCE`, and apply the resulting
private plan with `config apply --apply PLAN`. Settings calls these same common
model/transaction functions. Its preview describes changed values, with affected
file details available on expansion. Apply recomputes the exact plan under the existing transaction lock.
Stale revisions, changed preimages or component drift require a new preview;
concurrent owner changes survive. `config recover` or Settings Recover restores
the previous complete working configuration after an interrupted update.

Defaults affect future flights. Settings displays captured active-flight revisions
and grants separately. Explicit active reconfiguration retains the old snapshot,
grants and synchronization history and declares required checkout/check/evidence/
status-sync revalidation. Execution remains blocked until its existing checkout
reconciliation and affected validation are completed. A configuration change does
not authorize new provider operations or reset a synchronization retry budget.
With synchronization enabled, any captured configuration revision change requires
status-authority revalidation even when the status mapping is unchanged.

## Existing pinned installations

Reads select the integrity-checked installed model. Current writes require the supported configuration adapter.
A prior adapter is clearly read-only in Settings until explicitly reconciled.
From a clean current FlightCheck source, or its reviewed terminal distribution:

```sh
python3 -B setup/install.py config adapter-preview /path/to/project \
  --expected-revision CURRENT_SHA256 --reference /private/adapter-decision.json \
  --plan /private/adapter-plan.json
python3 -B setup/install.py config apply /path/to/project --apply /private/adapter-plan.json
```

This is an explicit bounded compatibility transaction, never a side effect of
read, preview of ordinary values, Save, or opening a card. Its plan enumerates
common model/updater/dispatch and Settings assets and the merged manifest. It
records exact adapter source and owner reference while retaining the original
workflow source and distribution/runtime pins. Workflow instructions and helpers outside the enumerated common adapter
components retain their bytes. The configuration reconfiguration helper is part
of the explicitly recorded adapter update. The previous configuration bytes stay
unchanged until a separately reviewed configuration update. The common transaction
provides stale-plan rejection and rollback. There is one effective installed model
afterward. A source checkout without canonical project configuration honestly
reports Unconfigured; it does not acquire a separate Settings defaults store.

## Audit and external destinations

Review branches and worktrees invokes the existing read-only repository audit.
It reports ownership, unfinished/retained/ambiguous work, recommendations and
coverage limitations. Remote observations are an explicit audit-action choice,
using the existing read-only operation and current permissions. It performs no fetch, prune, delete, archive, commit, stash,
checkout switch or native-client mutation. Reports grant no cleanup authority;
any later execution is a separate authorized operation with current revalidation.

Settings URL inputs use an adjacent arrow to open the destination in a new tab;
audit destinations use a compact labeled arrow. Resource and audit destinations
belong in #83's card-wide external-link inventory; this work does not implement
the richer resource-discovery interview or native client settings management.

The [destination inventory](settings-external-links.json) identifies Settings and
audit field families for #83 without publishing actual private destinations.

### Location controls and navigation

A location uses one textbox with an adjacent URL arrow or Browse button. Tracker
and board arrows open credential-free HTTP(S) destinations in a separate tab.
Browse selects files or folders in the configured project on the checkout host;
it does not upload files or mistake browser-machine selections for remote paths.
Style guides and runbooks select files, documentation selects a folder, and logs
can select either. The chooser lists names and types only, omits hidden/private
entries and symlinks, and refuses traversal outside the project. Select changes
only the draft; Cancel leaves it unchanged. External host paths, including private
evidence storage, remain direct-entry fields; project browsing never relocates
private evidence into a checkout.

Saved unavailability is shown beside the field. **Clear saved problem** removes
that note only when the change is saved; choosing a replacement location also
replaces it. Merely leaving the input blank preserves an existing problem record.

The bottom **[ Settings ]** and **[ STATUS ]** links preserve the authorized
current-tab context. Successful **Save changes** returns to Task Status; stale or
failed saves remain in Settings with the draft and error available.
