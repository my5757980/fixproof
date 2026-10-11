"""Run management for the public judge demo (FR-017, FR-018, FR-019).

One ``RunManager`` serves the web app:

- it admits at most ``FIXPROOF_DEMO_MAX_CONCURRENT`` live runs; others wait in FIFO order;
- it enforces a per-visitor daily allowance (keyed by a SHA-256 of the client IP) and a daily
  cost cap persisted in ``<FIXPROOF_STATE_DIR>/_budget.json``; a run is admitted only when the
  rest of today's budget can cover its worst case (model cap plus estimated sandbox minutes);
- it returns a random per-run control token once and keeps only its SHA-256, which ``stop``
  requires;
- it serves finished runs from disk and keeps the newest runs only;
- it lists the labeled replays of recorded real runs (``replays/index.toml``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import re
import secrets
import shutil
import tomllib
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fixproof.agent.orchestrator import Orchestrator, RunRequest, new_event_bus
from fixproof.config import ConfigError, Settings
from fixproof.events import EventType, TraceEvent
from fixproof.llm.client import ModelClient
from fixproof.models import RUN_ID_PATTERN, OutcomeLabel, RunMode, SampleTask, Task, TaskKind
from fixproof.repo.github import GitHubError, RepoSource, parse_issue_url, parse_repo_url
from fixproof.sandbox.executor import Executor
from fixproof.sandbox.factory import make_executor
from fixproof.trace import read_trace
from fixproof.wiring import github_source, token_factory_client

KEEP_RUNS = 200
REPLAY_NAME = re.compile(r"^[a-z0-9-]{1,64}$")
EventCallback = Callable[[EventType, dict[str, Any]], None]


def utc_today() -> date:
    """Return today's date in UTC (daily limits reset at midnight UTC)."""
    return datetime.now(UTC).date()


class DemoError(Exception):
    """A request the demo refuses, with its HTTP status and contract error code.

    Args:
        status: HTTP status code.
        code: Error code from the ``Error`` schema of ``contracts/openapi.yaml``.
        message: What happened and how to proceed.
        replay_suggestion: A recorded run to offer instead, if any.
    """

    def __init__(
        self, status: int, code: str, message: str, *, replay_suggestion: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.replay_suggestion = replay_suggestion

    def body(self) -> dict[str, Any]:
        """Return the JSON error body."""
        return {
            "error": self.code,
            "message": self.message,
            "replay_suggestion": self.replay_suggestion,
        }


class TaskInput(BaseModel):
    """A task as sent by the browser."""

    model_config = ConfigDict(extra="forbid")

    kind: TaskKind
    value: str = Field(min_length=1, max_length=4000)


class RunCreate(BaseModel):
    """Body of ``POST /api/runs``: a sample, or a repository plus a task."""

    model_config = ConfigDict(extra="forbid")

    sample_id: str | None = Field(default=None, max_length=100)
    repo_url: str | None = Field(default=None, max_length=300)
    task: TaskInput | None = None
    mode: Literal["single", "parallel"] = "single"


class RunCreated(BaseModel):
    """Response of ``POST /api/runs``; ``control_token`` is returned only here."""

    run_id: str
    status: Literal["queued", "setting_up"]
    queue_position: int
    control_token: str
    events_url: str


class ReplayEntry(BaseModel):
    """One labeled replay of a recorded real run."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=REPLAY_NAME.pattern)
    title: str = Field(min_length=1, max_length=200)
    label: OutcomeLabel
    recorded_at: datetime


@dataclass
class RunFactories:
    """How the manager builds per-run services (tests pass fakes)."""

    model: Callable[[Settings], ModelClient] = token_factory_client
    executor: Callable[[Settings, EventCallback], Executor] = make_executor
    repo_source: Callable[[Settings], RepoSource] = github_source


class DailyBudget:
    """Today's demo spending, persisted so a restart keeps it while the directory persists.

    Args:
        path: The JSON file (``<state_dir>/_budget.json``).
        cap_usd: The daily cap.
        today: Returns the current UTC date (injectable for tests).
    """

    def __init__(self, path: Path, cap_usd: float, *, today: Callable[[], date]) -> None:
        self._path = path
        self.cap_usd = cap_usd
        self._today = today
        self._day, self._spent = self._load()

    @property
    def spent_usd(self) -> float:
        """Spent today."""
        self._roll()
        return self._spent

    @property
    def remaining_usd(self) -> float:
        """Left today (never negative)."""
        return max(self.cap_usd - self.spent_usd, 0.0)

    def charge(self, usd: float) -> None:
        """Add a finished run's cost and persist the total."""
        self._roll()
        self._spent += max(usd, 0.0)
        self._save()

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._spent = today, 0.0

    def _load(self) -> tuple[date, float]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return date.fromisoformat(data["day"]), float(data["cost_usd"])
        except (OSError, ValueError, KeyError, TypeError):
            return self._today(), 0.0

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "day": self._day.isoformat(),
            "cost_usd": round(self._spent, 6),
            "cap_usd": self.cap_usd,
        }
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(self._path)


class VisitorAllowance:
    """Live runs per visitor per day; visitors are keyed by a hash, never by the raw IP.

    Args:
        per_day: Runs each visitor may start per UTC day.
        today: Returns the current UTC date (injectable for tests).
    """

    def __init__(self, per_day: int, *, today: Callable[[], date]) -> None:
        self._per_day = per_day
        self._today = today
        self._day = today()
        self._used: dict[str, int] = {}

    @staticmethod
    def key(client_ip: str) -> str:
        """Return the visitor key for a client IP."""
        return hashlib.sha256(f"fixproof-visitor:{client_ip}".encode()).hexdigest()

    def remaining(self, key: str) -> int:
        """Runs ``key`` may still start today."""
        self._roll()
        return max(self._per_day - self._used.get(key, 0), 0)

    def consume(self, key: str) -> None:
        """Count one started run for ``key``."""
        self._roll()
        self._used[key] = self._used.get(key, 0) + 1

    def _roll(self) -> None:
        today = self._today()
        if today != self._day:
            self._day, self._used = today, {}


@dataclass(eq=False)
class ManagedRun:
    """A run started by this server process."""

    run_id: str
    request: RunRequest
    orchestrator: Orchestrator
    executor: Executor
    token_hash: str
    reserved_usd: float
    admitted: bool = False
    started: bool = False
    finished: bool = False
    task: asyncio.Task[None] | None = None
    admission: asyncio.Event = field(default_factory=asyncio.Event)
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def stop_requested(self) -> bool:
        """Whether a stop was requested."""
        return self.stop_event.is_set()


def run_view(
    run_id: str, events: Sequence[TraceEvent], *, request: RunRequest | None = None
) -> dict[str, Any]:
    """Build the ``RunView`` of the API contract from a run's events."""
    view: dict[str, Any] = {
        "run_id": run_id,
        "status": "queued",
        "replay": False,
        "label": None,
        "stop_reason": None,
        "repo_url": request.repo_url if request else None,
        "task": {"kind": request.task.kind.value, "value": request.task.value} if request else None,
        "plan": [],
        "summary": None,
        "root_cause_md": None,
        "changed_lines": None,
        "cost_usd": 0.0,
        "duration_s": 0.0,
        "models": {},
    }
    for event in events:
        data = event.data
        match event.type:
            case EventType.RUN_STARTED:
                view.update(
                    repo_url=data["repo_url"], task=data["task"], models=dict(data["models"])
                )
            case EventType.PHASE_CHANGED:
                view["status"] = data["to"]
            case EventType.PLAN:
                view["plan"] = list(data["steps"])
            case EventType.MODEL_CALL:
                view["models"][data["role"]] = data["model"]
            case EventType.BUDGET:
                view["cost_usd"] = data["cost_usd"]
            case EventType.REPORT:
                view.update(
                    label=data["label"],
                    stop_reason=data["stop_reason"],
                    summary=data["summary"],
                    root_cause_md=data["root_cause_md"],
                    changed_lines=data["changed_lines"],
                )
            case EventType.RUN_FINISHED:
                view.update(
                    status="done",
                    label=data["label"],
                    stop_reason=data["stop_reason"],
                    cost_usd=data["cost_usd"],
                    duration_s=data["duration_s"],
                )
    return view


def load_replays(replays_dir: Path) -> list[ReplayEntry]:
    """Load ``replays/index.toml``; entries whose trace file is missing are skipped.

    Raises:
        ValueError: If an entry is invalid.
    """
    index = replays_dir / "index.toml"
    if not index.is_file():
        return []
    data = tomllib.loads(index.read_text(encoding="utf-8"))
    entries = [ReplayEntry.model_validate(item) for item in data.get("replays", [])]
    return [entry for entry in entries if (replays_dir / f"{entry.name}.jsonl").is_file()]


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RunManager:
    """Admission, limits, budget, and the run registry of the demo.

    Args:
        settings: Demo settings (limits, state directory, executor, models).
        factories: Builders of per-run services.
        samples: Curated one-click samples.
        replays_dir: Directory with ``index.toml`` and ``<name>.jsonl`` traces.
        today: Returns the current UTC date (injectable for tests).
        keep_runs: Number of newest run folders kept in the state directory.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        factories: RunFactories | None = None,
        samples: Sequence[SampleTask] = (),
        replays_dir: Path = Path("replays"),
        today: Callable[[], date] = utc_today,
        keep_runs: int = KEEP_RUNS,
    ) -> None:
        self.settings = settings
        self._factories = factories or RunFactories()
        self._samples = {sample.id: sample for sample in samples}
        self._replays_dir = replays_dir
        self._keep_runs = keep_runs
        self._state_dir = settings.state_dir
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self.budget = DailyBudget(
            self._state_dir / "_budget.json", settings.demo_daily_cap_usd, today=today
        )
        self._allowance = VisitorAllowance(settings.demo_runs_per_visitor, today=today)
        self._limits = settings.budget_demo()
        self._run_reserve = self._limits.max_cost_usd + (
            settings.sandbox_cost_per_min_usd * self._limits.max_seconds / 60
        )
        self._runs: dict[str, ManagedRun] = {}
        self._queue: deque[ManagedRun] = deque()
        self._admitted = 0
        self._order = sorted(
            p.name for p in self._state_dir.iterdir() if p.is_dir() and RUN_ID_PATTERN.match(p.name)
        )
        self._repo_source: RepoSource | None = None
        self.paused_reason = self._configuration_problem()
        load_replays(replays_dir)  # fail fast on an invalid catalog

    # -- queries -------------------------------------------------------------------------

    def runs(self) -> list[ManagedRun]:
        """Runs started by this process that are still registered."""
        return list(self._runs.values())

    def get(self, run_id: str) -> ManagedRun | None:
        """Return a run started by this process, if registered."""
        return self._runs.get(run_id)

    def samples(self) -> list[SampleTask]:
        """The curated samples."""
        return list(self._samples.values())

    def replays(self) -> list[ReplayEntry]:
        """The labeled replays available now."""
        return load_replays(self._replays_dir)

    def replay_path(self, name: str) -> Path | None:
        """Return the trace of replay ``name``, or ``None`` if there is no such replay."""
        if not REPLAY_NAME.match(name) or name not in {e.name for e in self.replays()}:
            return None
        return self._replays_dir / f"{name}.jsonl"

    def live_status(self) -> tuple[bool, str | None]:
        """Return whether a new live run can start now, and why not."""
        if self.paused_reason is not None:
            return False, self.paused_reason
        reserved = sum(r.reserved_usd for r in self._runs.values() if not r.finished)
        if self.budget.remaining_usd - reserved < self._run_reserve:
            return False, (
                "Today's demo budget is used up. Live runs resume tomorrow (UTC); you can watch "
                "a recorded run now."
            )
        return True, None

    def health(self) -> dict[str, Any]:
        """Return the ``Health`` body of the API contract."""
        available, reason = self.live_status()
        return {
            "status": "ok" if available else "degraded",
            "live_runs_available": available,
            "reason": reason,
            "budget_remaining_usd": round(self.budget.remaining_usd, 4),
            "active_runs": self._admitted,
            "queue_length": len(self._queue),
            "executor": self.settings.executor,
            "models": self.settings.models_by_role(),
        }

    def view(self, run_id: str) -> dict[str, Any] | None:
        """Return the ``RunView`` of a run (live or finished on disk), or ``None``."""
        managed = self._runs.get(run_id)
        if managed is not None:
            return run_view(run_id, managed.orchestrator.bus.history, request=managed.request)
        trace = self._trace_path(run_id)
        return run_view(run_id, read_trace(trace)) if trace else None

    def events_history(self, run_id: str) -> list[TraceEvent]:
        """Return the events recorded so far.

        Raises:
            DemoError: 404 if the run is unknown.
        """
        managed = self._runs.get(run_id)
        if managed is not None:
            return list(managed.orchestrator.bus.history)
        trace = self._trace_path(run_id)
        if trace is None:
            raise DemoError(404, "not_found", f"Unknown run {run_id}.")
        return read_trace(trace)

    def events(self, run_id: str, *, after: int = 0) -> AsyncIterator[TraceEvent]:
        """Stream the events after ``after``: past events first, then live ones.

        Raises:
            DemoError: 404 if the run is unknown.
        """
        managed = self._runs.get(run_id)
        if managed is not None:
            return self._live_events(managed, after)
        trace = self._trace_path(run_id)
        if trace is None:
            raise DemoError(404, "not_found", f"Unknown run {run_id}.")
        return self._stored_events(trace, after)

    def patch_path(self, run_id: str) -> Path | None:
        """Return the run's ``patch.diff``, if it exists."""
        if not RUN_ID_PATTERN.match(run_id):
            return None
        path = self._state_dir / run_id / "patch.diff"
        return path if path.is_file() else None

    # -- commands ------------------------------------------------------------------------

    async def create(self, payload: RunCreate, client_ip: str) -> RunCreated:
        """Validate a request, apply the limits, and start (or queue) the run.

        Raises:
            DemoError: 400 for invalid input, 429 for the visitor limit, 503 when live runs
                are paused (daily budget, configuration, or GitHub unavailable).
        """
        request, trusted = self._resolve(payload)
        self._ensure_available()
        visitor = self._allowance.key(client_ip)
        if self._allowance.remaining(visitor) <= 0:
            raise DemoError(
                429,
                "visitor_limit",
                f"Each visitor can start {self.settings.demo_runs_per_visitor} live runs per day. "
                "Watch a recorded run, or come back tomorrow (UTC).",
                replay_suggestion=self._replay_suggestion(),
            )
        if not trusted:
            await self._check_repository(request)
            self._ensure_available()  # the GitHub check awaited; re-check the budget
        self._allowance.consume(visitor)
        return self._launch(request)

    def stop(self, run_id: str, token: str) -> None:
        """Stop a run started by the holder of ``token``.

        Raises:
            DemoError: 404 unknown run, 403 wrong token, 409 already finished or stopping.
        """
        managed = self._runs.get(run_id)
        if managed is None:
            raise DemoError(404, "not_found", f"Unknown run {run_id}.")
        if not token or not hmac.compare_digest(_token_hash(token), managed.token_hash):
            raise DemoError(403, "forbidden", "Only the visitor who started this run can stop it.")
        if managed.finished or managed.stop_requested:
            raise DemoError(
                409, "already_finished", "This run has finished or is already stopping."
            )
        managed.stop_event.set()
        if managed in self._queue:
            self._queue.remove(managed)
        managed.orchestrator.stop()

    async def shutdown(self) -> None:
        """Stop every live run, wait for the reports, and release shared clients."""
        for managed in self._runs.values():
            if not managed.finished:
                managed.stop_event.set()
                managed.orchestrator.stop()
        pending = [m.task for m in self._runs.values() if m.task is not None and not m.task.done()]
        if pending:
            await asyncio.wait(pending, timeout=15)
        if self._repo_source is not None:
            await self._repo_source.aclose()
            self._repo_source = None

    # -- internals -----------------------------------------------------------------------

    def _resolve(self, payload: RunCreate) -> tuple[RunRequest, bool]:
        """Turn the request body into a ``RunRequest``; samples are trusted."""
        mode = RunMode(payload.mode)
        max_parallel = self._limits.max_parallel  # the demo allows at most 3 branches
        if payload.sample_id is not None:
            if payload.repo_url is not None or payload.task is not None:
                raise DemoError(
                    400, "invalid_task", "Send either sample_id, or repo_url with task, not both."
                )
            sample = self._samples.get(payload.sample_id)
            if sample is None:
                raise DemoError(400, "invalid_task", f"Unknown sample {payload.sample_id!r}.")
            request = RunRequest(
                repo_url=sample.repo_url,
                task=sample.task,
                ref=sample.ref,
                origin="web",
                base_image=sample.image_tag,
                mode=mode,
                max_parallel=max_parallel,
            )
            return request, True
        if payload.repo_url is None or payload.task is None:
            raise DemoError(400, "invalid_task", "Send sample_id, or both repo_url and task.")
        try:
            location = parse_repo_url(payload.repo_url)
            task = Task(kind=payload.task.kind, value=payload.task.value.strip())
            if task.kind is TaskKind.ISSUE:
                parse_issue_url(task.value, location)
        except GitHubError as exc:
            raise DemoError(400, exc.code, str(exc)) from exc
        except ValidationError as exc:
            raise DemoError(400, "invalid_task", "The task is empty or too long.") from exc
        request = RunRequest(
            repo_url=payload.repo_url,
            task=task,
            ref=location.ref,
            origin="web",
            mode=mode,
            max_parallel=max_parallel,
        )
        return request, False

    def _ensure_available(self) -> None:
        available, reason = self.live_status()
        if not available:
            code = "live_paused" if self.paused_reason else "daily_limit"
            raise DemoError(
                503,
                code,
                reason or "Live runs are paused.",
                replay_suggestion=self._replay_suggestion(),
            )

    async def _check_repository(self, request: RunRequest) -> None:
        location = parse_repo_url(request.repo_url)
        try:
            await self._github().get_repo(location, max_kb=self.settings.demo_max_repo_mb * 1024)
        except GitHubError as exc:
            if exc.code in ("rate_limited", "github_error"):
                raise DemoError(
                    503,
                    "live_paused",
                    f"GitHub is not reachable right now ({exc}). Try again shortly.",
                    replay_suggestion=self._replay_suggestion(),
                ) from exc
            raise DemoError(400, exc.code, str(exc)) from exc

    def _launch(self, request: RunRequest) -> RunCreated:
        token = secrets.token_urlsafe(32)
        bus = new_event_bus(self.settings)

        def publish(kind: EventType, data: dict[str, Any]) -> None:
            if not bus.closed:
                bus.publish(kind, data)

        executor = self._factories.executor(self.settings, publish)
        orchestrator = Orchestrator(
            settings=self.settings,
            model=self._factories.model(self.settings),
            executor=executor,
            repo_source=self._github(),
            bus=bus,
            runs_dir=self._state_dir,
            budget=self._limits,
            max_repo_kb=self.settings.demo_max_repo_mb * 1024,
        )
        managed = ManagedRun(
            run_id=bus.run_id,
            request=request,
            orchestrator=orchestrator,
            executor=executor,
            token_hash=_token_hash(token),
            reserved_usd=self._run_reserve,
        )
        self._runs[managed.run_id] = managed
        self._order.append(managed.run_id)
        if self._admitted < self.settings.demo_max_concurrent and not self._queue:
            self._admit(managed)
            status: Literal["queued", "setting_up"] = "setting_up"
            position = 0
        else:
            position = len(self._queue)
            self._queue.append(managed)
            status = "queued"
        managed.task = asyncio.create_task(self._execute(managed))
        return RunCreated(
            run_id=managed.run_id,
            status=status,
            queue_position=position,
            control_token=token,
            events_url=f"/api/runs/{managed.run_id}/events",
        )

    def _admit(self, managed: ManagedRun) -> None:
        managed.admitted = True
        self._admitted += 1
        managed.admission.set()

    def _admit_next(self) -> None:
        while self._queue and self._admitted < self.settings.demo_max_concurrent:
            candidate = self._queue.popleft()
            if not candidate.stop_requested and not candidate.finished:
                self._admit(candidate)

    async def _execute(self, managed: ManagedRun) -> None:
        try:
            if not managed.admitted:
                await self._wait_for_admission(managed)
            managed.started = True
            await managed.orchestrator.run(managed.request)
        finally:
            managed.finished = True
            if managed.admitted:
                self._admitted -= 1
                self._admit_next()
            with contextlib.suppress(Exception):
                await managed.executor.close()
            self._settle(managed)
            self._prune()

    async def _wait_for_admission(self, managed: ManagedRun) -> None:
        """Wait until the run is admitted, or until it is stopped while still queued."""
        admitted = asyncio.ensure_future(managed.admission.wait())
        stopped = asyncio.ensure_future(managed.stop_event.wait())
        try:
            await asyncio.wait({admitted, stopped}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            admitted.cancel()
            stopped.cancel()

    def _settle(self, managed: ManagedRun) -> None:
        """Charge the finished run: model cost plus estimated sandbox minutes."""
        managed.reserved_usd = 0.0
        finished = next(
            (
                e
                for e in reversed(managed.orchestrator.bus.history)
                if e.type is EventType.RUN_FINISHED
            ),
            None,
        )
        if finished is None:
            return
        minutes = float(finished.data["duration_s"]) / 60
        cost = float(finished.data["cost_usd"]) + minutes * self.settings.sandbox_cost_per_min_usd
        self.budget.charge(cost)

    def _prune(self) -> None:
        """Delete the oldest finished run folders beyond ``keep_runs``."""
        while len(self._order) > self._keep_runs:
            oldest = self._order[0]
            managed = self._runs.get(oldest)
            if managed is not None and not managed.finished:
                return  # never delete a run that is still going
            self._order.pop(0)
            self._runs.pop(oldest, None)
            shutil.rmtree(self._state_dir / oldest, ignore_errors=True)

    def _trace_path(self, run_id: str) -> Path | None:
        if not RUN_ID_PATTERN.match(run_id):
            return None
        path = self._state_dir / run_id / "trace.jsonl"
        return path if path.is_file() else None

    def _github(self) -> RepoSource:
        if self._repo_source is None:
            self._repo_source = self._factories.repo_source(self.settings)
        return self._repo_source

    def _replay_suggestion(self) -> str | None:
        replays = self.replays()
        return replays[0].name if replays else None

    def _configuration_problem(self) -> str | None:
        try:
            self.settings.require_api_key()
            if self.settings.executor == "contree":
                self.settings.sandbox_token()
                self.settings.require_sandbox_project()
        except ConfigError as exc:
            return f"Live runs are not configured on this server: {exc}"
        return None

    @staticmethod
    async def _live_events(managed: ManagedRun, after: int) -> AsyncIterator[TraceEvent]:
        async for event in managed.orchestrator.bus.subscribe():
            if event.seq > after:
                yield event

    @staticmethod
    async def _stored_events(trace: Path, after: int) -> AsyncIterator[TraceEvent]:
        for event in read_trace(trace):
            if event.seq > after:
                yield event
