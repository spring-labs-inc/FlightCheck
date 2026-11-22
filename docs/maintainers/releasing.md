# Releasing FlightCheck

**Published alpha.** Distribution `flightcheck`, executable `flightcheck`, and internal module `flightcheck_cli` are published as version `0.1.0a2` ([PyPI](https://pypi.org/project/flightcheck/0.1.0a2/)). The release uses source `2ee1a5325a6e80d466190918391f4e79cbb85c01`, prepare run `44950505267` and immutable artifact `14725706386`. Public wheel/sdist bytes, fresh public-index installation/setup and exact-wheel local/real SSH startup, recovery and browser rendering are verified within their recorded scope. Published tags and bytes remain immutable: this documentation update does not rebuild or replace them or authorize another upload. The [native qualification report](../claude-trial-report.md#accepted-native-app-scope) retains the bounded four-interface scope that closed #14, including the owner-accepted manual prepare/check/footer limitation; it does not promise automatic interception or qualify every future version/runtime.

The README uses the verified PyPI pin; shared Setup retains the Git/source alternative. Do not recommend an index package based only on its name. Existing project files and the selected project Python survive uninstalling the global CLI. This alpha supports fresh setup and identical repeats; project upgrades, removal, runtime management and the proposed AI resource interview remain separate work.

## Local owner review

Use Python 3.11+ for these maintainer scripts (tested here on macOS/Python 3.13). The application's declared minimum remains Python 3.9 on POSIX; other interpreter/platform and native client combinations are not qualified by this preparation.

```sh
umask 077
python3 -m venv /private/tmp/flightcheck-release-tools
/private/tmp/flightcheck-release-tools/bin/python -m pip install -r requirements.release.txt
/private/tmp/flightcheck-release-tools/bin/python -B tools/release.py prepare --review --output /private/tmp/flightcheck-review-artifacts
/private/tmp/flightcheck-release-tools/bin/python -B tools/release.py verify --artifacts /private/tmp/flightcheck-review-artifacts
```

Choose fresh paths you own outside the checkout; the `/private/tmp/` paths above are writable macOS examples, not existing release identities. Keep the tools environment separate from the new output directory. Review mode labels the artifacts ineligible for publication, including when used on a clean checkout. Uncommitted source is embedded as an explicitly labeled immutable development snapshot. `verify --require-release` and the publication gate reject it. Logs retain the native build and strict Twine checks. The record binds both artifacts, their sizes/hashes, exact Git source/commit/tree, CLI resources and FSL notices. No command in `release.py` uploads packages or reads publishing credentials.

## Legacy documentation proposal

The `docs` command is the retained one-shot Git-to-PyPI proposal helper. It accepts only a legitimate unpromoted Git quickstart and returns a proposal with its exact expected old README digest. It never writes repository files. The current already-promoted README correctly refuses this operation; an error is not permission to replace that README or weaken the guard. Use reviewed documentation changes for future installation wording, preserving the approved visitor structure. Loopback metadata never establishes public availability.

For a suitable historical source copy only:

```sh
python3 -B tools/release.py docs --artifacts /private/tmp/flightcheck-review-artifacts > /private/tmp/README-pypi-proposal.json
```

## Owner setup before any public upload

For future releases, follow this manual process under their own approval. The recorded a2 identity above is not permission to rebuild or republish its immutable bytes:

1. Confirm control and availability of `flightcheck` through the owner's PyPI account, with 2FA and minimal maintainers. A 404 does not reserve the name. Record the agreed release version and publication/license date; retain FSL-1.1-MIT notices and historical terms.
2. Configure a normal or pending Trusted Publisher for this repository, workflow `release.yml`, environment `pypi`. Configure that GitHub environment **before** publication with required human reviewers. Keep release-tag creation restricted to authorized maintainers. A pending publisher is not a successful public release.
3. Before enabling publication, qualify **both local and SSH status cards using the exact retained release wheel** on the browser machine (including the real SSH profile). Confirm that startup/recovery verifies the current task and candidate before emitting a usable link, and record successful browser rendering of both cards. Retain the wheel digest, source SHA, commands, URLs and owner observations with the release review. Automated loopback/SSH fixtures supplement this acceptance; they do not replace it. Earlier development-wheel acceptance does not qualify newly built release bytes. Keep publication disabled until both pass; see [status-card startup](../status-card.md). The closed #14 qualification remains limited to its recorded clients, runtimes and manual guard. These checks qualify the new release wheel separately; they do not reopen that native campaign.
4. Integrate and review the release-source, installation-guide and asset-channel preparation before creating the approved version tag on clean reviewed source. Configure repository variable `FLIGHTCHECK_PYPI_PUBLISH_ENABLED=true` only under a separate explicit publication grant. Keep it disabled during preparation. No long-lived PyPI token or `.pypirc` is needed.

The landed workflow has only `workflow_dispatch`; neither a push, tag nor GitHub release event uploads anything. Prepare is the default mode and has no OIDC write permission. Only the protected publish job has `id-token: write`, and that job performs no repository checkout or project-script execution. All actions are pinned to immutable commits.

## Build once, review, then publish the same bytes

The generic commands below require a newly approved version/tag and reviewed source. Replace `APPROVED_VERSION_TAG` and the approval identity placeholders with that release's actual values. They do not authorize creating a tag or running Actions now. Never rebuild or republish a2, and never move the published tag:

```sh
gh workflow run release.yml --ref APPROVED_VERSION_TAG -f mode=prepare -f tag=APPROVED_VERSION_TAG
```

Dispatch on the version tag so the run's source SHA equals the checked-out release source. The preparation job runs contributor checks, requires clean Git and the exact tag at HEAD, builds wheel/sdist, validates strict metadata/resources/notices, and uploads one immutable `flightcheck-release` artifact. Review/download it and retain the run ID, artifact ID, full source SHA and `release.json` SHA-256. Keep the original distributions; rebuilding would produce different bytes and is not a substitute for approval. Record this one release identity across all channels: distribution/version/tag, full source SHA, prepare run ID, immutable artifact ID, `release.json` hash, and both distribution filenames, sizes and SHA-256 digests. Later visitor-documentation commits do not rebuild or replace the published version.

A later, explicitly authorized dispatch uses those exact four reviewed identities:

```sh
gh workflow run release.yml --ref APPROVED_VERSION_TAG -f mode=publish -f tag=APPROVED_VERSION_TAG \
  -f reviewed_run_id=APPROVED_RUN_ID -f reviewed_artifact_id=APPROVED_ARTIFACT_ID \
  -f reviewed_source_sha=APPROVED_FULL_SOURCE_SHA -f reviewed_manifest_sha256=APPROVED_MANIFEST_SHA256
```

The verification job reads fresh GitHub run, workflow, artifact and environment records. It refuses a wrong run even when artifact hashes match; checks the approved source, repository, workflow, successful dispatch, artifact ID and required-reviewer environment; and verifies the entire downloaded payload. The publishing job downloads the same immutable ID, waits for protected-environment approval, rechecks manifest/distribution hashes, and invokes the pinned PyPA publisher with attestations. It never rebuilds. Missing API access or policy stays a blocker; do not substitute a fabricated context or remove the guard.

These workflow/publisher/environment interactions cannot be qualified locally without the later account setup, landed workflow, tag, actual Actions runs and explicit upload grant. Local tests exercise the policy evaluator, configuration and artifact behavior, not a real OIDC exchange or an enforced GitHub approval.

## Verify actual PyPI before changing the visitor quickstart

After successful authorized publication, use the retained clean release directory. Follow the separately reviewed [Setup](../../setup/README.md) instructions for the exact approved public version in a fresh isolated application/tool environment before running the project checks below:

```sh
python3 -B tools/release.py verify-index --artifacts /private/tmp/APPROVED_RELEASE_DIRECTORY \
  --manifest-sha256 APPROVED_MANIFEST_SHA256 > /private/tmp/pypi-verification.json
cd /path/to/disposable-existing-project
flightcheck inspect .
flightcheck init . --agent claude
flightcheck doctor .
```

`verify-index` performs only GET requests to the exact public project/version and approved file URLs. It binds the retained manifest to the approved digest before parsing or network requests, checks filenames, hashes, lengths, yanked status and actual downloaded bytes, and rechecks the same retained identity before success. Registry redirects and nondefault public artifact origins are rejected before a destination request. Its output explicitly leaves a **fresh public-index installation** pending; metadata agreement alone does not prove installation. `--test-index http://127.0.0.1:PORT` is only for fixtures and produces `simulated_registry_match`, never public qualification.

In the reviewed isolated installation routes, verify both adapters as applicable, complete inventory, preservation of instructions/settings/dependencies, identical repeat, conflict/failure recovery, and installed runtime after global CLI removal. Retain the observed PyPI file digests and attestations. Then independently review the documentation update and record that its published install commands work on that exact public version. Apply a legacy proposal only when its guarded historical input actually applies; preserve its expected old digest. Keep a source-install alternative in shared Setup. Another package or unpublished candidate with the same proposed name does not satisfy this step.

For existing early Git installs whose tool distribution was `flightcheck-cli`, retain the old artifact for rollback, uninstall that old tool, then install the new `flightcheck` distribution; both supply the same executable and can conflict on PATH. Do not force-overwrite an unrelated command. Existing project installations are not implicitly upgraded; use `doctor` to inspect them and keep unsupported migration explicit. No project dependency reinstall is required by the distribution-name change.

Start a fresh chosen coding surface after installation. Shared [Setup](../../setup/README.md) covers Codex CLI, Codex Desktop, Claude Desktop's Code tab and Claude Code, reviewer boundaries, TUI/browser routing, and the retained native trial. File placement and HTTP success do not establish native discovery, reviewer enforcement or browser rendering.

## Failed or withdrawn releases

A failed preparation cannot authorize upload; retain logs and choose a fresh output directory for retry. If upload response is ambiguous, inspect actual PyPI state/digests before retrying. Do not use skip-existing to hide conflicting bytes. PyPI versions/artifacts are immutable: do not rebuild and silently replace an approved release. Yanking requires a separate owner decision and does not undo installed project files. Preserve old distributions and evidence. Unsupported project upgrades/removal are not a reason to overwrite adopter work.

## References

- [Matching GitHub release assets and public readback](../../release/github-assets.md)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [Creating a project through a pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [GitHub Actions packaging guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [Immutable artifact downloads](https://github.com/actions/download-artifact)
- [PyPA publisher and attestations](https://github.com/pypa/gh-action-pypi-publish)
