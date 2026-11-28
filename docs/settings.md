# Project Settings reference

Settings configures persistent FlightCheck behavior for this project, for current
and future flights. It uses the same private `.flightcheck/project.json` as setup
and `flightcheck config`; there is no separate Settings defaults store.

Edit the form and select **Save Changes** once. FlightCheck validates the draft,
prepares the revision-checked common update and applies it behind that button.
Success returns to Status. Validation, conflict or recovery errors stay inline and
keep the draft. **Cancel changes** returns to Status without saving. **[ STATUS ]**
also returns without saving. The matching **[ SETTINGS ]** link sits below and
outside the whole Last progress section, including when Details is closed.

Running checks finish under their captured settings. Eligible active work adopts
saved changes at its next safe execution boundary. Incompatible checkout policy,
frozen work or work on another host waits for reconciliation. Settings never moves
a running worker, rewrites historical results or expands its permissions. Only
affected checks and assumptions need revalidation; unaffected accepted evidence
remains available under the existing incremental review rules.

## Open and authorize

Settings is available between flights with project editing authorization; users
need no task or flight identifier:

```sh
python3 -B setup/install.py settings /path/to/project \
  --authorize-local-settings /private/owner-settings-decision.json
```

`flightcheck settings` and a current copied `.flightcheck/install.py settings`
accept the same arguments. The launcher supplies internal session identifiers and
reuses the existing HTTP surface and supported preview/connection transport. The
checkout-host listener address is distinct from the client's forwarded browser
address, including over SSH. No additional forwarding service is introduced.

An existing task card is an optional transport. Its launcher can supply matching
`--task`, `--session`, private `--card-status`, and explicit `--project-scope`.
An old task-scoped token is never silently promoted to project editing authority.
Keep capability URLs private: the page removes the fragment and retains authorized
navigation only in same-origin, exact-context session storage for that tab, for up
to 30 minutes. Requests still require server authorization; public links, a fresh
tab, loopback Host validation and merely opening Settings grant no edit access.

## Defaults, saved values and scope

The form starts with the project's saved values, including preserved custom
values. A default below describes an unset/new configuration, not a replacement
for an existing owner decision. Setup may have confirmed project-specific values
or proposed detected resources; Settings does not invent discovered identities.

Project resource paths should normally be repository-relative. Absolute local,
`file:` and `ssh:` resource pointers are host-specific. Browsing always uses the
configured project's folder on the checkout host. Evidence, check commands,
reviewer-access instructions, delivery instructions, workflow references and
explicit minor-follow-up overrides are private host-scoped values in the common
model. Project identity and the host are not machine-wide configuration stores.

Every save requires the existing project capability and revision/conflict checks.
Changing a preference does not grant tracker, provider, reviewer, delivery or
cleanup authority. Mandatory ownership, protected-branch, checkout verification,
accepted-completion and preservation rules cannot be switched off.

## Project

Optional blank resources show **Not configured**. A known unavailable resource is
a different state: its saved reason appears inline. Blank input during an unrelated
save preserves that reason. **Clear saved problem** deliberately removes the note
on Save, leaving the resource unconfigured; choosing a replacement path replaces
it. No access failure is inferred merely because a field is empty.

| Control | Purpose and default | Choices, scope and effect |
| --- | --- | --- |
| Tracker | Main issue/follow-up destination; optional, otherwise Not configured. | One `resources.issue_tracker` pointer. Its adjacent arrow opens a credential-free HTTP(S) URL in a new tab. Saving changes where future tracker work looks; actual writes still need scoped authority. Inherited minor follow-ups follow this value automatically. |
| Style guide | Coding-convention file; optional or confirmed/detected existing pointer. | `resources.style_guide`. Browse selects a project file; a saved URL remains editable and Browse still selects host-project files. Distinct from Workflow instructions, which govern the flight process. |
| Documentation | Documentation folder; optional. | `resources.documentation`. Browse selects a directory on the project host. A pointer locates reference material; Save does not read its contents or run a documentation check. |
| Runbooks | Runbook file; optional. | `resources.runbook`, one file pointer despite the plural label. Browse selects a project file. Save never executes its commands. |
| Logs | Log destination; optional. | `resources.logs`. Browse can select a file or folder. Outside-project/private host destinations remain direct-entry pointers; browsing does not expose private evidence. |
| Other configured resource fields | Preserve additional project-specific `resources` keys; there is no second alias for a standard field. | Existing names become familiar labels. File/folder Browse is available where supported; URL arrows open supported destinations. The same missing/unavailable and path-scope rules apply. |
| URL arrow | Open the single URL textbox value without a redundant destination flyout. | Enabled for credential-free HTTP(S); opens separately with `noopener noreferrer`. It does not validate provider access or save edits. |
| Browse | Choose a host-project resource path without uploading a browser-local file. | See the chooser controls below. Selection edits the draft; Save is the only persistence action. |
| Clear saved problem | Remove a known unavailable-resource note deliberately. | Appears only for an actual saved problem. It changes the draft, and Cancel leaves the original record intact. |

## Project board and synchronization

The board is configured once. Its destination is dependent metadata for the one
canonical `status_sync` connection, never a second independently editable board.
Friendly names come from confirmed configuration or an authorized bounded read.
Settings never claims manual IDs were discovered or access-verified.

| Control | Purpose and default | Choices, scope and effect |
| --- | --- | --- |
| Board | Project-board destination; optional until synchronization is enabled. | `resources.project_board`. One URL field and adjacent arrow. A confirmed structured destination must match the canonical provider/project ID. An older string pointer is retained; enabling a new/unbound destination requires reading or explicitly confirming that board's connection. |
| Read board details | Resolve the entered board's friendly name, status field and options. | Explicit read-only use of the existing GitHub Projects v2 transport and credentials. It neither saves nor adds membership/grants; unavailable, ambiguous or incomplete results are reported honestly. |
| Synchronize status | Enable lifecycle status synchronization; default off (`disabled`). | Enabling uses advisory mode unless Required is chosen. Requires the selected board, field and five distinct existing option IDs. Turning it off hides mappings and preserves connection/option values. Exact issue-scoped, revision-bound write authority remains separate. |
| To do mapping | Existing board status for `todo`. | No invented default option. Select an observed status name; the common model stores its exact option ID. |
| Ready mapping | Existing board status for `ready`. | Same project/field and exact-option rules. Must differ from the other four mappings. |
| In progress mapping | Existing board status for `in_progress`. | Same rules; only synchronization behavior changes at a safe boundary. Sequence/Priority and manual/concurrent board decisions remain protected. |
| In review mapping | Existing board status for `review`. | Same rules. A mapping preference does not authorize broader board writes. |
| Done mapping | Existing board status for `done`. | Same rules. Done still requires accepted completion; saving this mapping cannot mark a flight complete. |

Advanced contains the following connection/policy controls once, rather than a
second editable copy of the board URL or ordinary mapping dropdowns:

| Control | Purpose and default | Choices, scope and effect |
| --- | --- | --- |
| When synchronization fails | Behavior when an enabled synchronization transition cannot be verified. | **Report and continue** (`advisory`, the enable default) or **Block the transition** (`required`). Disabled stores `disabled`; connection/options remain saved. Required blocks only the scoped lifecycle transition, not unrelated projects. |
| Manual board connection · fallback | Supply a known existing connection when the bounded read is unavailable. | Collapsed by default. Supported provider is GitHub Projects v2, explained as text; membership is always existing-only. There is no provider or membership selector offering unsupported choices. |
| Project ID | Exact existing project identity for the same Board field. | No fabricated default; reuse confirmed configuration. Private Advanced fallback, not a second project decision. |
| Status field ID | Exact existing status-field identity within that project. | No default or inferred field; reuse confirmed configuration or supply the known ID. |
| To do / Ready / In progress / In review / Done status IDs | Manual equivalents of the five mapping dropdowns when names cannot be read. | Each maps its corresponding logical state to one exact, distinct existing option. They feed the same canonical `status_sync.options`, not another mapping model. |
| Use this connection | Explicitly confirm this board and the supplied IDs. | Requires the URL, project, field and all five distinct IDs. Editing them invalidates the unsaved confirmation. This records an owner decision on Save and makes no discovery, membership or write-permission claim. |

Any adopted configuration revision change with synchronization enabled requires
reconciliation of the accepted exact-revision status authority, even if only a
resource changed. Save preserves the old grant, retry state and history; it cannot
silently bind authority to the new revision or reset retries.

## Workflow

| Control | Purpose and default | Choices, scope and effect |
| --- | --- | --- |
| Use FlightCheck by default for coding work | Activation policy; default unchecked (`opt-in`). | Checked means `default-for-coding`; the authorized Save records the activation decision internally. Only managed activation instructions change; surrounding project instructions survive. |
| Check name | Human label for one required check. | Setup requires actual project checks; a newly added row starts blank and must be completed. Host-specific check declaration, not a command execution. |
| Command | Existing non-mutating check's argument list. | Quote arguments containing spaces; shell expansion is not evaluated. Preserve existing command arguments unless changed. Save does not run the command. A changed check requires affected validation at adoption. |
| Classification | When that check is authoritative. | **Cheap check** (`cheap`, new-row default) or **Authoritative check** (`authoritative`). This labels evidence expectations; a cheap check cannot substitute for a required authoritative gate. |
| Add check | Add one draft check row. | New row has empty name/command and Cheap classification. Complete it before Save; it is not silently a runnable default. |
| Remove | Remove that check from the draft list. | No persistence until Save; the common model still requires a nonempty valid check list. Mandatory workflow gates/guards are not optional switches. |
| UI preview instructions | Project-specific instructions for the existing preview capability. | May initially be unset; if configured, use nonempty instructions. This records data, never starts a preview or forwarding framework. A change invalidates only affected preview assumptions. |

## Checkout & Cleanup

| Control | Purpose and default | Choices, scope and effect |
| --- | --- | --- |
| Checkout choice | Required checkout isolation policy. | **Native choice (default)** (`native-choice`) or **Require a separate worktree** (`worktree-required`). Native capability may honestly be unavailable; the requirement never silently weakens. An incompatible existing worker stays in place and adoption waits for a compatible verified boundary. |
| Allow Git fallback when native checkout creation is unavailable | Permit the ordinary Git fallback within the flight's authorized scope. | Default unchecked. An authorized Save records its confirmation reference internally; it does not create a worktree or grant deletion authority. |
| Branch prefix | Prefix for owned implementation branches; default unset unless configured. | Use a prefix such as `codex/`; the combined prefix and branch suffix must form a valid Git branch. A changed prefix is enforced against actual worker branches at adoption; no branch is silently renamed or worker moved. |
| Additional protected branches | Add protections beyond the actual default branch. | Comma-separated literal branch names; default none beyond the default branch. The default branch is always protected and shown as explanatory text, not an optional checkbox. Authoritative repository protection still applies. |
| Automatic cleanup · Verified merged local branches | Preference to clean eligible owned local refs after verified integration. | Default unchecked. Requires current exact inventory/grants and ownership/preservation safeguards; Save deletes nothing and does not expand an existing flight's grants. |
| Automatic cleanup · Verified merged actual remote branches | Independent preference for actual remote refs. | Default unchecked. Distinct from local refs and remote-tracking observations; same exact authorization and verification restrictions. |
| Automatic cleanup · Verified merged temporary worktrees | Independent preference for disposable owned checkouts. | Default unchecked. Existing retained artifacts, protected checkouts, unknown native operations and reservations remain preserved. Per-flight retained items appear only in the read-only audit. |

Client worktree count, native retention and archive preferences remain in the
native client. Mandatory safe closeout and preservation are not Settings toggles.

At the normal lifecycle planning boundary, the confirmed effective preferences
select concrete `next_actions` for review from the existing verified, eligible,
explicitly granted inventory. Turning a preference off removes only its automatic
proposal. The artifact still requires the independent disposition and closeout
accounting. Save and proposal generation delete nothing, create no cleanup grants
and change no frozen decisions, retention obligations or reservations.

## Evidence & Delivery and remaining Advanced controls

| Control | Purpose and default | Choices, scope and effect |
| --- | --- | --- |
| Private evidence location | Private host directory for check/review receipts. | Required absolute, nonsymlink path outside the checkout; an existing directory must be owner-only (0700). Setup confirms it. Direct entry, not project Browse. Existing flight evidence is preserved; active adoption revalidates affected assumptions instead of relocating old results. |
| Review client | Intended independent review client. | **Codex** or **Claude**; an unset value prompts a choice, and an existing custom value remains selectable. A preference grants no access and does not establish a read-only reviewer boundary. |
| Delivery policy | Instructions for authorized delivery. | Schema default forbids provider writes without owner approval. Selector offers **Pull request and approved merge** or **Prepare review only**, retaining any saved custom policy. Host-scoped instructions never grant provider/merge rights; changed delivery assumptions need validation. |
| Use a separate minor-follow-up location | Enable a deliberate exception to the main tracker. | Default unchecked: `nit_tracker: null` inherits the current Tracker dynamically. Enabling reveals one nonempty Advanced override; disabling resumes inheritance without copying a tracker URL. |
| Minor-follow-up override | Explicit alternate notes/tracker destination. | Required only while its override checkbox is checked. Existing explicit strings are retained. Host-scoped; adjacent URL/Browse actions follow the same supported location rules and never grant writes. |
| Reviewer access | Required access/boundary instructions or reference. | Setup may record a pending probe rather than pretend access exists. Nonempty when configured. Host-scoped data; actual independent read-only access/write-rejection probes remain required. |
| Workflow instructions | Reference to project development/delivery rules (`policy_reference`). | Required nonempty setup/owner reference; use an existing path or instructions. Host-scoped private reference, with project-file Browse where applicable. Distinct from coding conventions in Style guide; Save never executes the referenced material. |
| Required runtimes | Recorded tools/versions the project needs. | Default empty list. One nonempty requirement per line; removing all rows clears the list. Host-recorded requirements for this project, not an environment manager: Save installs or executes no runtime. Changes require affected validation. |
| Details: validation and provenance | Inspect configuration source, scope, confirmation and structural validation. | Collapsed by default; metadata is read-only and not duplicated as ordinary input. Structural validity is not a claim of runtime/resource/provider access. |
| Confirm displayed suggestions | Deliberately confirm currently unconfirmed values. | Initially unchecked; appears only when applicable. Save records these exact displayed values through the common updater. Unchanged, unconfirmed suggestions are not silently elevated by an unrelated Save. |
| Runtime validation | Read-only status of the pinned executable and observation. | Uses the existing runtime identity; it is not a runtime selector or execution button. An unavailable/changed pin must be reconciled through the explicitly authorized terminal operation below. |
| Clear Settings navigation session | Revoke this tab's retained navigation context. | Clears session storage and locks the editing surface. It neither resets configuration nor grants access elsewhere; reopening editing requires the authorized launcher. |
| Recover interrupted update | Restore the previous complete configuration after an interrupted transaction. | Shown only when recovery is actually needed. Uses the existing common recovery journal/backups; it does not discard unknown concurrent bytes or rewrite evidence. |
| Include permitted read-only remote observations | Add current remote observations to an explicit repository audit. | Unchecked by default; action-specific, not another persistent configuration setting. Uses existing permissions; no fetch/prune/provider mutation. |
| Run read-only audit | Inspect branches/worktrees, exact ownership, retained items and limitations. | Separate explicit action. No delete/archive/stash/commit/switch/native mutation, and no cleanup authority is granted. Individual retention records remain here rather than editable Settings inputs. |

## Resource chooser and page actions

The chooser is one compact scrollable folder tree with indented children, folder
and file icons, disclosure buttons and a single selection. It tries the current
draft location first, then the saved value. For example, `docs/style.md` opens
`docs/` with `style.md` selected. An actual missing/unbrowsable path or an outside
project/URL pointer produces an explanation before using the saved location or
project folder. No nonexistent selection is invented.

| Control | Effect |
| --- | --- |
| Folder disclosure | Expand/collapse one folder in the same pane using bounded host-project name/type reads. Hidden/private paths, symlinks and private evidence remain excluded. |
| File/folder row | Select exactly one item. File-only fields cannot confirm a folder; Documentation selects folders; Logs accepts either. No contents are uploaded or read. |
| Path/breadcrumb | Show the current directory and navigate to a project ancestor. Relative and absolute-inside-project current values are supported; outside-project host paths stay direct-entry. |
| Up | Navigate to the parent directory; disabled at the project root. It is in the navigation row, not the confirmation footer. |
| Clear selection | Remove the current picker selection, disabling confirmation; shown only when useful. It does not clear the configuration textbox. |
| Select file / Select folder | Confirm a compatible selected item into the draft textbox and close the dialog. This does not save project settings. |
| Chooser Cancel | Close the dialog and leave the textbox draft unchanged. Distinct from page-level Cancel changes. |
| Save Changes | One action validates, internally prepares and applies the existing authorized transaction. Success returns to Status; failure keeps the draft with an inline error. There is no second review screen. |
| Cancel changes | Discard unsaved page edits by returning to Status in the same tab/context. No configuration API write occurs. |
| [ STATUS ] / [ SETTINGS ] | Matching bottom-right navigation preserves the exact authorized tab context. A public/fresh context remains read-only. |

## Transaction, adoption and evidence details

The common document revision is the SHA-256 of its stored bytes. Save recomputes
the internally prepared plan under the existing project transaction lock. Stale
revisions, changed preimages or component drift fail closed; concurrent owner
choices survive. Recovery retains the journal and original backups.

Within that lock, Save records eligible adoption intents before publishing the
canonical configuration. Intents contain only project/transaction locators, target
revision and decision reference, not another values store. A failed or interrupted
Save cannot adopt unpublished values; superseded intents remain recoverable.

The existing recorder holds a shared execution lease from initial context capture
through final receipt publication, inherited by its foreground child. Overlapping
checks finish with their old bindings; the last exclusive safe boundary consumes a
published intent. Worker captures participate automatically; a controller execution
capture explicitly opts in with `--adopt-project-settings`. Read-only verify,
audit, status and review admission never adopt; external commands are not universally
intercepted. Existing grants, captured snapshots, synchronization retry/history and
physical workers remain intact. Frozen delivery/disposition leases, unknown native
reservations and other-host work are honestly deferred.

Pass reuse stays strict about source, request, full input fingerprint, grants,
physical checkout/session, runtime and policy. A frozen
`--configuration-dependencies` JSON list may declare supported common setting
paths, including configured custom resources. Complete paths are validated: an
unknown child or child of a scalar cannot declare independence. Omitted/unknown declarations are conservative. Only valid same-
execution adoption history with unaffected dependencies permits reuse; mid-check
identity remains strict. After check commands or classifications change, affected
frozen requests are blocked until the controller reconciles the exact command
and phase against the common model. The recorder's `--configuration-check NAME`
binds that selected check; handoff also verifies its current classification.
Settings never rewrites a frozen gate. A named check's current command and
classification are validated exactly without treating an edit to a different
check as an implicit dependency. Explicit catalog dependencies and unknown
assumptions remain conservative. The fixed internal preflight round trip declares
its own independence; it does not execute a project check. New generic checkout
contexts and handoff packets do not copy unrelated check argv: lookup stays
inside the private Registry and returns only the requested name/classification.
Historical receipts keep their original private bytes and authority; they are not
rewritten or retagged. Explicitly independent unaffected requests
may retain their original receipt and complete fingerprint. Accepted evidence is reused through normal incremental
review without retagging old receipts or historical results.

The terminal common interface still exposes explicit `config read`, `config
preview --changes FILE --expected-revision SHA --reference OWNER_REFERENCE` and
`config apply --apply PLAN`; these are the same functions the one-button UI uses.

### Runtime reconciliation

Structural Settings operations never execute a configured interpreter, including
an unavailable pin. An executable whose bytes changed blocks ordinary updates.
Only this separate explicitly authorized terminal operation probes and reconciles
the existing runtime; it installs nothing:

```sh
python3 -B setup/install.py config runtime-preview /path/to/project \
  --python /approved/existing/python --execute-approved-runtime \
  --expected-revision CURRENT_SHA256 --reference /private/runtime-decision.json \
  --plan /private/runtime-plan.json
python3 -B setup/install.py config apply /path/to/project \
  --apply /private/runtime-plan.json --execute-approved-runtime
```

### Existing pinned installations

Reads use the integrity-checked installed common model. A prior incompatible
adapter is read-only until an explicit bounded update from current reviewed source:

```sh
python3 -B setup/install.py config adapter-preview /path/to/project \
  --expected-revision CURRENT_SHA256 --reference /private/adapter-decision.json \
  --plan /private/adapter-plan.json
python3 -B setup/install.py config apply /path/to/project --apply /private/adapter-plan.json
```

The plan enumerates common model/updater/dispatch, required adoption helpers,
Settings assets and manifest components. It preserves the original workflow source,
distribution/runtime pins and untouched helpers, and records exact adapter source
and owner reference. Adapter reconciliation is never a side effect of opening,
reading or saving Settings. Unconfigured projects remain honestly Unconfigured.

The [destination inventory](settings-external-links.json) records existing Settings
and audit link families for later #83 work without publishing private destinations.
