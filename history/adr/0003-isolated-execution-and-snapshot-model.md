# ADR-0003: Isolated Execution and Snapshot Model

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted (amended by ADR-0009: the Docker executor is also the personal-mode
  executor; the demo and the video still use Token Factory Sandboxes)
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** Repository code is untrusted and must never run on the host, the user's working
  tree, or the demo server (FR-002). The shipped product and the demo must use Nebius Token
  Factory Sandboxes, which are in beta and not yet accessible to us (billing-country issue). The
  agent needs cheap read-only runs, persistent states to branch from (parallel mode), and an exact
  patch against the installed baseline. Sandbox API calls can fail transiently. Implemented in
  Phase 2 and 3 (`src/fixproof/sandbox/`).

## Decision

- **One `Executor` protocol**: `prepare_repo`, `run(snapshot, command, timeout_s, mutate)`,
  `read_file`, `list_dir`, `write_files`, `tag`, `cancel_all`, `close`. Three implementations:
  - `ContreeExecutor` (Token Factory Sandboxes via contree-sdk 0.3.6): the default, and the only
    one allowed for the demo and the video;
  - `DockerExecutor`: **dev only**, opt-in with `FIXPROOF_EXECUTOR=docker`, prints a DEV ONLY
    banner, uses `--network none` for every run except harness mutations, never mounts host
    folders;
  - `FakeExecutor`: an in-memory filesystem that lives only under `tests/`.
- **Snapshots are sandbox image versions**: reads, tests, and inspection commands run disposably
  and leave the snapshot unchanged; dependency install, the git baseline, and file writes create
  new versions. Key snapshots are tagged `fixproof/<run_id>/<label>` (source, installed, repro,
  final); a failed tag is a warning, not a failure.
- **Repository in, patch out**: the server downloads the GitHub tarball (never extracted on the
  host; install recipes read files from it in memory) and uploads it with its extraction command,
  so the sandbox needs no access to GitHub. After installation, a git commit tagged
  `fixproof-baseline` makes every patch an exact `git diff` (new files included).
- **Resilience**: transient Sandboxes errors (429, API timeouts, transport errors, 5xx) are
  retried 3 times with 1, 2, and 4 s backoff, then fail with a clear `ExecutorError`; command
  timeouts are results (`timed_out`), not errors; `cancel_all()` cancels in-flight operations
  (the SDK then cancels them on the server).
- **No credentials in sandboxes**: no environment variables are passed, and the Contree executor
  refuses any command or file that contains a configured secret value (FR-020).
- **Demo safety**: `assert_demo_safe` refuses the Docker executor or a non-Nebius model endpoint
  unless `FIXPROOF_ALLOW_DEV=1`, which is for local UI testing only.

## Consequences

### Positive

- Untrusted code runs only in disposable or versioned sandboxes; the host never executes it.
- Branching from one snapshot is natural, which ADR-0006 builds on.
- Exact, reviewable patches with change counts for "smallest fix" selection (FR-014).
- Development and the full test suite proceed before Sandboxes access, without weakening the
  rule that the demo and video use Token Factory Sandboxes.

### Negative

- Each sandbox operation has latency; a run issues many of them (reads, tests, git commands).
- Several facts remain VERIFY-ON-ACCESS: PyPI egress, resource limits, maximum timeout, tag
  syntax, and pricing. If egress is missing, tasks need pre-built images.
- Two real executors must stay behaviorally aligned (for example, file modes after writes).
- The installed SDK differs from its docs; upgrades need re-verification (research R4).

## Alternatives Considered

- **`git clone` inside the sandbox**: depends on unknown egress, slower, and less deterministic.
  Rejected.
- **Running repository code on the host with `subprocess`**: violates sandboxed execution
  (FR-002). Rejected.
- **The Contree MCP server**: an extra protocol hop for operations we already wrap. Rejected.
- **Waiting for Sandboxes access before building**: integration would land too late for the
  2026-10-30 deadline. Rejected in favor of the dev-only Docker executor and the fake.

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (FR-002, FR-020)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D3, D4, D10);
  research R4, R5
- Related ADRs: ADR-0002 (tools), ADR-0004 (verification), ADR-0006 (branches), ADR-0008 (demo)
- Evaluator Evidence: `tests/unit/test_contree_executor.py`, `tests/unit/test_docker_executor.py`,
  `tests/unit/test_factory.py`, `tests/live/test_live_smoke.py` (opt-in); PHR 0020
