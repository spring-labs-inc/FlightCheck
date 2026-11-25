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

Safely leave the execution worktree before native removal. Use the supported
client operation for a client-managed worktree. Without that operation, the helper
returns a bound native-action request rather than deleting its directory. Retain
the actual native result and acknowledge it through `ack-native`; client identity
and observed absence of both the path and Git administrative entry are necessary.
A success flag alone cannot complete disposition. A retained control checkout in
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

The required close gate belongs to **PR & Merge**, not a tenth stage. A merged PR
can coexist with a flight still blocked on cleanup. Eligible disposable artifacts
must actually be removed or proven absent; runtime blockers cannot be relabeled as
successful retention. Predesignated preserved-existing artifacts receive explicit
retained disposition. Release execution ownership and close only after the fresh
gate passes. Preserve the evidence and accurate historical identity on the closed
card. After authorized removal of the execution checkout, use the existing
portable publisher and retained assets rather than substituting the publisher's
checkout for the historical flight location.

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
