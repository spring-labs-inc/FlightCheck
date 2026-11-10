# Paired benchmark pilot plan

Proposed first pair for [FlightCheck #13](https://github.com/spring-labs-inc/FlightCheck/issues/13). The pilot starts after owner approval and launch preflight.

The approved run is documented in the [paired pilot result](benchmark-pilot-result.md).

## Rust first

Use the ripgrep 15.0.0 [source pin](benchmark-pins.json) and the line-buffered output task. With line buffering requested, a matching line from a continuing stdin stream should be available before stdin closes. Keep ordinary search behavior and buffering options working. The task can be evaluated locally with process I/O and needs no application service or owner-facing UI.

Give both arms the same symptom-only brief, a bounded code-and-test scope, and the same known check commands. Keep the exact private evaluator and reference implementation with the controller. Freeze the native test identities and input conditions, including the timing bound and scheduling assumptions for the pipe evaluator. Review any required existing assertion edit independently.

## Launch contract

| Item | Proposed setting |
| --- | --- |
| Attempts | One Codex session using FlightCheck and one ordinary Codex session. Use fresh independent contexts and record the exact effective model and effort for both. |
| Host and dependencies | Same arm64 host, verified Rust/Cargo toolchain, identical locked vendored dependencies, separate Cargo home, build output and scratch per arm. Use equivalent starting build-cache state and keep provisioning outside measured time. |
| Native checks | `cargo fmt --all --check`, `cargo test --frozen -p grep-searcher`, and `cargo test --frozen --features pcre2 --test integration`. Expect the 398 baseline test identities plus any new acceptance tests. Verify equivalent permission for the system decompressor in both arms. |
| External evaluation | Same controller-only pipe evaluator and common independent reviewer brief for both arms. Review the endpoint candidate and current native evidence. |
| Timing | Run sequentially on the same host to limit contention. Assign the first order before launch and reverse it for a repeat. Count all workflow stages, with waits and setup reported separately. |
| Authority | Local implementation, native checks, and independent review in the assigned checkout. Confirm the model, effort, tool boundary and resource allowance before launch. |
| Endpoint | A named candidate with the same required tests and external evaluation passing, with current independent acceptance. |

Before starting the clock, verify instruction and skill discovery in the selected arm and ordinary behavior in the control. Check access to the read-only reviewers, confirm the owner-approved limits, and freeze the [run records](benchmark-records.md), including the common brief, arm briefs, reviewer brief, evaluator, and manifest. Use durable approved private evidence storage for the paired run. Keep the arms' inputs and results isolated. Record the first pair as a case study and counterbalance order if repeated.
