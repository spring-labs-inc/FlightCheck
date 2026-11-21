# Matching GitHub release assets

Preparation for [#71](https://github.com/spring-labs-inc/FlightCheck/issues/71).
Public publication remains held for a separate explicit owner grant. A private
bundle or fixture pass does not establish a public release, PyPI ownership,
fresh installation or native client qualification.

Use the **same retained wheel and sdist** downloaded from #67's reviewed,
successful Actions prepare run and immutable artifact ID. Follow
[the release guide](README.md) first. Record the run ID, immutable artifact ID,
tag, full source SHA, `release.json` SHA-256 and distribution hashes together
in the release approval. Integrate preparation before freezing that release
source. A later documentation commit does not authorize rebuilding its version.

## Prepare a private bundle

Maintainer tooling requires Python 3.11+ and the release requirements. The
application's separate minimum is Python 3.9 on POSIX.

```sh
python3 -B release/github_assets.py prepare \
  --artifacts /private/reviewed-release --output /private/new-github-assets \
  --manifest-sha256 APPROVED_MANIFEST_SHA256
```

The helper validates the existing `release.json`, wheel, sdist, source and
notices through #67's verifier. It rejects review/development artifacts. It
copies the original distribution bytes into a new private directory alongside
the original `release.json`, `SHA256SUMS` and proposed `release-notes.md`. It
never builds, uploads, reads credentials, replaces an existing directory, or
changes the retained release artifacts. This step does not validate the actual
Actions/OIDC policy; retain the release guide's protected publication gate.
Take `APPROVED_MANIFEST_SHA256` from the independently retained exact-artifact
approval, not a freshly computed hash of whichever directory is supplied.
Both commands require that binding and reject a different internally valid
release. Readback also checks that GitHub and PyPI used that same manifest.

Review the proposed notes against actual supported platforms, client/runtime
limits and the [bounded native observations](../docs/claude-trial-report.md#accepted-native-app-scope).
Add the approved Actions run/artifact and available PyPI attestation references
from their actual provider records. Do not invent attestations or extend the
manual guard scope to automatic interception. Qualify both local and supported
SSH cards on the browser machine with this exact retained release wheel before
enabling any publication.

## Publish only after explicit authorization

The overseer owns provider writes. Before asking for the held grant, present
the exact reviewed identities, byte hashes, successful prepare run, protected
environment policy, local/SSH card observations and proposed notes. Confirm
the agreed PyPI release and fresh uv/pipx install/setup checks under #67/#70.
Keep #72 blocked until its actual public PyPI prerequisite clears.

Read the **current** remote tag/release/assets before creating anything. The
tag must already resolve to the reviewed full source commit. Refuse a tag or
release mismatch. A missing release permits creation only under the explicit
publication grant. Attach exactly the wheel, sdist, original `release.json` and
`SHA256SUMS`, using the reviewed notes; do not upload `release-notes.md` as an
extra asset. Mark alpha versions as prereleases. Never use overwrite/clobber,
delete-and-recreate, `skip-existing` or another build to hide a conflict.

If a release or any asset already exists, download and compare it before any
retry. An identical complete release needs readback, not replacement. An
incomplete/ambiguous upload needs remote readback of every existing asset and
an explicit reconciliation of the missing operations before an authorized
resume. Stop on conflicting bytes, source/tag/version, checksums or unexpected
assets; retain the provider response. The helper intentionally has no upload
command, token option or publication-enable switch.

## Verify public readback

After authorized publication, retain the original release directory:

```sh
python3 -B release/github_assets.py verify-public \
  --artifacts /private/reviewed-release --manifest-sha256 APPROVED_MANIFEST_SHA256 \
  > /private/github-pypi-readback.json
```

This performs public GETs of the GitHub release, exact tag (including annotated
tag resolution) and each of its four assets. It checks publication/prerelease
state, source SHA, inventory, names, sizes, advertised digests when present and
the actual downloaded bytes. Only HTTPS GitHub asset redirects to the GitHub
release-asset host are accepted. It then invokes #67's actual public PyPI
metadata **and artifact-body** verifier for those same wheel/sdist bytes.
There is no simulated-index option or saved-receipt shortcut in this command.
A fixture pass cannot satisfy public acceptance.

Retain the resulting release/asset IDs, source/version/digests and original
output. Download wheel and sdist into fresh isolated tool environments, check
`SHA256SUMS` (for example `shasum -a 256 -c SHA256SUMS` on macOS), then verify
each pinned installation, explicit project preview/application and `doctor`.
Use the [shared setup guide](../setup/README.md) for project choices and both
client adapters. Record tool, Python and platform versions and all required
build dependencies for the sdist; do not claim a fully offline installation
without testing its complete dependency inputs.

Global CLI upgrade/reinstall/uninstall must preserve already configured
projects and their pinned workflow/runtime. Project migration/removal remains
unsupported. Preserve FSL-1.1-MIT notices and historical terms; native Windows,
cloud sessions and untested platform/client combinations remain unqualified.

The helper follows GitHub's official
[release-by-tag API](https://docs.github.com/en/rest/releases/releases#get-a-release-by-tag-name),
[Git reference API](https://docs.github.com/en/rest/git/refs#get-a-reference) and
[asset download API](https://docs.github.com/en/rest/releases/assets#get-a-release-asset).
