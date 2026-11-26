# Project status synchronization

The synchronization policy lives in the existing private
`.flightcheck/project.json` document. Setup and the configuration CLI use the
common model's revision-safe read, preview, apply and recover operations. There
is no second synchronization configuration file. Settings consumes that same
model; this interface does not itself implement Settings or provider writes.
The separate lifecycle operation below performs the scoped provider writes.

`status_sync_config.normalize(value)` defines schema 1. Missing configuration
defaults to `mode: "disabled"`. Modes are `disabled`, `advisory` and `required`.
An enabled policy requires an opaque `provider` identifier, exact `project_id`
and `field_id`, and an `options` map with distinct provider option IDs for
`todo`, `ready`, `in_progress`, `review` and `done`. Labels and English board
names are not identities. `membership` is `existing-only`; no mode implicitly
adds an issue to a project. Unknown providers can be recorded but require an
explicit unsupported outcome from provider resolution.

The common configuration model validates these fields, records project scope
and confirmation provenance, and detects stale updates using the exact stored
byte revision. Provider identities and confirmation references stay out of the
allowlisted shared card projection. Changes affect future flights by default.
An active flight keeps its captured configuration and grants; explicit
reconfiguration adds `status_sync` and evidence revalidation when this field
changes. It never silently retargets an existing grant.

`normalize_grant(value)` validates a separate `grants.tracker_status` object in
the existing flight association. Its exact fields are `schema: 1`,
`authority: "owner"`, an actual owner decision `reference`, repository identity,
`provider`, `project_id`, `field_id`, unique positive `issues`, and the active
snapshot's `configuration_revision`. `authorize(grant, repository,
configuration_snapshot, issue)` returns `authorized` and a concise `reason`.
The snapshot uses the common `{revision, values}` representation and must carry
the confirmed synchronization value's provenance digest. A missing, stale or
different scope is denied. This pure function performs no provider operations.
Status authority grants no membership, issue closure, PR delivery, installation
or cleanup permission. Saving configuration grants none of those permissions.

#111 owns this synchronization schema and provider/lifecycle behavior. #80 owns
the common configuration update mechanism and Settings presentation. The shared
model adapter, active-flight revalidation call and packaging entry are serialized
until an immutable reviewed interface commit is explicitly handed off. Later
integration must preserve the mapping, revisions, grants and private projection.

## Invoke actual lifecycle events

The selected workflow invokes this operation once at a real event, never for
card publication, each reply, a planning link or an early CODE substep:

```sh
python3 -B setup/install.py status-sync --checkout /recorded/project \
  --registry /private/flight-associations --flight FLIGHT --event /private/event.json
```

Installed projects use `.flightcheck/install.py status-sync`; the terminal CLI
uses `flightcheck status-sync` with the same options. These execute pinned helpers,
not an installation or upgrade. Keep the event a private regular JSON file.

The existing association's `status_sync.work` explicitly identifies each owned
`issue`, its `role` (`implementation`, `implementation_epic` or `roadmap`),
`scope` (`partial` or `full`) and actual decision `reference`. Association alone
does not grant work/status authority. An event has `kind` (`start`, `resume`,
`review`, `repair`, `accepted_completion`), exact changed `issues` and its actual
`reference`. Review additionally requires `ready: true` after scoped full-work
readiness. A first start can advance an observed Todo/Ready/empty status. Resume
preserves the last warranted review state. Later events compare the last verified
Status observation; a deliberate manual/native departure is a conflict, never
authority to reassert. An explicitly authorized reconciliation supplies
`expected` keyed by issue number and its `reconciliation_reference`; use a fresh
provider observation and actual scoped decision, not a copied old board state.
A detected conflict retains its intent, including on the first start, so replaying
that start cannot reinterpret an observed manual Todo as untouched initial work.
To resolve a retained or exhausted intent, supply the fresh exact observation and
a scoped reconciliation decision. A new decision (a new reference or a changed
exact expected observation) retires the old replay authority, records its complete
intent/attempt budget with outcome still unknown, then records a separate bounded
intent before mutation. Repeating the same reference and observation cannot reset
that new intent's attempt budget. Configuration/target changes require resolving
the original scope first; this recovery never grants another issue or field.

The operation uses the captured `{revision, values}` configuration and the
separate `tracker_status` grant. The GitHub Projects v2 adapter uses existing
`gh` authentication, exact project/item/field/option IDs and existing membership.
Missing membership is actionable and never creates another item. Only the Status
single-select value can be changed; Sequence, Priority, labels, parentage and
workflow configuration have no mutation path here. Unknown providers, unavailable
access, incomplete observations and failed writes report explicit unsynchronized
reasons. Required policy returns a blocking exit; advisory policy reports the
outcome and lets the lifecycle proceed. Neither mode claims failed writes passed.

Intent and the last verified observation use a bounded extension of the existing
Registry. The operation reads before writes, checks the Status value/timestamp
again immediately before mutation, and verifies readback. An uncertain response
is reconciled against actual state before at most two attempts with brief backoff.
An acknowledged mutation whose readback is unavailable remains an uncertain
write: its intent and consumed attempt survive same-event reconciliation and
restart. A read failure before dispatch remains distinct and makes no mutation.
A newer manual/native decision is preserved. Unresolved intents remain visible
and cannot silently retarget another event or configuration. GitHub exposes no
atomic compare-and-set: these are optimistic checks, not a guarantee that an
unobserved simultaneous external write cannot occur between the final read and
mutation. Readback detects a changed result; it never grants permission to undo it.
If ownership or completion/disposition verification stops the operation before
provider inspection, the result explicitly reports automation inspection as not
started. Neither an available-metadata fixture nor an unavailable one then proves
that the live native workflow triggers/actions were inspected.

Read actual native workflow metadata when available and report its coverage.
GitHub's supported workflow API exposes IDs, names and enabled flags but not the
trigger/action configuration. Do not infer completion behavior from names or
assume default automation. FlightCheck does not install Actions or a polling job.
Prefer an already aligned native outcome over another mutation. An open issue
is never set Done by this status-only operation, because unknown native actions
could close it without a separate closure grant.

For `accepted_completion`, the explicit `completion` object must contain
`accepted: true`, `full_scope: true` and its actual acceptance `reference` for an
owned full issue scope. The operation additionally requires the released/closed
Registry record, complete verified disposition (including accepted retention),
bound actual merged delivery and current integration, and an actually
closed/completed issue. Perform separately authorized accepted closure first.
Cancelled/not-planned closure, partial work, a merged PR and cleanup blockers do
not meet this contract. Use stable same-clone control and retained verified
helpers after release/removal; the operation never adopts the historical worker.
