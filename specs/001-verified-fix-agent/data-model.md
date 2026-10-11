# Phase 1 Data Model: Verified Fix Agent

**Feature**: `001-verified-fix-agent` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

All entities are immutable-by-default Pydantic v2 models in `src/fixproof/models.py`, except
`Run`, which the orchestrator mutates through explicit transition methods. Nothing is stored in a
database. A run persists as files in `runs/<run_id>/`: `trace.jsonl`, `report.json`, `report.md`,
and `patch.diff`.

## Enumerations

| Enum | Values | Notes |
|------|--------|-------|
| `TaskKind` | `issue`, `failing_test`, `description` | Exactly one per run (FR-001) |
| `RunStatus` | `queued`, `setting_up`, `baseline`, `planning`, `reproducing`, `fixing`, `verifying`, `reporting`, `done` | `done` is terminal; see transitions |
| `OutcomeLabel` | `verified`, `needs_review`, `not_verified` | Computed by the harness only (research R8) |
| `StopReason` | `completed`, `budget_steps`, `budget_time`, `budget_cost`, `user_stop`, `setup_failed`, `not_reproducible`, `service_unavailable`, `invalid_tool_calls`, `internal_error` | Shown next to the label |
| `TestOutcome` | `passed`, `failed`, `error`, `skipped` | Parsed from JUnit XML |
| `RunMode` | `single`, `parallel` | `parallel` enables Story 3 |
| `ModelRole` | `planner`, `worker`, `condenser` | Mapped to model IDs in config |

## Entities

### Task

| Field | Type | Rules |
|-------|------|-------|
| `kind` | `TaskKind` | required |
| `value` | `str` | 1–4,000 chars. For `issue`: a GitHub issue URL of the same repository. For `failing_test`: a pytest node ID such as `tests/test_x.py::test_y`. |
| `issue_title` / `issue_body` | `str \| None` | Filled by intake for `issue` tasks; body truncated to 8,000 chars |

### RepoRef

| Field | Type | Rules |
|-------|------|-------|
| `url` | `str` | Must match `^https://github\.com/[\w.-]+/[\w.-]+/?$` (optional `/tree/<ref>`) |
| `owner`, `name` | `str` | Derived from the URL |
| `ref` | `str` | Branch, tag, or SHA; defaults to the repository's default branch |
| `resolved_sha` | `str \| None` | Commit actually fetched (recorded for reproducibility) |
| `size_kb` | `int` | From the GitHub API; the demo rejects anything above `max_repo_mb * 1024` |
| `private` | `bool` | Must be `False` (FR-018) |

### Budget

| Field | Type | Default (CLI / demo) | Rules |
|-------|------|----------------------|-------|
| `max_steps` | `int` | 40 / 30 | ≥ 5; counts model calls, across all branches |
| `max_seconds` | `int` | 900 / 600 | ≥ 60 |
| `max_cost_usd` | `float` | 1.00 / 0.60 | > 0; computed from usage tokens × price table |
| `max_parallel` | `int` | 3 / 3 | 1–3; 1 means single-path |
| `command_timeout_s` | `int` | 300 | Install commands use 600 |
| `tool_output_chars` | `int` | 8,000 | Truncation limit for tool results sent to the model |

`BudgetTracker` (runtime, not persisted as a model) holds `steps_used`, `seconds_elapsed`, and
`cost_usd` plus `tokens_in`/`tokens_out` per model. `check()` raises `BudgetExceeded(reason)`.

### Snapshot

| Field | Type | Rules |
|-------|------|-------|
| `image_id` | `str` | Sandbox image UUID (or Docker image ID for the dev executor) |
| `parent_id` | `str \| None` | Lineage for branching |
| `label` | `str` | `source`, `installed`, `baseline`, `repro`, `attempt-<k>-step-<n>`, `final-<k>` |
| `tag` | `str \| None` | `fixproof/<run_id>/<label>` for key snapshots |
| `created_at` | `datetime` | UTC |

### TestCaseResult / TestRun

| Field | Type | Rules |
|-------|------|-------|
| `TestCaseResult.node_id` | `str` | pytest node ID built from JUnit `classname` and `name` |
| `TestCaseResult.outcome` | `TestOutcome` | |
| `TestCaseResult.duration_s` | `float` | |
| `TestCaseResult.message` | `str \| None` | Failure message, ≤ 2,000 chars |
| `TestRun.id` | `str` | `tr-<n>` |
| `TestRun.snapshot_id` | `str` | Image the tests ran on |
| `TestRun.selector` | `str \| None` | `None` means the full suite |
| `TestRun.results` | `list[TestCaseResult]` | |
| `TestRun.exit_code` | `int` | |
| `TestRun.duration_s` | `float` | |
| `TestRun.output_tail` | `str` | Last ≤ 4,000 chars of console output |
| `TestRun.timed_out` | `bool` | |

Derived properties: `passed_ids`, `failed_ids` (failed ∪ error), and `counts`.

### Evidence

| Field | Type | Rules |
|-------|------|-------|
| `baseline` | `TestRun` | Full suite before any change (FR-003) |
| `baseline_flaky` | `list[str]` | Tests that passed on one re-run (baseline failures, or apparent regressions after the fix); excluded from the regression check only |
| `repro_test_id` | `str \| None` | Existing failing test or the created reproduction test |
| `repro_created` | `bool` | `True` if the agent wrote the test (FR-004) |
| `repro_before` | `TestRun \| None` | Must show `repro_test_id` failing |
| `repro_after` | `list[TestRun]` | Exactly 3 consecutive runs for `verified` |
| `regression` | `TestRun \| None` | Full suite after the fix |
| `modified_test_files` | `list[str]` | Existing test files modified or deleted (FR-008), plus reproduction tests changed after the reproduction was confirmed |

**Labeling rule** (in `verify.py`; rationale in ADR-0004):

- `verified` requires all of the following:
  - `repro_after` has 3 runs and all pass `repro_test_id`;
  - `baseline.passed_ids − baseline_flaky ⊆ regression.passed_ids`;
  - `modified_test_files == []`;
  - the baseline has at least one passing test besides the reproduction test (flaky tests still
    count here; they are excluded only from the regression check).
- `needs_review` applies when the test conditions hold but `modified_test_files` is not empty,
  or the repository had no prior passing tests.
- Everything else is `not_verified`.

### FileChange / Patch

| Field | Type | Rules |
|-------|------|-------|
| `FileChange.path` | `str` | Relative to the repository root |
| `FileChange.status` | `added \| modified \| deleted` | |
| `FileChange.added` / `removed` | `int` | From `git diff --numstat` |
| `FileChange.is_test_file` | `bool` | Matches `tests/**`, `test_*.py`, `*_test.py`, `conftest.py` |
| `Patch.unified_diff` | `str` | `git diff` against the baseline commit, including new files |
| `Patch.files` | `list[FileChange]` | |
| `Patch.changed_lines` | `int` | Σ(added + removed); used for "smallest change" (FR-014) |

### Hypothesis / Attempt

| Field | Type | Rules |
|-------|------|-------|
| `Hypothesis.id` | `str` | `h1`…`h3` |
| `Hypothesis.statement` | `str` | ≤ 500 chars, from the planner |
| `Hypothesis.suspected_files` | `list[str]` | |
| `Attempt.id` | `str` | `a<k>` |
| `Attempt.hypothesis` | `Hypothesis \| None` | `None` in single-path mode |
| `Attempt.start_snapshot` | `Snapshot` | Always the `repro` snapshot |
| `Attempt.current_snapshot` | `Snapshot` | Advances on each mutation |
| `Attempt.steps` | `int` | |
| `Attempt.patch` | `Patch \| None` | |
| `Attempt.evidence` | `Evidence \| None` | |
| `Attempt.label` | `OutcomeLabel \| None` | |
| `Attempt.status` | `running \| verified \| failed \| cancelled \| budget_exhausted` | |

### Citation / Report

| Field | Type | Rules |
|-------|------|-------|
| `Citation.path` | `str` | Must exist in the final snapshot |
| `Citation.start_line` / `end_line` | `int` | 1-based, `start ≤ end` |
| `Report.run_id` | `str` | |
| `Report.label` | `OutcomeLabel` | Copied from the harness result, never from model output |
| `Report.stop_reason` | `StopReason` | |
| `Report.summary` | `str` | One paragraph |
| `Report.root_cause_md` | `str` | Must contain ≥ 1 citation when the label is not `not_verified` (FR-009) |
| `Report.citations` | `list[Citation]` | |
| `Report.patch` | `Patch \| None` | |
| `Report.evidence` | `Evidence \| None` | |
| `Report.hypotheses` | `list[{hypothesis, attempt_status, label, changed_lines, why}]` | Parallel mode only |
| `Report.flags` | `list[str]` | For example, "existing test file modified: tests/test_x.py" |
| `Report.cost_usd`, `Report.tokens`, `Report.duration_s` | numbers | |
| `Report.models` | `dict[ModelRole, str]` | Actual model IDs used |

### Run (aggregate root)

| Field | Type | Rules |
|-------|------|-------|
| `id` | `str` | `run-YYYYMMDD-HHMMSS-<6 hex>` |
| `repo` | `RepoRef` | |
| `task` | `Task` | |
| `mode` | `RunMode` | |
| `budget` | `Budget` | |
| `status` | `RunStatus` | |
| `stop_reason` | `StopReason \| None` | Set when entering `done` |
| `label` | `OutcomeLabel \| None` | Set when entering `done` |
| `plan` | `list[str]` | Plan steps shown to the user (Constitution IV). Published first as `initial` (within 30 s, from the task and the GitHub file tree, before install), then as `refined` after the baseline (SC-006) |
| `snapshots` | `list[Snapshot]` | |
| `attempts` | `list[Attempt]` | |
| `evidence` | `Evidence \| None` | Of the chosen attempt |
| `report` | `Report \| None` | |
| `created_at`, `started_at`, `ended_at` | `datetime \| None` | |
| `origin` | `cli \| web \| bench` | |
| `replay` | `bool` | `True` only for replayed runs; the UI must label them (FR-018) |
| `control_token_hash` | `str \| None` | Web runs only: SHA-256 of the one-time `control_token` that is required to stop the run. The plain token is never stored or logged |

**State transitions** (any non-terminal state can also go to `done` with `stop_reason` set to
`user_stop`, a budget reason, `service_unavailable`, or `internal_error`):

```text
queued → setting_up → baseline → planning → reproducing → fixing ⇄ verifying → reporting → done
                 │                              │
                 └─(install failed)→ reporting  └─(cannot reproduce)→ reporting
```

- `setting_up` fails → `reporting` with `stop_reason=setup_failed`, `label=not_verified`.
- `reproducing` exhausts its attempts → `stop_reason=not_reproducible`, `label=not_verified`.
- `fixing → verifying` happens when the worker calls `finish`. A failed verification returns to
  `fixing` with the failures fed to the planner for re-diagnosis, if budget remains.
- `reporting` always runs, even after a stop, so that partial results are returned (FR-012).

### TraceEvent (persisted as JSONL; see contracts/trace-events.md)

| Field | Type | Rules |
|-------|------|-------|
| `seq` | `int` | Strictly increasing per run |
| `ts` | `datetime` | UTC ISO-8601 |
| `run_id` | `str` | |
| `attempt_id` | `str \| None` | |
| `type` | `str` | One of the contract's event types |
| `data` | `dict` | Type-specific payload, **secrets redacted** before write |

### Demo entities (web only)

| Entity | Fields | Rules |
|--------|--------|-------|
| `SampleTask` | `id`, `title`, `repo_url`, `ref`, `task: Task`, `image_tag \| None`, `expected_minutes` | ≥ 3 curated (FR-019) |
| `VisitorAllowance` | `visitor_key` (hashed IP), `day`, `runs_started` | Default ≤ 3 per day |
| `DailyBudget` | `day`, `cost_usd` (model tokens + estimated sandbox minutes), `cap_usd` | Persisted to `<FIXPROOF_STATE_DIR>/_budget.json` (default `runs/`). On hosts with ephemeral disks, such as free Hugging Face Spaces, the file resets on restart, so the documented daily cap is set conservatively. Point `FIXPROOF_STATE_DIR` at persistent storage when it is available |
| `ReplayEntry` | `name`, `title`, `trace_path`, `label`, `recorded_at` | Served only with `replay: true` |

### BenchmarkTask (bench/tasks.toml)

| Field | Type | Rules |
|-------|------|-------|
| `id` | `str` | For example, a SWE-bench instance ID |
| `repo_url`, `base_commit` | `str` | Revision before the official fix |
| `task` | `Task` | Usually `issue` text |
| `hidden_fail_to_pass`, `hidden_pass_to_pass` | `list[str]` | **Never** given to the agent |
| `image_tag` | `str \| None` | Preloaded or pre-built sandbox image |
| `python` | `str` | Default `3.12` |
