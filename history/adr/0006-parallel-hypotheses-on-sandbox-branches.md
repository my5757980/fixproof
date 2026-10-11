# ADR-0006: Parallel Hypotheses on Sandbox Branches

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** User Story 3 asks the system to try at least two candidate fixes at once from the
  same saved environment, within the run's overall budget, and to pick the change with the fewest
  changed lines when several verify (FR-013, FR-014). Token Factory Sandboxes documents branching
  from a checkpoint as a core use case. The constitution prefers one agent loop over multi-agent
  frameworks (Constitution III). Status: planned for Phase 5; the budget split it relies on
  (`BudgetTracker.split`) already exists and is tested.

## Decision

- **Hypotheses from the planner**: after reproduction, the planner returns up to N competing
  root-cause hypotheses as structured JSON (default 3; never more than 3 in the demo), published
  as a `hypotheses` event.
- **Same worker loop per branch**: each hypothesis runs the existing worker loop and tools
  (ADR-0002) in its own branch from the `repro` snapshot, concurrently with an `asyncio`
  semaphore bounded by `max_parallel`. Each branch is an attempt with its own `attempt_id` in the
  trace.
- **Budget**: the remaining steps and cost are split evenly across branches; branches share the
  run's clock and report usage back to the parent, so the run as a whole never exceeds its budget.
- **Selection**: every finished branch goes through the same harness verification (ADR-0004).
  When the first branch verifies, the others are cancelled unless `--exhaustive` is given. Among
  verified results, the smallest change wins; the report includes a comparison table with each
  hypothesis, its status, label, changed lines, and why it won or lost.

## Consequences

### Positive

- More chances to find a correct fix within one run, using a native Sandboxes capability.
- No new agent architecture: one loop, many branches; verification and reporting are reused.
- The comparison table makes the reasoning visible to users and judges.

### Negative

- Higher cost per run (about $0.50 with 3 branches versus about $0.25 single-path, research R2).
- Each branch gets fewer steps; a promising hypothesis can run out of budget.
- More concurrent sandbox operations (the beta limit is 50 at once) and an interleaved trace.
- Cancelling losing branches must be prompt and must not disturb the winner's evidence.

## Alternatives Considered

- **Sequential hypotheses**: simpler and cheaper per minute, but slower and without the branching
  story. Rejected as the default.
- **Tree search such as MCTS over edits**: more powerful but over-engineered for the deadline.
  Rejected.
- **A multi-agent framework** (separate planner, coder, and reviewer agents with messaging): more
  moving parts and against Constitution III. Rejected.

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (User Story 3, FR-013,
  FR-014, SC-007)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D6); research R9
- Related ADRs: ADR-0003 (snapshots and branching), ADR-0004 (verification), ADR-0005 (budgets)
- Evaluator Evidence: `tests/unit/test_budget.py` (split); Phase 5 tests in tasks.md (T066–T070)
