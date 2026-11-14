# Unpublished PyPI distribution experiment

Read the [design and release recommendation](../../docs/pypi-distribution.md).
This is a sandbox-only feasibility prototype for #58, separate from #53's production
installer work. `init` copies immutable resources into `.flightcheck`. The explicit `configure`
command now delegates to the unchanged canonical installer from merged #53. It
preserves existing project policy and installs the shared workflow and chosen client
adapters. `doctor` still verifies the resource bundle; use the installed verifier
and a real fresh-session flight to qualify the configured workflow.

Use a POSIX host with Python 3.9+, Git and permission to bind IPv4 loopback for the
packaged-card test. All outputs and disposable environments stay outside the checkout.
The builder uses the canonical files listed in [assets.json](assets.json), including
dot-directories, and records development builds honestly. No index project is published
or reserved. Do not substitute an index install for the local wheel command below.

From the repository root, with your chosen Python on PATH:

```sh
python3 -m venv /private/tmp/flightcheck-package-build
. /private/tmp/flightcheck-package-build/bin/activate
python3 -m pip install -r experiments/pypi-installer/requirements-dev.txt pytest
python3 -B -m unittest discover -s experiments/pypi-installer/tests -v
python3 -B -m unittest discover -s tests
python3 -B experiments/pypi-installer/build_wheel.py --output /private/tmp/flightcheck-wheels
python3 -m venv /private/tmp/flightcheck-package-cli
/private/tmp/flightcheck-package-cli/bin/python -m pip install --no-index --no-deps \
  /private/tmp/flightcheck-wheels/flightcheck_distribution_prototype-0.0.0.dev58-py3-none-any.whl
```

Mark a **new disposable** target, then preview and explicitly apply:

```sh
mkdir /private/tmp/flightcheck-package-target
printf 'Disposable FlightCheck distribution sandbox\n' \
  > /private/tmp/flightcheck-package-target/.flightcheck-prototype-sandbox
/private/tmp/flightcheck-package-cli/bin/flightcheck-prototype init \
  --sandbox /private/tmp/flightcheck-package-target
/private/tmp/flightcheck-package-cli/bin/flightcheck-prototype init \
  --sandbox /private/tmp/flightcheck-package-target --apply
/private/tmp/flightcheck-package-cli/bin/flightcheck-prototype doctor \
  --sandbox /private/tmp/flightcheck-package-target
/private/tmp/flightcheck-package-cli/bin/flightcheck-prototype status \
  --sandbox /private/tmp/flightcheck-package-target
```

Preview returns JSON `action: dry-run`, exact planned new paths and hashes via the
bundle manifest; no target writes occur. Apply returns `action: apply`; repeating
it returns `unchanged`. Doctor/status identify the project pin and explicitly report
`client_configuration: not implemented` and `live_client_support: unverified`.
Errors return nonzero with a JSON diagnostic. All commands require the exact sandbox
marker and reject links in the target. Do not use this prototype on a real project.

The tests build `0.0.0.dev58` and `0.0.0.dev59`, install the replacement wheel into an
isolated environment and exercise `upgrade --from OLD_BUNDLE` as preview and with
`--apply`. A stale OLD_BUNDLE, changed assets or an entry under `.flightcheck/active/`
blocks the operation. The old version directory remains available after an accepted
upgrade. These versions test the distribution lifecycle; they are not release numbers.

The CLI has `init`, `doctor`, `status`, `upgrade` and explicit `configure`.
Complete project-local configuration delegates to #53; native-client qualification
is separate. Production diff/backup, project removal, runtime environments and real
flight coordination remain proposals in the design. The lock schema is descriptive; the CLI uses its bounded
Python validator and does not depend on a JSON Schema library. Metadata/field integrity
does not authenticate a maliciously rewritten project lock; production provenance
verification must anchor in a separately trusted release digest/attestation.

Neither building/installing a wheel nor importing its CLI writes to a project or
global agent settings. Global tool uninstall does not remove copied project files.
Discard these explicitly disposable directories when finished; no production removal
command is implemented here. Evidence and logs from an actual FlightCheck flight
have their own retention rules.

## Complete workflow rehearsal

After `init --apply`, create a reviewed project configuration using
[the installer guide](../../setup/README.md), then run:

```sh
flightcheck-prototype configure --sandbox DISPOSABLE_GIT_PROJECT --agent codex --config PRIVATE_CHOICES_JSON
flightcheck-prototype configure --sandbox DISPOSABLE_GIT_PROJECT --agent codex --config PRIVATE_CHOICES_JSON --apply
python3 -B DISPOSABLE_GIT_PROJECT/.flightcheck/install.py verify --target DISPOSABLE_GIT_PROJECT
```

The wheel includes a SHA-256-bound archive of the exact original tracked Git tree
and original commit object. The adapter materializes a clean shallow source snapshot
with that same commit/tree, without history, downloads or global Git configuration,
then runs the canonical installer unchanged. It does not invent a replacement source
commit. All original archive paths, file types, digests and resulting Git identities
are checked before installation. This requires Git as well as Python.

The additional configuration check covers full selected installation, original
provenance, repeated setup, preserved policy/modes, modified-managed-file refusal,
and installed verification with the original checkout unreadable. A fresh native
flight and actual browser observation are separate acceptance requirements. The
earlier packaging approval does not establish complete adoption or browser rendering;
those require the actual client and owner-observation evidence described in the design. An isolated PyPI-compatible index can test
package download without a public release; it is not an actual PyPI upload/download.

The expanded candidate also includes merged #54's portable `reply.py` guard. A
selected controller must prepare and verify the card, check each exact private reply
draft, and keep its returned footer last. Remote route readiness and actual browser
rendering are separate observations. The fresh-session rehearsal retains the actual native prepare/check execution, exact
reply drafts and owner-supplied browser route. Installing the guard alone does not
prove the client used it or intercepted messages. Keep native tests, frozen-baseline
controls, actual independent reviews, verdict validation and repair/resume evidence
in the private review packet. Run an ordinary question separately to verify that it
does not activate a selected flight. Public PyPI delivery and native Claude use are
not established by this isolated-index Codex rehearsal.
