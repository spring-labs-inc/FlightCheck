# Verified native flight checkouts

FlightCheck verifies the checkout selected by the coding client. It does not
create a second worktree manager. The shared configuration, private Registry and
related-work detector remain the sources of policy and ownership.

## Select and bind before editing

Run the lightweight related-work detector before choosing competing work. Resolve
its resume, reuse, wait or deliberate dependent-flight decision. Unrelated work is
informational; a matching directory name or branch prefix proves no ownership.
Prefer a suitable recorded checkout, including one created by another client.
Use the client's native creation, adoption or recovery mechanism when available.

`native-choice` is the default confirmed checkout policy. A safe dedicated branch
in an existing checkout and a suitable linked worktree are both valid. No special
branch-only opt-in is needed. Explicit `worktree-required` policy requires a
separate flight worktree and must not silently degrade. Standard Git creation is
a fallback only when native mechanisms are unavailable and the confirmed policy
and recorded decision permit it. FlightCheck's helper never creates or switches
checkouts itself.

The controller records the actual repository, pinned base, confirmed configuration
snapshot, native operation/capability observation and one main execution checkout
through the existing `flight_associations.Registry`. Editing children belong to
that flight; read-only reviewers do not need their own worktrees. The source and
matching packaged CLI route to the same helper:

```sh
python3 -B setup/install.py checkout --help
python3 -B workflow/scripts/checkout_guard.py --help
```

Use the helper's `adopt`, `verify`, `reconcile` and `release` operations with the
private flight record and actual selected checkout. The confirmed configuration
comes from the common model. Source development may supply its controller's
explicit private configuration snapshot without installing into the repository.
This is a retained flight binding, not a second project defaults store.

## What verification establishes

Verify actual root and common Git directory, provider repository identity,
authoritative default and protected branches, intended base ancestry, ownership,
main/child role and effective checkout policy. Cached `origin/HEAD` or a displayed
worktree label alone does not establish the actual policy. Unavailable required
facts produce a specific blocker. Provider policy support and its observation
limits are reported rather than generalized to untested hosts.

An isolated native detached checkout can remain detached during implementation,
checks and review, with its commits tracked. Delivery requires an appropriate
dedicated, unprotected branch. Neither policy permits edits on actual default or
protected branches. Unknown ownership, a conflicting unfinished owner, unsafe
base/repository identity or unavailable required isolation prevents execution.

Selected context uses `task.checkout_binding` with `registry` and `flight`, explicit
controller context, or the actual checkout's owner in the default Registry. The
default private location is the existing FlightCheck state root, clone namespace
and `flight-associations` directory. This lookup does not create a registry.
Explicit conflicting or broken context fails closed. Standalone legacy evidence
helpers without selected ownership remain usable; this compatibility is not a
fallback for a selected flight.

Controlled checks verify before fingerprint/reuse or native command execution and
retain the actual before/after execution binding. Review preparation and approval
verify the same context, using existing dependency/access bindings. A receipt from
another checkout or unreconciled generation cannot become current by copying its
files. No guard grants provider-write or cleanup authority. Native write boundaries
and capabilities are recorded honestly; these checks do not intercept arbitrary
commands outside FlightCheck-controlled operations.

## Resume and explicit reconciliation

Resume returns to the recorded checkout and verifies repository, client/session,
branch or detached commit, configuration binding and unfinished work. Ordinary
commits on the recorded lineage do not require another worktree. A missing,
locked, restored, moved or conflicting checkout needs the available native recovery
operation and explicit reconciliation where identity is uncertain. Do not allocate
a new worktree merely because the client changed.

Reconciliation retains prior identity, commits/provenance, task/card and private
external evidence, records the decision and affected revalidation, and verifies the
actual destination. A restored path or a client's name alone does not establish
identity. Uncertain preservation is a blocker, not permission to discard work.
Project-default changes do not silently rewrite active flight snapshots or grants;
explicit reconfiguration and affected revalidation use the shared model.

## Downstream handoff and close

Private records supply #83 the actual execution location, host and branch or
verified detached commit; the publisher/listener directory is not a substitute.
#83 owns presentation. #111 consumes the same repository-qualified associations.
#81 receives main/children, native/manual management, preserved-existing versus
disposable-temporary classification, commits, delivery targets and disposition.

Release execution ownership only after the recorded closeout/handoff decision
and the required [lifecycle disposition gate](flight-lifecycle.md) pass inside
PR & Merge. Retain records, outstanding obligations and all preservation proof.
Eligible authorized cleanup must be attempted. An explicit setup-approved
retention policy may permit **closed with retained artifacts**, with actual
outcomes, reasons and next actions recorded. This does not waive required tests,
review, implementation or merge. Retained ownership reservations and unknown
operations survive closure and block conflicting adoption/reconciliation while
unrelated work remains permitted. Missing/uncovered disposition stays pending.
Existing markerless and no-policy records remain compatible without invented
retention acceptance or deletion grants.
#81 owns cleanup authorization, integration/preservation proof and native
cleanup/reconciliation; #82 supplies no deletion, retention or snapshot system.
Preserve an existing repository checkout used for branch-only work. Keep the PM
in stable same-clone control and bind a delegated implementation worker as the
actual main source checkout. Separately authorized ordinary Git-managed workers
outside client-managed directories retain explicit manual provenance and cleanup
authority; never use that authority to remove client-managed artifacts. Temporary
worktrees are merely eligible for later verified disposition. A merged PR alone
does not prove required disposition complete. Closed cards can retain historical
identity without claiming the checkout still exists.

## Costs and shared resources

Branch-only work shares that checkout's files, index and editor selection. A
worktree adds checkout/bootstrap and disk costs while sharing Git objects and some
configuration. Select the actual execution checkout in the client/editor; private
or ignored configuration is not automatically copied between worktrees. Keep
private evidence outside disposable locations. Worktrees do not isolate ports,
services, databases, caches or other external mutable resources; coordinate those
resources separately. Neither mode authorizes overwriting unrelated edits.

These commands are source capabilities. Existing installed projects and immutable
packages remain pinned until separately authorized delivery; running the source
helper does not install or upgrade them.
