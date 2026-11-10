# SpringDev handoff benchmark

Compare how ordinary Codex and SpringDev resume Spring's Contact validation flow from clean and stale saved states. Use the shared [handoff commands](../examples/existing-project/scripts/handoff.py) for the SpringDev arms. The controller supplies the task, gate definitions, preview fixtures, and benchmark waiver.

## Prepare the pinned checkout

Use the Spring commit `92f38c043943e94bbf427c8ff45fc37de87ea39c`. Record the Codex CLI, model and effort, host, Python and PostgreSQL versions, and pinned Spring and Playwright dependencies. Use an existing authorized local Spring checkout containing that commit. Provision an equivalent offline Spring test environment in each worktree using Spring's local test setup. Use equivalent prepared environments, preserve package records and launchers, and point Spring package imports to the assigned worktree. Verify the import locations and compare the fingerprint probe output across equivalent candidates before timing. Separate installs can produce different package records and cause a rerun. Use a disposable loopback database fixture and Spring's isolated pytest launcher. Record differences in tooling or runtime.

From the SpringDev checkout, set `spring_source` to the absolute path of the existing Spring checkout.

```sh
umask 077
springdev=$(pwd)
fixtures="$springdev/benchmarks/contact-handoff"
scratch=$(mktemp -d)
spring_pin=92f38c043943e94bbf427c8ff45fc37de87ea39c

git init --bare "$scratch/spring.git"
git --git-dir="$scratch/spring.git" fetch --depth=1 "$spring_source" "$spring_pin"
for arm in seed changed-ordinary changed-springdev clean-ordinary clean-springdev; do
    git --git-dir="$scratch/spring.git" worktree add --detach "$scratch/$arm" "$spring_pin"
    (cd "$scratch/$arm" && python3 -B "$fixtures/seed.py")
done
```

The helper seeds a Contact error summary and focused assertions in the scratch worktree. The initial summary copy is “Please correct the errors below.” Keep those worktree edits local. Give the timed worktrees the same benchmark scope and project configuration. For the SpringDev arms install the example [skill, roles, guide and scripts](../examples/existing-project/README.md). If adapting the Spring workflow already present at this pin, point its selected-workflow instructions at the example guide for these disposable worktrees. Preserve Spring's test isolation and tool boundaries. Expose the same project files to both arms. The ordinary arm uses its ordinary entry point, and the SpringDev arm selects the skill.

## Create the two saved states

- **Changed UI.** Run the required test and browser gates on the original seed and retain the passing receipts. Record a synthetic approval keyed to the original Contact template digest. Copy that saved state to both changed arms. In each changed worktree, change the summary copy to “Please correct the highlighted fields.” and change the summary's condition from `form.errors` to `form.errors and require_email`. The stale preview and receipts still describe the original template. On a disposable preflight copy, confirm the changed fixture fails the verified-user test and browser case.
- **Clean.** Change the copy to “Please correct the highlighted fields.” with the `form.errors` condition intact. Run both required gates on that candidate and retain the passing receipts and its synthetic preview approval. Give both clean arms that exact candidate and a private copy of those records. Verify that the current input fingerprints match the saved receipts before timing.

Use the same brief for all arms. The exact new copy should appear in an accessible alert on invalid submissions for both anonymous and verified-email visitors. GET should show no alert. Invalid submissions must retain drafts and send no mail. The anonymous form includes an email field and the verified form omits it. Workers may edit the Contact template only. Keep the seeded tests and benchmark scripts outside the edit scope. Keep the helpers and controller outside the worker's checkout.

## Run and record the gates

Use these checks from each assigned checkout. Export `SPRING_ISOLATED_TEST_PORT` to the disposable loopback port, `SPRINGDEV_BENCH_DB_RECEIPT` to a private file describing the disposable database runtime and bootstrap, and `SPRINGDEV_CHROMIUM_BINARY` to the installed Playwright headless Chromium executable. Keep the fixture configuration equivalent within a pair. Set `FLIGHTCHECK_LOG_ROOT` to a scratch-only location for that worktree. Use a clean environment without Spring's runtime secrets.

```sh
git diff --check
.venv/bin/ruff check spring-web/authn/tests/test_contact.py
.venv/bin/python -B scripts/check_agent_policy.py
.venv/bin/python -B .venv/bin/flightcheck-check
.venv/bin/python -B -m spring.isolated_pytest spring-web/authn/tests/test_contact.py -q
.venv/bin/python -B "$fixtures/visual.py" .local/tmp/bench-visual "$expected_copy"
```

Use [the recorder](../examples/existing-project/docs/development-workflow.md#reuse-a-result) with the following invocations. Set `bank` to an existing owner-only directory outside the worktree. Set `expected_copy` to the text for the candidate under test. Omit the cheap invocation when creating the saved preview and gate bank, then run it for the timed SpringDev arms. Ordinary Codex can run the four cheap checks directly and retain their results.

```sh
candidate=$(shasum -a 256 spring-web/templates/authn/contact_form.html | cut -d ' ' -f 1)
record_gate() {
    gate=$1
    scope=$2
    shift 2
    probe=$(.venv/bin/python -B -c 'import json,sys; print(json.dumps([".venv/bin/python","-B",*sys.argv[1:]]))' "$fixtures/fingerprint.py" "$gate")
    .venv/bin/python -B "$springdev/examples/existing-project/scripts/capture_check.py" \
        --evidence-dir "$bank" --candidate "$candidate" --gate "$gate" --scope "$scope" \
        --fingerprint-command "$probe" "$@"
}

record_gate native "Focused Contact tests" --summary pytest -- \
    .venv/bin/python -B -m spring.isolated_pytest spring-web/authn/tests/test_contact.py -q
record_gate visual "Eight Chromium Contact cases" \
    --artifact .local/tmp/bench-visual/browser.json \
    --artifact .local/tmp/bench-visual/anonymous-get.html \
    --artifact .local/tmp/bench-visual/anonymous-invalid.html \
    --artifact .local/tmp/bench-visual/verified-get.html \
    --artifact .local/tmp/bench-visual/verified-invalid.html -- \
    .venv/bin/python -B "$fixtures/visual.py" .local/tmp/bench-visual "$expected_copy"
record_gate cheap "Whitespace, scoped Ruff, agent policy, and static workflow contract" --refresh \
    --artifact .local/tmp/bench-cheap/cheap.json \
    --artifact .local/tmp/bench-cheap/cheap-0.log --artifact .local/tmp/bench-cheap/cheap-1.log \
    --artifact .local/tmp/bench-cheap/cheap-2.log --artifact .local/tmp/bench-cheap/cheap-3.log -- \
    .venv/bin/python -B "$fixtures/cheap-gate.py"
```

Copy each saved bank intact into separate private banks for its two arms. Use the `request` field of each `run.json` when constructing the handoff manifest. For the changed arm, replace the last argument of the visual request with the new copy. Preserve each original log and all review results.

## Run the paired sessions

1. Launch fresh independent Codex sessions sequentially from the four starting states. Use the same brief, requested model and effort, test scope, and equivalent isolation. Keep each arm's worker and read-only reviewer from inspecting other arms or private controller records. Record the order and start timing before preparing the resume prompt. The controller may execute the checks for each arm under the same assistance policy.
2. For SpringDev, run [`handoff.py resume`](../examples/existing-project/docs/development-workflow.md#resume-summary-and-final-packet) before launch and include its computed summary in the task prompt. Supply the current and saved template digests, the synthetic preview decision and explicit waiver, and the exact gate requests from the recorder invocation. The stale arm's current visual request uses the new copy. Ordinary Codex receives the same brief and saved records and assesses applicability directly. Ask each worker to report the preview and gate dispositions before repair and return the candidate for verification.
3. Run or reuse the applicable gates and record the decisions. SpringDev's recorder decides reuse and its [`handoff.py review`](../examples/existing-project/docs/development-workflow.md#resume-summary-and-final-packet) command validates the final packet. Supply the current diff under the evidence root, required gate requests, reuse receipt paths where applicable, acceptance criteria, waiver and local-only boundary. Stop on unresolved prerequisites and repair them before final review. Give the ordinary arm an independent read-only final reviewer with the same acceptance standard and its original evidence.
4. End each arm at its recorded technical `APPROVE`, including any repair and re-review time. Keep publication and provider actions outside the exercise. Use synthetic preview approvals and an explicit benchmark waiver for all arms. The exact UI routes still need rendering and verification. Verify the final diff, all required gate receipts, and verdict from retained records. Report elapsed wall time separately from preflight and note any interruption or controller recovery.

The checked-in helpers reproduce the source fixture, browser assertions and fingerprint inputs. A manual or automated session controller can use this procedure. Match timing boundaries and assistance policy across arms.

For the non-UI replay, use a synthetic shipping quote with unit tests below, at, and above $50.00. Capture a pass under a required gate, change the boundary to exclude exactly $50.00, and record the actual failing run under the same gate. Use `preview: null`. Verify that the shared resume and review commands report the newer failure and block final review. After repairing the boundary, run the same check again and obtain a local verdict from the final reviewer. The matching [CLI regression tests](../tests/test_handoff.py) run without a Spring checkout.

```sh
python3 -B -m unittest discover -s tests -p 'test_handoff.py' -v
```
