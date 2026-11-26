# Project status synchronization

The synchronization policy lives in the existing private
`.flightcheck/project.json` document. Setup and the configuration CLI use the
common model's revision-safe read, preview, apply and recover operations. There
is no second synchronization configuration file. Settings consumes that same
model; this interface does not itself implement Settings or provider writes.

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
