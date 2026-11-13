# Install FlightCheck in an existing project

Use the complete installation flow below. It includes the shared workflow, all six evidence tools, the browser status card and the selected client adapter. A documentation-only installation is incomplete. Preserve existing project policy; record a concrete blocker or an explicit owner-approved exclusion rather than silently dropping a component.

The installer uses only Python's standard library and Git. Receipt and card tools require **Python 3.9+ on POSIX**. They can support projects using other languages. No PyPI release, plugin, account, global configuration change or new CI service is needed.

## 1. Obtain and pin the source

Run these commands outside the adopting repository, choosing an unused destination:

```sh
git clone https://github.com/spring-labs-inc/FlightCheck.git /path/to/FlightCheck
git -C /path/to/FlightCheck rev-parse HEAD
git -C /path/to/FlightCheck checkout --detach FULL_COMMIT_FROM_PREVIOUS_COMMAND
git -C /path/to/FlightCheck status --porcelain=v1 --untracked-files=all
```

Expected: a full immutable commit ID, a detached checkout and no status output. Record that ID with the setup. The source must stay clean. The installer records the commit, Git tree, manifest digest and each component's source/installed digest. New releases are adopted deliberately; the setup prompt does not permanently pin an old version.

Read the license accompanying that revision. Current FlightCheck uses FSL-1.1-MIT, permitting ordinary internal organizational commercial use without paid seats. Each version gains additional MIT rights after two years. Keep the version's license and notices with copied material; retain the adopting project's own license. Historical versions keep their historical terms.

## 2. Inspect before changing the project

From the adopting project's Git root:

```sh
python3 -B /path/to/FlightCheck/setup/install.py inspect --target .
```

Expected: JSON listing detected instruction/configuration files, a preferred Python interpreter, a default branch when `origin/HEAD` is known, safe activation/delivery defaults, and required configuration fields. This command writes nothing and does not run project checks.

Read the existing instructions and development commands. Detection is a starting point, not permission to replace policy. In particular, an existing `CLAUDE.md` may hold different policy from `AGENTS.md`; the installer appends a bounded FlightCheck section instead of replacing either file or redirecting it to the other.

Choose `codex`, `claude`, or `both` explicitly. Only that client's project-local skill and reviewer definitions are installed. Claude definitions are generated from the canonical reviewer instructions with `tools: Read, Grep, Glob`; actual effective boundaries still need the fresh-session probe below.

## 3. Resolve the project choices together

Reuse decisions already present in project policy. Ask the owner about only the unresolved items, in one batch:

- **Activation:** opt-in is the default. Use `default-for-coding` only with a recorded explicit owner decision. Ordinary questions remain outside the workflow.
- **Delivery:** default to no provider writes without approval. Record the exact grant if commits, pushes, PR creation, nit issues or merge are authorized. A passing verdict does not expand that grant.
- **Evidence:** an absolute, owner-only directory outside the checkout, and any narrowly scoped client read access needed by reviewers. No global read permission is installed automatically.
- **Checks and interpreter:** the project's actual non-mutating commands, selected Python and cheap/authoritative phases. Run formatters/autofix separately before freezing a candidate; the installer does not run those commands.
- **Default branch and nit tracker:** use the detected branch when available; otherwise resolve it explicitly. Record the actual tracker and any permissions needed to write there.

Save the resulting configuration outside the source checkout, for example `/private/project-flightcheck.json`:

```json
{
  "activation": "opt-in",
  "delivery": "No provider writes without owner approval",
  "evidence_dir": "/absolute/private/project-evidence",
  "python": "/absolute/project/.venv/bin/python",
  "default_branch": "trunk",
  "nit_tracker": "Project GitHub issues; owner approval required to create",
  "policy_reference": "Existing project development guide and owner setup decision",
  "checks": [
    {
      "name": "Project tests",
      "command": ["/absolute/project/.venv/bin/python", "-B", "-m", "pytest", "-q"],
      "phase": "authoritative"
    }
  ]
}
```

These are example paths, a branch name and a test command: replace them with the detected project values. The selected interpreter needs the project's dependencies for its own checks. The installer itself does not install dependencies. For default-for-coding, also supply `"activation_reference": "Actual owner decision reference"`; relying on the model to select a skill automatically is insufficient.

## 4. Preview and apply the complete installation

```sh
python3 -B /path/to/FlightCheck/setup/install.py plan --target . --agent claude --config /private/project-flightcheck.json
python3 -B /path/to/FlightCheck/setup/install.py apply --target . --agent claude --config /private/project-flightcheck.json
```

Expected from `plan`: `status: planned`, source identity and a complete list of create/update/unchanged operations, with no writes. Inspect the plan before applying. Unresolved configuration, modified managed files, collisions with existing files and symlink destinations produce `status: incomplete` with a nonzero exit.

Expected from successful `apply`: `status: ready_for_client_probe`, component count, source identity and passed local Python-tool/card-HTTP checks. It installs every selected component, appends marked instruction sections, creates a private evidence directory when needed, and runs a bounded synthetic card check. The test listener is stopped afterward. Runtime failure remains incomplete and is never a completed client qualification; correct the reported environment problem and rerun verification.

Interpreter detection has a 10-second timeout. The combined tool/card smoke check has a 15-second overall deadline, followed by at most seven seconds for process cleanup. A listener that stalls or trickles data cannot extend the verification indefinitely.

The complete source-to-destination inventory is [`manifest.json`](manifest.json). Shared assets live under `.flightcheck/`, with client discovery files at `.agents/skills/` and `.codex/agents/` for Codex, or `.claude/skills/` and `.claude/agents/` for Claude. The manifest is also copied to `.flightcheck/manifest.json`. No hooks, global settings, credentials or provider writes are installed/enabled by this flow.

Existing instructions outside the `FlightCheck:begin`/`FlightCheck:end` markers remain intact. Existing client settings are untouched. Repeating the same plan/apply is idempotent. A pristine previously managed file can be updated by an explicit plan/apply from a new clean pinned source; modifications to managed content cause a conflict instead of being overwritten. Changing client selection requires explicit reconciliation. Review changes with `git diff` and inspect new files too; the installer does not stage or commit them.

## 5. Verify from the installed project

```sh
python3 -B .flightcheck/install.py verify --target .
```

Expected: `status: ready_for_client_probe`. Verification checks the entire required inventory and recorded hashes, validates project configuration/interpreter, invokes the real installed tools, publishes a synthetic nine-stage snapshot in private scratch, and tests its real loopback HTTP route and printed task link. Missing or modified required components return incomplete and a nonzero exit. This works without keeping the original source checkout on disk.

`project.json` records choices; it does not create per-flight task contracts, fingerprints, baseline reports or reviewer verdicts. Configure those using the installed `.flightcheck/docs/development-workflow.md`. Reusable language-specific evidence adapters are separate work in #57.

## 6. Verify the client in a fresh session

Installation and HTTP tests do not prove that a client loaded its instructions, restricted reviewer tools or rendered the card. Start a fresh Claude/Codex session in the target checkout, especially after creating the first agent definitions. Use the installed client's discovery tools to inspect effective instructions, skill and role availability.

1. Ask an ordinary question; it must stay outside a flight. Select a small task through `$develop-change` (Codex) or `/develop-change` (Claude), or verify the explicitly approved default-for-coding route.
2. Probe each reviewer with synthetic canaries: required packet/evidence reads must work and writes, secrets, native check execution and provider tools must be unavailable. Inspect active hook sources too. Preserve existing settings; request only the narrow missing evidence access the project requires. Keep review pending if the boundary cannot be enforced.
3. Follow `.flightcheck/docs/status.md` to prepare a real task card before each controller reply and check the exact draft with `.flightcheck/status-card/reply.py check --task TASK_ID --phase update --reply-file /private/reply.txt`. Test all phases, including approval pauses, blockers and repair/resume. Ordinary chat and raw reviewer JSON must remain unchanged. Do not claim a Stop hook intercepts intermediate or interrupted replies without an observed native capability test. A TUI can keep using the terminal while the user opens the printed card URL in a browser. For SSH/remote checkouts, use approved localhost forwarding; do not expose the listener to the network.
4. Record host HTTP publication and browser reachability/rendering separately. Keep one task URL on resume. Test a stopped listener and a changed candidate; an old verdict must become Pending.
5. Rehearse the documented handoff path before provider writes. Label any mock reviewer output as a plumbing test; it does not establish real approval.

Record tested client/runtime versions, observed capabilities and outstanding blockers with the setup. Full native Claude end-to-end qualification is tracked in #14; installing the adapter alone does not complete it. The portable per-reply guard and TUI browser guidance are included; native event interception still needs a live capability probe. Card-completeness policy remains #55.

## Troubleshooting

- **Dirty source:** obtain a clean pinned source checkout. Do not discard unrelated work to make it clean.
- **Conflict:** inspect the reported file and existing installation record. Preserve owner edits and reconcile deliberately; there is no force-overwrite flag.
- **Runtime or loopback failure:** use the selected project interpreter and a host that allows `127.0.0.1` binds. Run sibling-import scripts by path with `-B`, not `-I`. Verify again after correcting the environment.
- **Missing default branch:** inspect the remote's actual default branch or ask the owner. Do not assume `main`.
- **Client probe fails:** keep setup qualification pending and record the actual boundary/discovery error. Fresh-session requirements and supported capabilities can vary by client version.
