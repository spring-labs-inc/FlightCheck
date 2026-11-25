# Flight launch, closeout and repository audit

FlightCheck uses the existing confirmed configuration and private flight Registry.
Native clients select and manage their checkouts. Lifecycle operations reconcile
explicit flight artifacts; the audit observes the whole discoverable repository
and recommends separate actions.

## Launch and concrete authorization

From a FlightCheck source checkout, run the lightweight detector before editing
or creating competing work:

```sh
python3 -B setup/install.py lifecycle launch --checkout /path/to/project --registry /private/registry --repository owner/repo --issue 123
```

The packaged terminal entry point is `flightcheck lifecycle`; copied workflow
helpers are available under `.flightcheck/scripts/flight_lifecycle.py`. Use each
operation's `--help` for its exact private JSON inputs. A command does not install,
upgrade or reconfigure an existing project.

Use explicit repository-qualified flight, issue, PR and checkout associations.
Uncommitted/staged/untracked work belongs to a checkout. Related branch comparisons
report unmerged/unpushed indicators from their stated observations. Naming or file
overlap can suggest investigation but cannot establish ownership. Return to the
recorded flight, reconcile a paused one, wait, or record a deliberate dependent
flight; unrelated work stays informational. This launch operation is not the full
audit.

During setup, record a concrete cleanup inventory and the owner's existing scoped
cleanup grant separately from delivery. Identify exact worktree paths and Git
administrative identity, local refs, actual remote/push endpoints and refs, owning
flight/client, and preserved-existing versus disposable-temporary classification.
Do not interpret a branch prefix, historical handoff, merged PR or audit report as
a deletion grant. `lifecycle register` consumes a grant; it cannot create one.
Unexpected artifacts require a separate decision instead of a broader inventory.

Newly adopted flights carry required cleanup state. Missing authorization remains
pending. A helper save cannot remove that protocol to obtain legacy closeout.
Existing markerless records remain readable without reconstructing archives or
inventing historical grants.

An otherwise clean worktree can contain ignored private data. Preserve unknown
ignored files. For expressly owned generated assets, record producer provenance,
exact file hashes/modes and verified external copies within the authorized ignored
scope. A prefix alone never proves ownership or preservation. Confirm the native
client's actual recovery coverage rather than assuming archive preserves every
kind of file. Keep private evidence, task-card history and necessary helper/card
runtime assets outside every disposable worktree.

## Setup-approved retention policy

Cleanup authority and retention approval are separate. A flight may declare an
explicit owner `grants.retention` policy during setup, using the existing Registry:

```json
{"schema": 1, "authority": "owner", "reference": "private-owner-decision.json",
 "allowed_reasons": {"native_unavailable": {
   "next_action": "Reconcile supported native cleanup when available",
   "responsible": "Flight owner"}}}
```

Registration binds the policy and its digest alongside the exact cleanup scope.
An absent policy keeps existing closeout behavior; it does not invent acceptance
for legacy records. Retain original decisions and operation history. Silent policy
widening or changing frozen authority/leases is prohibited.

The policy is not permission to skip eligible cleanup. Record each artifact's
identity, observed existence, actual operation outcome, reason, next action,
responsibility and policy reference. Unknown identity or existence stays unknown.
A failed or unknown operation may qualify only for expressly approved retention;
it never becomes successful removal. Merely emitting a native-action request is
not an attempted cleanup or evidence of an unknown native outcome.

## Verified disposition inside PR & Merge

Cleanup follows the confirmed actual merge. The observer checks repository,
recorded base, delivered source head, actual target and pinned integration commit.
For merge, squash and rebase delivery, every source-changed path must have the
required blob, mode or deletion at that integration commit. The integration commit
must remain reachable from the currently observed target. Unrelated or later
legitimate target edits do not undo historical integration; new source-branch work
blocks cleanup. An ancestry count, patch-id, pushed label or whole-tree comparison
alone cannot establish this proof. A missing upstream or deleted remote branch
must not defeat otherwise proven integration. Missing objects or uncertain proof
remain concrete blockers; the observer never fetches them automatically.

`lifecycle plan` freezes the authorized identities and delivered tips. `apply`
rechecks ownership, grant, protection, checkout/client state and source/target facts
immediately before each selected action. Preserve the repository main checkout,
protected/shared refs, other active owners, locks, dirty/staged/untracked work,
unknown ignored data, unintegrated commits and ambiguous artifacts. An owned main
temporary worktree is eligible only when those conditions pass; it is distinct
from the repository's main checkout.

Keep the PM in stable control and safely leave/release the execution worktree
before removal. Use the supported client operation for a client-managed worktree. Without that operation, the helper
returns a bound native-action request rather than deleting its directory. Retain
the actual native result and acknowledge it through `ack-native`; client identity
and observed absence of both the path and Git administrative entry are necessary.
A success flag alone cannot establish successful cleanup. Separately authorized
Git-managed workers can use ordinary `git worktree remove` without force only
when their recorded manual provenance, explicit `git_managed` grant and all
current checks permit it. This is not a fallback for a client-managed worktree;
never manually remove a Codex-managed artifact. A retained control checkout in
the same clone and an externally preserved, verified helper runtime allow
reconciliation after the execution path is removed, without adopting another main
checkout or changing its files.

Local ref removal and actual remote branch deletion are conditional on the exact
previous OID. Recheck the endpoint and checked-out/protected state. Remote-tracking
ref removal is not actual remote deletion. A changed source or remote tip retains
the new work; repeating a plan cannot silently refresh its lease. Persist intent
before mutation and reconcile actual outcomes afterward. On interruption, resume
the same authorized inventory and distinguish removed, already absent, retained,
failed and native-action-pending artifacts. A failed remote query cannot establish
absence; a recreated artifact cannot inherit an old removal result.

Attempt every independently eligible authorized action. A blocked worktree must
not prevent safe remote-ref cleanup. A branch still checked out in a preserved
worktree remains retained. Global authority, actual merge and integration failures
still prevent unsafe mutation; all other current preservation checks remain in
force.

The required close gate belongs to **PR & Merge**, not a tenth stage. Its outcomes
are **closed—cleanup complete** or **closed with retained artifacts**. Every scoped
artifact needs verified cleanup or policy-accepted retention; missing accounting,
an uncovered reason or absent next action keeps disposition pending. A merged PR
alone is insufficient, and retention does not waive implementation acceptance,
required tests/reviews or delivery. Cleanup completeness and disposition
completeness are separate; retained, failed and unknown outcomes are not cleanup
success.

Closeout releases execution sessions from stable control while preserving relevant
artifact ownership reservations and unresolved obligations. Closed retained flights
remain visible to related-work detection and audit. Unknown operations prohibit
conflicting or duplicate mutations until reconciled, including when no physical
path or native administrative identity was observed. Record the known request and
exact target reservations without inventing an artifact. Unrelated safe work is
not blocked. A next action confers no new deletion grant; deferred cleanup must
revalidate authority, identity, current state and exact original OID conditions.

Preserve evidence and accurate historical identity on the closed card. After
actual removal of the execution checkout, use the existing portable publisher and
retained assets without substituting the control checkout for the historical
execution location. Native capability/archival coverage must be reported
separately: deterministic outcome tests or accepted retention do not establish
successful live native archival.

## Optional on-demand audit

The full audit is an explicit user/agent trigger, separate from lightweight launch.
From a FlightCheck source checkout:

```sh
python3 -B setup/install.py audit --checkout /path/to/project --registry /private/registry --repository owner/repo
```

The packaged entry point is `flightcheck audit`; the copied helper is
`.flightcheck/scripts/repository_audit.py`. It emits a report to stdout. Retain the
report outside the audited repository when desired. No selected flight, Registry
creation or project installation is required merely to inspect a repository.

The inventory covers discoverable worktrees, local branches, actual advertised
remote branches, cached remote-tracking refs and recorded missing paths, including
manual/non-FlightCheck artifacts. Each row identifies its ref/OID or path, known
explicit owner/client/flight/PR, checkout dirty/untracked/ignored state where
applicable, checked-out/locked/protected or active state, target/integration
indicators and an actionable recommendation with reasons and prerequisites.
Worktree existence and a closed Registry record do not prove native inactivity.
Include closed retained obligations and known unresolved operations, even when
physical identity is unavailable. Report their policy, actual outcome, retention
reason, next action, responsibility and exact reservations. Keep missing identity
and native coverage limits explicit; recommendations remain read-only.

Audit is strictly read-only: no fetch, even without prune; no prune, delete,
archive, checkout switch, commit, stash, configured-check execution or client-state
write. Use bounded read commands with optional locks and filesystem monitoring
disabled. Unsafe/custom remote helpers, unavailable authorization or policy,
unknown client activity, remote-only OIDs absent locally and truncated observations
remain explicit coverage limits. Distinguish fetch and push endpoints and cached
observations from actual remote facts. Never hydrate missing objects to make the
audit appear complete.

A report may recommend preserving or investigating many artifacts. That is a
valid result. Recommendations describe what to remove, retain, resume or
investigate and why; they provide neither cleanup authority nor a reusable promise
of future safety. A later separately authorized action must revalidate its exact
current state. This feature adds no worktree-count manager, snapshot system,
retention scheduler, Settings UI or provider-status synchronization.

These are merged-source capabilities. Existing copied projects and immutable
published packages keep their pinned code until a separately authorized update.
