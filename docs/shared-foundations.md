# Shared configuration and launch foundations

This prerequisite delivery belongs to #84 and leaves #80, #81 and #82 open.
It supplies configuration/update/revision APIs, private flight associations and
an association-first unfinished-work detector. Settings UI, checkout enforcement,
cleanup and repository-wide audit, synchronization and card presentation remain
with their owning issues. These commands grant no provider or cleanup authority.

## Configuration reads and explicit updates

Setup and the terminal CLI use `workflow/scripts/project_config.py`. The canonical
configuration remains the flat-compatible **private local**
`.flightcheck/project.json`; `_flightcheck` holds versioned field provenance,
confirmation and validation metadata. The revision is SHA-256 of the exact saved
bytes. A shared view is an allowlisted projection, not another defaults store.
Host paths, runtimes, commands, free-form resources and decision references stay
out of that projection. Unknown legacy provenance is not historical confirmation.

In the source checkout, use the source entry point; no package build or release
is required. Replace `/path/to/project` and private file paths with your own:

```sh
python3 -B setup/install.py config read /path/to/project --shared
python3 -B setup/install.py config read /path/to/project
python3 -B setup/install.py config preview /path/to/project \
  --changes /private/config-changes.json --expected-revision SHA256 \
  --reference "Owner configuration decision" --plan /private/config-plan.json
python3 -B setup/install.py config apply /path/to/project --apply /private/config-plan.json
```

A CLI built from this source exposes the same operations as `flightcheck config
read|preview|apply`. Immutable published packages and historical installed copies
do not gain new commands on source merge. Use the current source entry point or
a separately delivered matching CLI, preserving the installation being updated.

A minimal changes file is:

```json
{"checkout_policy": {"mode": "worktree-required", "git_fallback": false}}
```

`native-choice` is the default: the checkout verifier accepts either a
safe dedicated branch in an existing checkout or a suitable worktree. An explicit
`worktree-required` policy requires a separate flight worktree; it must not
silently fall back. Both policies retain the actual confirmed default branch and
additional protected branches in the protected set. Branch prefix and confirmed
Git fallback are optional policy data, not a checkout manager or authority to
create anything. The foundation records and validates the policy; #82 supplies actual checkout
verification, protection and enforcement through the [native checkout
contract](checkout-verification.md). Native clients still select and manage their
own checkouts. #81 retains cleanup/audit and #83 retains presentation.

The bounded update path supports checkout policy, default/additional protected
branches, recorded checks and resource pointers. It refuses runtime, evidence-root,
activation, delivery, reviewer permission and other authority changes with an
explicit reconciliation blocker. It never runs configured checks while saving.
An update does not migrate installed workflow files or a runtime pin.

Preview records the target/repository, expected revision, changes and operations.
Apply rechecks them under the existing transaction lock. A stale edit is refused;
failed/interrupted writes retain recoverable prior bytes and modes. New source
installations keep host-bearing config/status files ignored and private. Updating
an existing installation requires those files to be untracked; a tracked file is
a separate remediation blocker and the update never edits the index. The plan
includes required private modes/local ignore safeguards and only the config hash
in installation metadata changes. Retain private plans and recovery backups. For
an interrupted source configuration update, use `python3 -B setup/install.py
config recover /path/to/project`; recovery refuses to overwrite later owner edits.

## Flight identity and configuration binding

`workflow/scripts/flight_associations.py` provides the schema and `Registry` API.
Installed source copies place it under `.flightcheck/scripts/`. Use a private
owner-only registry directory outside every execution checkout. A registry write
uses an expected revision and atomic publication; a read never creates a store.

An association records these explicit facts:

- Repository identity and this clone's canonical common Git directory; repository-
  qualified scoped issue and PR numbers.
- Stable flight/task/card IDs and native client/session associations.
- One main checkout and optional children, each with actual path, recorded branch
  or detached commit, native/manual management and `preserved-existing` versus
  `disposable-temporary` classification.
- Confirmed configuration revision and effective private values, separately scoped
  grants, delivery target, lifecycle and disposition.

`repository_identity(checkout, repository_id)` observes the common Git directory.
`Registry(directory).read()` returns its current revision and records;
`save(record, expected_revision=revision)` validates and publishes one record;
`get(flight)` and `related(repository_id, issues=..., pull_requests=..., flights=...)`
resolve only explicit associations. One unfinished owner per canonical main/child
checkout is allowed. A matching name, branch prefix, issue number in another
repository or overlapping files does not establish ownership or dependency.

The common model's `snapshot(project)` returns `revision` and `values` for a
flight binding. Project-default updates never rewrite the flight snapshot or its
grants. `reconfigure(record, snapshot, reference)` explicitly records a new binding,
retains prior binding history and grants, and returns required checkout/check/
evidence revalidation categories. Callers must actually perform that revalidation;
the returned list is not evidence that checks ran. The schema and registry are
interfaces, not native-client recovery, universal command interception or cleanup
integration proof. Keep all records and historical bindings private.

## Lightweight related unfinished-work detection

Before choosing competing work, run the detector with the explicit repository
identity and scoped associations:

```sh
python3 -B workflow/scripts/launch_detection.py \
  --checkout /path/to/project --registry /private/flight-associations \
  --repository owner/project --issue 82
```

Installed projects use `.flightcheck/scripts/launch_detection.py`. Optional
`--pr`, `--flight` and `--current-flight` selectors reuse the same registry/API.
`detect(checkout, registry, repository_id, ...)` is the shared operation.

The JSON report distinguishes recorded associations from current observations.
Dirty tracked files and untracked files belong to **checkouts**; unmerged and
unpushed commit counts belong to branches or detached commits where comparison
is meaningful. Target/upstream comparisons use available local cached refs.
Missing upstream, missing or changed checkout identity, locked worktrees and
unavailable native-client state are reported honestly. A branch's ancestry count
is an unfinished-work indicator, not squash/rebase delivery or cleanup proof.

Related work produces an actionable resume, reuse or wait decision and a deliberate
dependent-flight alternative. Unrelated unfinished work is informational and
never blocks launch. The detector reads worktree state and only related branch
comparisons; it is not the future repository-wide audit. It does not fetch, prune,
create/switch a checkout, commit, stash, delete or modify registry state. The caller
must resolve the reported decision; the detector does not enforce a launch gate.

## Verification and delivery boundary

`tests/test_foundations.py` supplies the five frozen acceptance identities using
config and flight case mixins. They cover shared entry-point validation/private
projection; revision races and failure recovery; active-flight revision/grant
isolation; repository-qualified ownership; related/unrelated detection and unchanged
Git state. Required contributor checks still apply. Conditional early CODE and one
independent final skeptical code-and-evidence review remain unchanged.

The concurrent #117 benchmark flight owns its six benchmark/documentation files.
Foundations do not change its tooling, recorder/handoff/status-card contracts,
production review policy or accepted #106 archives. Merge #117 first, then reconcile
and land foundations sequentially with genuinely affected integration checks.

## Checkout integration

The [checkout verifier](checkout-verification.md) consumes these APIs without
creating another ownership store or changing project defaults. Configuration
updates preserve active snapshots and grants; explicit reconciliation revalidates
affected assumptions. This integration does not complete #81 cleanup/audit, #80
Settings or #83 presentation, or close their parent epic on partial delivery.

## Required lifecycle and full audit

The [lifecycle contract](flight-lifecycle.md) consumes this configuration, Registry
and launch interface. `setup/install.py lifecycle` records concrete cleanup scope,
proves actual delivery and reconciles authorized native worktree/ref disposition
inside PR & Merge. New flight records require completion before ownership release;
legacy markerless records remain compatible without receiving new grants. Private
operation intents/outcomes remain in the existing Registry, with external proof
references rather than a second ownership store.

`setup/install.py audit` supplies the complete optional repository-wide report,
including manual/unowned artifacts, actual remote heads and cached observations.
It is an explicit read-only operation with no fetch/prune or cleanup authority.
#80 retains Settings, #83 presentation and #111 synchronization.
