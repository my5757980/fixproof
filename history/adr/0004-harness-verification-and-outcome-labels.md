# ADR-0004: Harness Verification and Outcome Labels

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** The product promise is "a fix with proof". The constitution forbids reporting
  success without evidence, FR-007 defines "Verified" (reproduction passes 3 consecutive times
  and every baseline-passing test still passes), and FR-008 forbids weakening tests. A model can
  claim success, edit tests, or write a reproduction test that later gets changed. Repositories
  have pre-existing failures and flaky tests. Implementation (Phase 3) refined the original rule
  in three places, recorded here: the scope of flaky exclusion, the "prior tests" condition, and
  protection of the reproduction test. Code: `src/fixproof/agent/verify.py`,
  `src/fixproof/agent/orchestrator.py`, `src/fixproof/agent/report.py`.

## Decision

- **Only the harness sets the label**; `finish` merely hands over, and the report copies the
  harness label, never model text.
- **Reproduction first**:
  - `failing_test` task: the given test must fail at baseline, or the run ends `not_reproducible`;
  - issue or description task: the worker must create a new test file while existing files are
    frozen; the harness runs the new files, and the first test that *fails* (an assertion or the
    reported exception, not an error such as an import failure) becomes the reproduction test.
    The harness gives feedback and allows up to 3 checks before `not_reproducible`.
- **Verification on the final snapshot**: run the reproduction test up to 3 times (stopping at the
  first failure); compute the patch; run the full suite; re-run apparent regressions once.
- **Labels**:
  - **verified**: 3 of 3 reproduction passes, AND no regressions among baseline-passing tests,
    AND no existing test file modified or deleted, AND the baseline had at least one passing test
    besides the reproduction test;
  - **needs review**: the tests pass, but existing test files changed, or there was no prior
    passing test (so there is no regression evidence);
  - **not verified**: anything else, including any stop before verification.
- **Refinements from implementation**:
  - flaky tests (baseline failures that pass on a re-run, and apparent regressions that pass on a
    re-run) are excluded **only from the regression check**; they still count as prior evidence;
  - a reproduction test changed after the reproduction was confirmed counts as a modified test
    file, which closes the "weaken my own test" loophole;
  - "prior tests" means prior *passing* tests, because a suite that fails entirely proves nothing
    about regressions.
- **Iterate on failure**: a failed verification goes to the planner for re-diagnosis and back to
  fixing, for up to 3 rounds within budget; the best result is kept (higher label, then fewer
  changed lines). Tests that failed before any change are listed separately and never count
  against the label. The stop reason is recorded independently of the label.

## Consequences

### Positive

- "Verified" is earned by evidence that the model cannot talk around or tamper with.
- Pre-existing failures and flaky tests do not unfairly block a correct fix.
- Every label is explainable from the evidence table and the trace (SC-005).

### Negative

- Verification costs sandbox time: 3 reproduction runs, a full-suite run, and re-runs.
- Repositories without passing tests can reach only `needs_review`.
- The reproduction test is written by the model; a test that fails for the wrong reason can still
  be accepted (the failed-not-errored rule reduces but does not remove this). The test is in the
  patch for human review.
- One re-run cannot catch every flaky test; a flaky reproduction test fails safe (not verified).

## Alternatives Considered

- **Let the model judge success**: unverifiable and contrary to the constitution. Rejected.
- **Require the entire suite to pass**: penalizes pre-existing failures (spec scenario 1.3).
  Rejected.
- **A single reproduction run**: too weak against flaky fixes; FR-007 requires 3. Rejected.
- **Grade only with hidden reference tests**: those exist for benchmark tasks, not for user tasks;
  used as an extra benchmark metric instead (research R14).
- **Treat flaky tests as missing evidence everywhere**: tried first in implementation; it wrongly
  downgraded correct fixes to `needs_review` when the only prior test flaked once. Replaced by the
  narrower rule above.

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (FR-004, FR-007, FR-008,
  FR-009)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D5); research R7,
  R8; [data-model.md](../../specs/001-verified-fix-agent/data-model.md) (labeling rule)
- Related ADRs: ADR-0002 (finish tool), ADR-0005 (lifecycle), ADR-0006 (winner selection)
- Evaluator Evidence: `tests/unit/test_verify.py`, `tests/unit/test_report.py`,
  `tests/integration/test_orchestrator_single.py`; PHR 0020 (records the flaky-rule finding)
