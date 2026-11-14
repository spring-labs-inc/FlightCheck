# PyPI distribution feasibility — issue #58

Decision: **go for a packaging channel built on the shared installer; no-go for
publication now.** A wheel can carry FlightCheck's command, Python runtime
scripts, Markdown, agent definitions, schemas and browser resources. Installing
that wheel must only install the tool. Project configuration requires a separate,
reviewable command. This experiment does not implement or qualify production
adoption, and is independent of closing [#14](https://github.com/spring-labs-inc/FlightCheck/issues/14).

The shared installer from
[#53](https://github.com/spring-labs-inc/FlightCheck/issues/53) is merged. Reuse its planning,
preservation, configuration and verification logic. Do not maintain
a second production installer in the packaging channel. The sandbox prototype in
[experiments/pypi-installer](../experiments/pypi-installer/README.md) tests packaging
and version retention. Its added explicit `configure` command now delegates to the
merged #53 installer for complete project-local configuration. Real client use and
browser rendering require the separate rehearsal described below.

## Channels and prerequisites

| Property | Immutable Git revision / manual adoption | Proposed PyPI / pipx tool |
| --- | --- | --- |
| Distribution | Clone/download an exact revision; adapt reviewed files | Install a versioned wheel into an isolated tool environment |
| Project writes | Explicit adaptation, preserving the project's policy | Explicit `init` or `upgrade`, delegated to the same installer |
| Reproducibility | Record repository, commit, copied hashes and adaptations | Record distribution/version, wheel digest/attestation, source commit, asset hashes and adaptation plan |
| Updates | Owner selects a new revision and reviews the diff | Upgrading the global CLI does nothing to projects; each project explicitly selects and applies a new bundle |
| Offline use | Local source snapshot and project checks | Retained wheel/tool environment plus copied project bundle and project-owned runtime |
| Main cost | Git/source discovery and manual copying | Packaging/release maintenance, namespace ownership and supply-chain verification |

[PyPA's command-line guide](https://packaging.python.org/en/latest/guides/creating-command-line-tools/)
describes console entry points; [pipx](https://pipx.pypa.io/stable/) provides isolated
application environments and accepts local wheels. Package resources belong
inside the package, with an explicit list that includes dot-directories; see
[setuptools data files](https://setuptools.pypa.io/en/latest/userguide/datafiles.html).
The adopter's application does not import FlightCheck or add it to its runtime
dependencies. No `sudo pip`, post-install hooks, automatic agent hooks, global
`~/.codex`/`~/.claude` writes or implicit permissions expansion is needed.

Prototype prerequisite: Python 3.9+ on POSIX, Git for recording source provenance,
and the isolated build tools listed in the experiment. Verification has only been
run on the development host and Python recorded in the evidence. Production
support needs an explicit Python/macOS/Linux test matrix and the shared installer's
requirements. A `py3-none-any` wheel tag describes packaging compatibility; it does
**not** establish Windows support. Existing evidence scripts use POSIX facilities.
Windows is unsupported by this prototype. Native Windows and WSL need separate
qualification; WSL is not a native Windows support claim.

The original exploration baseline targeted Codex. The current bundle includes the
merged #53 installer, which generates the selected Codex or Claude adapters. Their
installation establishes neither native client discovery nor an enforced reviewer
boundary. The real local Claude trial remains in #14; Claude is not qualified by this
Codex rehearsal. Merged #54 supplies the portable per-reply card prepare/check guard,
whose actual native use and remote route must be verified separately. A portable HTTP card can work
without an embedded browser; browser routing/rendering and remote forwarding need
separate observations.

## Names and proposed user interface

Read-only PyPI JSON requests on **2026-11-13 at 15:51 UTC** returned HTTP 404 for
both `flightcheck` and `flightcheck-cli`. This only shows no public listing was
visible; it does not reserve a name or establish it can be registered. PyPI may
block names under its [name policy](https://docs.pypi.org/project-management/name-retention/).
Confirm owner-controlled registration and normalized-name availability immediately
before any separately authorized release. Do not recommend an index install until
that succeeds. `flightcheck-distribution-prototype` is an unpublished local build
label, not an invitation to install a similarly named index project.

These **production commands are proposals**, pending integration and review:

| Command | Proposed behavior |
| --- | --- |
| `flightcheck init PATH` | Detect clients, checks, branch and policy; batch unresolved project decisions; emit a plan/diff by default. `--apply PLAN` applies only that reviewed, hash-bound plan. |
| `flightcheck doctor PATH` | Read-only completeness, hashes, provenance, configuration and runtime checks. Report client probes separately. Explicitly requested smoke checks may use synthetic fixtures/loopback and need their normal permission boundary. |
| `flightcheck status PATH` | Read project and active-flight pins, check readiness, and show the stable local card URL if published. Do not treat a reachable endpoint as rendered UI or a complete flight. |
| `flightcheck upgrade PATH --to VERSION` | Produce old/new hashes and text diffs, conflicts and backup plan. Applying requires a fresh plan and expected old pin. Refuse while an affected flight is active. |
| `flightcheck remove PATH` | Preview removal of unchanged generated files/owned instruction blocks only; retain edited files, project policy, evidence and backups. Require explicit application. |

Proposed output has a human-readable unified diff plus structured JSON containing
the source and target version, before/after hashes, new paths, removals, conflicts,
unresolved decisions, backups, approval surface and expected final verification.
Plans must not expose private evidence paths or credentials in public cards/logs.
Installation and normal status checks do not contact a provider or create a PR.

## Project preservation and transactions

Project-local installation defaults to explicit workflow selection. Preserve the
owner's existing AGENTS.md, CLAUDE.md, nested overrides, permissions, rules, hooks,
dependency files and application license. Adapt only identifiable FlightCheck-owned
blocks; never replace entire existing instruction or configuration files. A separately
recorded owner decision can enable default-for-coding routing. Ordinary questions
retain their existing entry point. Installing package files does not trust hooks.

Before applying, verify every planned input hash, path, parent, permission and
conflict. Reject links/unsafe paths and unmanaged collisions. Detect changes since
the preview and stop without partially replacing policy. Repeated application of
the same version and resolved configuration must make no further edits. Preserve
original modes; do not broaden access to source or private evidence.

Production application needs a project transaction lock shared with flight startup,
same-filesystem staging, durable backups of affected bytes and modes outside tracked
source, and an explicit recovery journal. Publish a new pin only after installation
and verification succeed. On failure retain the old usable state and report the
recoverable staging/backup locations; never quietly overwrite local edits. Backup
and recovery durability under disk-full, process death and concurrent agent writes
must be qualified before production use. The prototype only serializes its own CLI
calls and stages directory/lock renames; it does not make crash-durability claims.

`pipx uninstall` removes the global tool environment and launcher. It does not remove
generated repository files, project runtimes, FlightCheck-owned instruction blocks,
private evidence or retained backups. Explicit project removal is a separate operation
with a preview, edit/conflict checks and active-flight protection. Never garbage-collect
a bundle or runtime referenced by a flight. Keep evidence according to the project's
retention policy even after removing its configuration.

## Version, runtime and flight stability

Production layout should keep immutable bundles by content digest under project-local
managed storage, a versioned project lock and a small stable launcher/adapter. The lock
records the tool distribution/version, wheel SHA-256, origin/attestation, immutable
source revision, full asset manifest/hashes, installer/configuration schema versions,
adapted-file before/after hashes and the project runtime identity. Keep wheel digest
external to the wheel's own manifest to avoid a self-referential hash.

Use a project-owned pinned environment outside the global pipx environment for flight
execution, with an explicit Python path/version and pinned dependency/input manifest.
The package installation must not silently create or upgrade that runtime. A flight
freezes the exact bundle/configuration/runtime and executes its six adjacent scripts
from those paths, rather than resolving whatever `flightcheck` is now on PATH.
Upgrading or uninstalling the global CLI then cannot silently alter an open flight.
Runtime disappearance/drift is an actionable blocker; it is not a reason to select
a different interpreter automatically. Record the stable private evidence/card route
independently of the global tool environment.

The prototype records the resolved Python executable path, executable SHA-256 and
Python version, and verifies executable bytes. This deliberately avoids pinning a
pipx launcher path, but it does **not** freeze the interpreter's standard library,
dependencies or operating system. It is not a production runtime manager. Follow-up
must implement and test the project-owned runtime/dependency contract.

The sandbox prototype copies a bundle once under `.flightcheck/versions/DIGEST`,
with `.flightcheck/lock.json` selecting it. Global CLI replacement leaves those
files untouched. A synthetic ongoing flight is a file under `.flightcheck/active/`
containing its bundle/runtime pin; any entry there blocks an explicit upgrade.
This representation is a fixture, not integration with real flight activation.
The production adapter must use the actual controller's frozen flight records and
coordinate activation and upgrade atomically. Completed-flight cleanup and explicit
version rollback/garbage collection require their own reviewed behavior.

## Packaged asset contract

[assets.json](../experiments/pypi-installer/assets.json) is the complete, explicit
prototype inventory. The builder reads those canonical files without maintaining
divergent copies, preserves their repository-relative paths under package resources,
and fails on missing or linked inputs. The generated manifest records each hash,
source commit, development dirty-state flag, CLI hash and version. Tests compare the
wheel against both this inventory and the complete tracked canonical directories.

| Resource group | Included prototype source paths |
| --- | --- |
| Shared evidence runtime | All six `examples/existing-project/scripts/*.py` files, adjacent and unchanged |
| Workflow/setup | Example README, AGENTS.md, CLAUDE.md, requirements, shared workflow and project-resource index |
| Shared skill | `.agents/skills/develop-change/SKILL.md` and its task-status reference |
| Codex adapters | Both `.codex/agents/*.toml` roles, sample hooks and read rules as inert assets |
| Portable card | Every tracked `status-card/` script, task/detail/tab/publisher/maintainer module, HTML, CSS, JavaScript and synthetic pilot JSON |
| Notices and references | Root LICENSE, README, CONTRIBUTING, licensing guide and status-card guide |
| JSON schema | The new prototype lock schema; it is not the authoritative shared flight/evidence schema |

The original source has no standalone authoritative shared JSON schema files. Do not
invent a second schema for handoff.py; its existing Python validation remains canonical.
Installer manifests, configuration validation and generated client adapters remain
owned by the canonical shared installer. Add future resources from their reviewed
canonical paths rather than maintaining packaging-specific copies. The static root README
and status guide contain links to other repository documentation: bundled notices are
reference material, not a self-contained copy of the entire website. Production help
must preserve working installed documentation links or use revision-pinned source URLs.

## Metadata, license and release proposal

The local build declares a planning-stage distribution, console entry point,
Python >=3.9, POSIX classifier, canonical source/issue URLs, no runtime dependencies,
`License-Expression: FSL-1.1-MIT`, and the exact root LICENSE in wheel license files.
The [current license](../LICENSE) and [licensing guide](licensing.md) govern the
distributed workflow portions. Do not advertise an OSI-approved classifier or MIT-only
terms for a new FSL release. Personal/internal organizational commercial use remains
free under the existing terms; a version's MIT transition remains two years after
its publication and is not reset by a later CLI upgrade. Retain notices and each
version's first-publication date. This exploration changes none of those terms.
See [PyPA's licensing guidance](https://packaging.python.org/en/latest/guides/licensing-examples-and-user-scenarios/)
for package metadata; the metadata does not replace the included license.

Before a separately authorized release:

1. Qualify the packaged shared installer and complete supported client assets. Freeze
   a clean release source/tag, version and publication-date/license record. Verify
   collaborator contribution rights under CONTRIBUTING.md.
2. Build in a pinned isolated environment from a clean source archive. Compare sdist
   and wheel inventories, dotfiles, hashes, notices, entry points and metadata; run
   metadata checks and fresh offline installs from both artifacts. Test supported
   Python/POSIX clients, full contributor suite, installer failure/recovery, real
   discovery/reviewer permissions, card publication/browser rendering, flight pins
   and global upgrade/uninstall behavior. Reproducible builds require their own proof.
3. Propose an owner-controlled PyPI project with minimal maintainers and 2FA, and
   [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) bound to the exact
   GitHub owner/repository/workflow and protected release environment. Require owner
   environment approval and a protected version tag. Give `id-token: write` only to
   the publish job, pin action revisions, and publish already-verified artifacts with
   provenance attestations and external checksums. Avoid long-lived PyPI tokens.
4. Inspect the actual uploaded artifact digests, metadata, notices and attestations;
   test a fresh isolated download/install before recommending the confirmed command.
   Define incident/yank procedures; yanking cannot undo already installed project files.

These are proposed follow-ups, not an installed workflow or authorization to configure
accounts, tokens, CI publishing, TestPyPI or PyPI. Nothing in this experiment uploads
packages or changes global agent settings.

## Validation and next scope

The experiment README gives exact local reproduction commands. The checks use two
locally built versions, fresh wheel environments, disposable sandbox targets and
synthetic project policy. They inspect actual wheel bytes, run packaged handoff/card
entry points, verify card HTTP resources, exercise nonwriting previews/idempotence,
replace the CLI during an ongoing synthetic flight, preserve old bundles, and reject
stale pins, corruption, missing files and links. Those automated tests do not establish native client discovery or browser rendering.
The separate rehearsal uses pipx itself and actual client sessions; browser acceptance
comes from the owner observations, not HTTP assertions.

The independent preservation challenge compares the documented manual channel's
explicit file-copy adaptation against the wheel's initialization using the same
protected-file assertions. Its baseline control is a recorded manual adoption of
the frozen Git source, not a claim that an installer CLI existed at that revision.
Other prototype behaviors need sensitivity controls using documented invalid
mutations, since the baseline has no packaged installer.

The bounded prototype now integrates the shared installer. Recommended next scope
is runtime/active-flight locking and recovery, installed documentation/schema integrity,
client/platform qualification and artifact/release hardening. Keep the pinned Git
channel available. Only after those checks and separate owner authorization should
the project select an available package name and publish a first release.

## Expanded acceptance after the initial packaging rehearsal

The initial pipx rehearsal did not verify a real selected flight or browser appearance.
The owner requires both before landing. The added `configure` adapter invokes the
unchanged merged #53 installer from a verified embedded shallow source snapshot,
retaining the original commit/tree and preserving existing policy. The source
archive contains only the pinned tracked tree, not repository history. The seven
original lifecycle checks are retained, alongside a complete configuration check.

The rehearsal requires a fresh installed native session, actual selected-flight
planning/implementation/native checks/controls/CODE/EVIDENCE/verdict, user-visible
card links, live stage/check observations and repair/resume. Retain original client
transcripts, exact checked reply drafts, controller receipts, independent reviews,
validated verdicts and owner observations in the private task review packet.
Browser automation was unavailable on the rehearsal host. The owner observed the
initial card title and “Snapshot rendered,” a live stage change, and the repaired
Cheap Tests / running native check / Pending state. These observations establish
browser rendering; HTTP success alone cannot substitute for them.

The current package includes merged #54's explicit per-reply guard. A fresh native
session must prepare the real card before its first reply, retain the exact draft
and actual check result, and preserve the owner-observed forwarded browser URL on
resume. The initial older client trial guessed a link before publication; its
failure is retained. The #54 trial uses the published route and correctly reports
remote routing unavailable until an owner supplies the browser-facing URL. The
owner subsequently observed the current card and supplied its actual forwarded
route. A successful explicit check does not establish automatic interception of
streamed messages or qualify other clients.

A disposable delivery-fee change exercises threshold, equivalent numeric, existing
behavior and negative-input tests. Run the identical tests on the frozen original
product: the new threshold must fail and compatibility must pass. Run the current
product through the installed recorder, then separate read-only CODE and EVIDENCE
sessions, and validate the actual final verdict. Return a completed flight to repair:
the same candidate must lose APPROVE, a changed candidate must reject the old verdict,
and current proofs and independent reviews must be refreshed. Qualify the retained
record assertions with a separate serializer mutation that exposes the stale verdict;
never mutate the actual card, original reviews or owner observations to make a test
pass. The private final packet records whether all these requirements are satisfied.

The package remains unpublished. The rehearsal may install it by name/version through
a loopback PyPI-compatible simple index, with isolated pipx directories and no global
agent configuration changes. Public PyPI delivery remains unverified until separately
authorized publication. No prior approval for the narrower prototype is a landing
grant for this expanded candidate.
