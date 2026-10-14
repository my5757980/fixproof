"""Domain models for FixProof runs, evidence, and reports.

The models mirror ``specs/001-verified-fix-agent/data-model.md``. Value objects are frozen
Pydantic models. Aggregates that the orchestrator updates while a run is in progress
(``Evidence``, ``Attempt``, ``Report``, ``Run``) are mutable, with assignment validation.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RUN_ID_PATTERN = re.compile(r"^run-\d{8}-\d{6}-[0-9a-f]{6}$")

_FROZEN = ConfigDict(frozen=True, extra="forbid")
_MUTABLE = ConfigDict(extra="forbid", validate_assignment=True)


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def new_run_id(now: datetime | None = None) -> str:
    """Create a run ID of the form ``run-YYYYMMDD-HHMMSS-<6 hex>``.

    Args:
        now: Timestamp to embed; defaults to the current UTC time.

    Returns:
        A new, practically unique run identifier.
    """
    stamp = (now or utc_now()).strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{secrets.token_hex(3)}"


class TaskKind(StrEnum):
    """Kind of task a run is asked to resolve (FR-001)."""

    ISSUE = "issue"
    FAILING_TEST = "failing_test"
    DESCRIPTION = "description"


class RunStatus(StrEnum):
    """Lifecycle state of a run; ``done`` is terminal."""

    QUEUED = "queued"
    SETTING_UP = "setting_up"
    BASELINE = "baseline"
    PLANNING = "planning"
    REPRODUCING = "reproducing"
    FIXING = "fixing"
    VERIFYING = "verifying"
    REPORTING = "reporting"
    DONE = "done"


class OutcomeLabel(StrEnum):
    """Outcome label computed by the harness, never by the model (research R8)."""

    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    NOT_VERIFIED = "not_verified"


class StopReason(StrEnum):
    """Why a run ended; shown next to the outcome label."""

    COMPLETED = "completed"
    BUDGET_STEPS = "budget_steps"
    BUDGET_TIME = "budget_time"
    BUDGET_COST = "budget_cost"
    USER_STOP = "user_stop"
    SETUP_FAILED = "setup_failed"
    NOT_REPRODUCIBLE = "not_reproducible"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INVALID_TOOL_CALLS = "invalid_tool_calls"
    INTERNAL_ERROR = "internal_error"


class TestOutcome(StrEnum):
    """Outcome of a single test case, parsed from JUnit XML."""

    __test__ = False  # not a pytest test class

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class RunMode(StrEnum):
    """Single-path run, or parallel hypotheses (User Story 3)."""

    SINGLE = "single"
    PARALLEL = "parallel"


class ModelRole(StrEnum):
    """Role a model plays in the agent; each role maps to a configured model ID."""

    PLANNER = "planner"
    WORKER = "worker"
    CONDENSER = "condenser"


class AttemptStatus(StrEnum):
    """Status of one fix attempt (one hypothesis branch in parallel mode)."""

    RUNNING = "running"
    VERIFIED = "verified"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


class FileStatus(StrEnum):
    """How a file changed relative to the baseline commit."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class Task(BaseModel):
    """What the user asked for: an issue link, a failing test ID, or a bug description."""

    model_config = _FROZEN

    kind: TaskKind
    value: str = Field(min_length=1, max_length=4000)
    issue_title: str | None = None
    issue_body: str | None = Field(default=None, max_length=8000)


class RepoRef(BaseModel):
    """A public GitHub repository and the revision a run works on."""

    model_config = _FROZEN

    url: str
    owner: str
    name: str
    ref: str | None = None
    resolved_sha: str | None = None
    size_kb: int = Field(default=0, ge=0)
    private: bool = False
    default_branch: str | None = None


class Budget(BaseModel):
    """Limits that bound every run (FR-006, Constitution III)."""

    model_config = _FROZEN

    max_steps: int = Field(ge=5)
    max_seconds: int = Field(ge=60)
    max_cost_usd: float = Field(gt=0)
    max_parallel: int = Field(default=3, ge=1, le=3)
    command_timeout_s: int = Field(default=300, ge=1)
    install_timeout_s: int = Field(default=600, ge=1)
    tool_output_chars: int = Field(default=8000, ge=500)


class Snapshot(BaseModel):
    """A saved state of the isolated environment (a sandbox image version)."""

    model_config = _FROZEN

    image_id: str
    parent_id: str | None = None
    label: str
    tag: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class TestCaseResult(BaseModel):
    """Result of one test case."""

    __test__: ClassVar[bool] = False

    model_config = _FROZEN

    node_id: str
    outcome: TestOutcome
    duration_s: float = 0.0
    message: str | None = Field(default=None, max_length=2000)


class TestRun(BaseModel):
    """One execution of pytest inside the sandbox."""

    __test__: ClassVar[bool] = False

    model_config = _FROZEN

    id: str
    snapshot_id: str
    selector: str | None = None
    results: tuple[TestCaseResult, ...] = ()
    exit_code: int
    duration_s: float = 0.0
    output_tail: str = ""
    timed_out: bool = False

    @property
    def passed_ids(self) -> frozenset[str]:
        """Node IDs of tests that passed."""
        return frozenset(r.node_id for r in self.results if r.outcome is TestOutcome.PASSED)

    @property
    def failed_ids(self) -> frozenset[str]:
        """Node IDs of tests that failed or errored."""
        bad = {TestOutcome.FAILED, TestOutcome.ERROR}
        return frozenset(r.node_id for r in self.results if r.outcome in bad)

    @property
    def counts(self) -> dict[str, int]:
        """Number of tests per outcome, with every outcome present."""
        totals = {outcome.value: 0 for outcome in TestOutcome}
        for result in self.results:
            totals[result.outcome.value] += 1
        return totals

    def outcome_of(self, node_id: str) -> TestOutcome | None:
        """Return the outcome of ``node_id``, or ``None`` if it did not run."""
        for result in self.results:
            if result.node_id == node_id:
                return result.outcome
        return None


class Evidence(BaseModel):
    """Test evidence collected by the harness for one attempt."""

    model_config = _MUTABLE

    baseline: TestRun
    baseline_flaky: list[str] = Field(default_factory=list)
    repro_test_id: str | None = None
    repro_created: bool = False
    repro_before: TestRun | None = None
    repro_after: list[TestRun] = Field(default_factory=list)
    regression: TestRun | None = None
    modified_test_files: list[str] = Field(default_factory=list)


class FileChange(BaseModel):
    """One file in a patch."""

    model_config = _FROZEN

    path: str
    status: FileStatus
    added: int = Field(default=0, ge=0)
    removed: int = Field(default=0, ge=0)
    is_test_file: bool = False


class Patch(BaseModel):
    """The proposed change relative to the baseline commit."""

    model_config = _FROZEN

    unified_diff: str = ""
    files: tuple[FileChange, ...] = ()

    @property
    def changed_lines(self) -> int:
        """Total added plus removed lines; used to pick the smallest fix (FR-014)."""
        return sum(change.added + change.removed for change in self.files)

    @property
    def is_empty(self) -> bool:
        """Whether the patch changes nothing."""
        return not self.files


class Hypothesis(BaseModel):
    """A competing explanation of the root cause (parallel mode)."""

    model_config = _FROZEN

    id: str
    statement: str = Field(min_length=1, max_length=500)
    suspected_files: tuple[str, ...] = ()


class Attempt(BaseModel):
    """One path toward a fix, starting from the reproduction snapshot."""

    model_config = _MUTABLE

    id: str
    hypothesis: Hypothesis | None = None
    start_snapshot: Snapshot
    current_snapshot: Snapshot
    steps: int = Field(default=0, ge=0)
    patch: Patch | None = None
    evidence: Evidence | None = None
    label: OutcomeLabel | None = None
    status: AttemptStatus = AttemptStatus.RUNNING


class Citation(BaseModel):
    """A file and line range that a root-cause explanation relies on."""

    model_config = _FROZEN

    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_range(self) -> Citation:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class HypothesisRow(BaseModel):
    """One row of the parallel-mode comparison table in a report."""

    model_config = _FROZEN

    hypothesis_id: str
    statement: str
    attempt_status: AttemptStatus
    label: OutcomeLabel | None = None
    changed_lines: int | None = None
    why: str = ""


class Report(BaseModel):
    """Final report of a run. The label always comes from the harness."""

    model_config = _MUTABLE

    run_id: str
    label: OutcomeLabel
    stop_reason: StopReason
    summary: str = ""
    root_cause_md: str = ""
    citations: list[Citation] = Field(default_factory=list)
    patch: Patch | None = None
    evidence: Evidence | None = None
    hypotheses: list[HypothesisRow] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    preexisting_failures: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    tokens: dict[str, int] = Field(default_factory=dict)
    duration_s: float = 0.0
    models: dict[str, str] = Field(default_factory=dict)


class Run(BaseModel):
    """Aggregate root for one run; updated by the orchestrator through its lifecycle."""

    model_config = _MUTABLE

    id: str = Field(default_factory=new_run_id, pattern=RUN_ID_PATTERN.pattern)
    repo: RepoRef
    task: Task
    mode: RunMode = RunMode.SINGLE
    budget: Budget
    status: RunStatus = RunStatus.QUEUED
    stop_reason: StopReason | None = None
    label: OutcomeLabel | None = None
    plan: list[str] = Field(default_factory=list)
    snapshots: list[Snapshot] = Field(default_factory=list)
    attempts: list[Attempt] = Field(default_factory=list)
    evidence: Evidence | None = None
    report: Report | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    origin: Literal["cli", "web", "bench"] = "cli"
    replay: bool = False
    control_token_hash: str | None = None


class SampleTask(BaseModel):
    """A curated one-click task for the judge demo (FR-019).

    ``image_tag`` and ``pip_packages`` (pins installed after the recipe) set up the sample's
    environment, as for benchmark tasks.
    """

    model_config = _FROZEN

    id: str
    title: str
    repo_url: str
    ref: str | None = None
    task: Task
    image_tag: str | None = None
    pip_packages: tuple[str, ...] = ()
    expected_minutes: int = Field(ge=1)


class BenchmarkTask(BaseModel):
    """A real, already-fixed bug used only for measurement (FR-023).

    The hidden tests, and the official test patch that adds them, are never shown to the agent.
    ``hidden_test_patch`` is a path relative to the task file. ``pip_packages`` are pins
    installed after the detected recipe, for old revisions that newer dependencies break.
    """

    model_config = _FROZEN

    id: str
    repo_url: str
    base_commit: str
    task: Task
    hidden_fail_to_pass: tuple[str, ...] = ()
    hidden_pass_to_pass: tuple[str, ...] = ()
    hidden_test_patch: str | None = None
    pip_packages: tuple[str, ...] = ()
    image_tag: str | None = None
    python: str = "3.12"
