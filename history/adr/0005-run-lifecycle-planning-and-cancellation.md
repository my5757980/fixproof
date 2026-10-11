# ADR-0005: Run Lifecycle, Two-Stage Planning, and Cancellation

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** SC-006 asks for a visible plan within 30 seconds and a stop within 10 seconds, but
  setup alone (download, sandbox upload, dependency install) can take minutes, and a single
  sandbox command may run for 300 seconds. FR-006 requires every run to be bounded by steps,
  time, and cost; FR-012 requires partial results after a stop. One orchestrator must serve the
  CLI, the web demo, and the benchmark. Implemented in Phase 3
  (`src/fixproof/agent/orchestrator.py`, `src/fixproof/budget.py`, `src/fixproof/cli.py`).

## Decision

- **Explicit state machine** (data-model.md): `queued → setting_up → baseline → planning →
  reproducing → fixing ⇄ verifying → reporting → done`. Every transition publishes
  `phase_changed`; any phase can end early with a stop reason.
- **Two-stage plan**: right after intake, the planner gets the task and the GitHub file tree and
  publishes the **initial** plan while setup continues concurrently. If the planner takes longer
  than 25 s, a labeled default plan is shown instead. After the baseline test run, the planner
  publishes the **refined** plan. Re-diagnosis plans after failed verifications are also
  published, so the user always sees the current plan before edits.
- **Setup**: install with commands detected from the project files; one model-suggested retry,
  accepted only if it is a plain `pip install` command (optionally joined with `&&`). Two
  failures end the run with `setup_failed`.
- **Budgets**: steps, wall time, and cost are checked before every model call; harness work
  (install, verification, reporting) checks only time and cost, so a fix found on the last
  allowed step is still verified. A limit produces a `budget` event with `limit_hit`.
- **Stop**: `stop()` cancels the run's asyncio task, which interrupts any in-flight model request
  or sandbox wait immediately, and `Executor.cancel_all()` cancels remote operations. A tool call
  interrupted this way is closed with `error: "stopped"`. Cancelling the orchestrator from outside
  is treated the same way. The CLI maps the first Ctrl+C to `stop()`.
- **Reporting always runs**: after success, failure, budget limits, or a stop (then with a
  10-second deadline and no new model calls), and `run_finished` is always the last event. If the
  full report cannot be built, a minimal report is still written.

## Consequences

### Positive

- The user sees a plan within seconds, long before the environment is ready.
- Stops are prompt and predictable even during long commands or model calls.
- Every exit path yields `report.md`, `report.json`, the trace, and a patch when there is one.
- The same orchestrator serves the CLI and the demo; its scenarios are covered offline.

### Negative

- Concurrency (the initial plan runs alongside setup) adds complexity and ordering to test.
- A slow planner shows a default plan first; the refined plan arrives later.
- Cancellation relies on every await point being cancellable; blocking code inside a sandbox call
  would delay a stop (none exists today, but it is a constraint for future code).
- Several fixed limits (25 s plan timeout, 3 fix rounds, 15 turns per reproduction attempt) are
  tuning guesses until live runs exist.

## Alternatives Considered

- **One plan after the baseline**: simpler, but misses the 30-second plan goal on any real repo.
  Rejected.
- **Cooperative stop flags checked between steps**: a 300-second command would delay the stop far
  beyond 10 seconds. Rejected.
- **Killing the process on stop**: loses partial results and the report (FR-012). Rejected.
- **A plan-free ReAct loop**: hides intent from the user and the judges (Constitution IV).
  Rejected.

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (FR-005, FR-006, FR-011,
  FR-012, SC-006)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (Run lifecycle, D9);
  [data-model.md](../../specs/001-verified-fix-agent/data-model.md) (state transitions)
- Related ADRs: ADR-0001 (model gateway), ADR-0003 (cancel_all), ADR-0004 (verification loop),
  ADR-0007 (events)
- Evaluator Evidence: `tests/integration/test_orchestrator_single.py` (scenarios a–o),
  `tests/contract/test_trace_contract.py`, `tests/integration/test_cli.py`; PHR 0020
