"""The public judge demo: a FastAPI service for ``contracts/openapi.yaml`` plus a static UI.

Live runs call Nebius Token Factory and run code in Token Factory Sandboxes; the service refuses
dev settings at startup (``assert_demo_safe``). Events stream as Server-Sent Events
(``id``/``event``/``data`` lines, ``Last-Event-ID`` resume, keep-alive comments). Replays are
recorded real runs, and every replayed event carries ``replay: true``. There is deliberately no
endpoint that applies a patch or opens a pull request (FR-016).
"""

from __future__ import annotations

import asyncio
import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fixproof import __version__
from fixproof.config import Settings, load_settings
from fixproof.events import TraceEvent
from fixproof.models import SampleTask
from fixproof.sandbox.factory import assert_demo_safe
from fixproof.trace import replay as replay_trace
from fixproof.web.runs import (
    DemoError,
    ReplayEntry,
    RunCreate,
    RunCreated,
    RunManager,
    TaskInput,
)

STATIC_DIR = Path(__file__).with_name("static")
SAMPLES_FILE = Path(__file__).with_name("samples.toml")
KEEPALIVE_S = 15.0
_EVENT_STREAM = {"content": {"text/event-stream": {"schema": {"type": "string"}}}}


class ErrorBody(BaseModel):
    """The ``Error`` schema of the API contract."""

    error: str
    message: str
    replay_suggestion: str | None = None


class Health(BaseModel):
    """The ``Health`` schema of the API contract."""

    status: Literal["ok", "degraded"]
    live_runs_available: bool
    reason: str | None = None
    budget_remaining_usd: float
    active_runs: int
    queue_length: int
    executor: Literal["contree", "docker"]
    models: dict[str, str]


class SampleOut(BaseModel):
    """The ``Sample`` schema of the API contract."""

    id: str
    title: str
    repo_url: str
    ref: str | None = None
    task: TaskInput
    expected_minutes: int


class RunView(BaseModel):
    """The ``RunView`` schema of the API contract."""

    run_id: str
    status: str
    replay: bool
    label: str | None = None
    stop_reason: str | None = None
    repo_url: str | None = None
    task: TaskInput | None = None
    plan: list[str] = []
    summary: str | None = None
    root_cause_md: str | None = None
    changed_lines: int | None = None
    cost_usd: float = 0.0
    duration_s: float = 0.0
    models: dict[str, str] = {}


def _error(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {status: {"model": ErrorBody} for status in statuses}


def load_samples(path: Path = SAMPLES_FILE) -> list[SampleTask]:
    """Load the curated samples (``[[samples]]`` tables)."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [SampleTask.model_validate(item) for item in data.get("samples", [])]


def client_ip(request: Request) -> str:
    """Return the visitor's IP, preferring the proxy's ``X-Forwarded-For`` header."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _with_keepalive(
    events: AsyncIterator[TraceEvent], interval: float
) -> AsyncIterator[TraceEvent | None]:
    """Yield events, and ``None`` whenever ``interval`` seconds pass without one."""
    queue: asyncio.Queue[TraceEvent | None] = asyncio.Queue()
    done = asyncio.Event()

    async def pump() -> None:
        try:
            async for event in events:
                queue.put_nowait(event)
        finally:
            done.set()
            queue.put_nowait(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), interval)
            except TimeoutError:
                yield None
                continue
            if item is None and done.is_set():
                return
            yield item
    finally:
        task.cancel()


def event_stream(events: AsyncIterator[TraceEvent]) -> StreamingResponse:
    """Wrap trace events as a Server-Sent Events response."""

    async def body() -> AsyncIterator[str]:
        async for event in _with_keepalive(events, KEEPALIVE_S):
            if event is None:
                yield ": keep-alive\n\n"
            else:
                data = event.model_dump_json()
                yield f"id: {event.seq}\nevent: {event.type.value}\ndata: {data}\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def create_app(
    *,
    settings: Settings | None = None,
    manager: RunManager | None = None,
    replays_dir: Path = Path("replays"),
) -> FastAPI:
    """Create the demo app.

    Args:
        settings: Settings for a new manager (read from the environment when omitted).
        manager: A prepared manager (tests inject one with fakes).
        replays_dir: Where the recorded replays live, for a new manager.

    Raises:
        ConfigError: If the settings are dev-only and ``FIXPROOF_ALLOW_DEV`` is not set.
    """
    if manager is None:
        settings = settings or load_settings()
        assert_demo_safe(settings)
        manager = RunManager(settings, samples=load_samples(), replays_dir=replays_dir)
    else:
        assert_demo_safe(manager.settings)
    runs = manager

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await runs.shutdown()

    app = FastAPI(
        title="FixProof demo API",
        version=__version__,
        description="Fix bugs in public Python repositories, with proof (judge demo).",
        lifespan=lifespan,
    )

    @app.exception_handler(DemoError)
    async def demo_error(request: Request, exc: DemoError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.get("/api/health", operation_id="getHealth", response_model=Health)
    async def get_health() -> dict[str, Any]:
        return runs.health()

    @app.get("/api/samples", operation_id="listSamples", response_model=list[SampleOut])
    async def list_samples() -> list[SampleOut]:
        return [
            SampleOut(
                id=sample.id,
                title=sample.title,
                repo_url=sample.repo_url,
                ref=sample.ref,
                task=TaskInput(kind=sample.task.kind, value=sample.task.value),
                expected_minutes=sample.expected_minutes,
            )
            for sample in runs.samples()
        ]

    @app.post(
        "/api/runs",
        operation_id="createRun",
        status_code=202,
        response_model=RunCreated,
        responses=_error(400, 429, 503),
    )
    async def create_run(payload: RunCreate, request: Request) -> RunCreated:
        return await runs.create(payload, client_ip(request))

    @app.get(
        "/api/runs/{run_id}",
        operation_id="getRun",
        response_model=RunView,
        responses=_error(404),
    )
    async def get_run(run_id: str) -> dict[str, Any]:
        view = runs.view(run_id)
        if view is None:
            raise DemoError(404, "not_found", f"Unknown run {run_id}.")
        return view

    @app.get(
        "/api/runs/{run_id}/events",
        operation_id="streamRunEvents",
        response_class=StreamingResponse,
        responses={200: _EVENT_STREAM, **_error(404)},
    )
    async def stream_run_events(
        run_id: str, last_event_id: Annotated[str | None, Header()] = None
    ) -> StreamingResponse:
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
        return event_stream(runs.events(run_id, after=after))

    @app.post(
        "/api/runs/{run_id}/stop",
        operation_id="stopRun",
        status_code=202,
        responses=_error(403, 404, 409),
    )
    async def stop_run(
        run_id: str, x_run_token: Annotated[str | None, Header()] = None
    ) -> dict[str, str]:
        runs.stop(run_id, x_run_token or "")
        return {"run_id": run_id, "status": "stopping"}

    @app.get(
        "/api/runs/{run_id}/patch",
        operation_id="downloadPatch",
        response_class=FileResponse,
        responses={
            200: {"content": {"text/x-diff": {"schema": {"type": "string"}}}},
            **_error(404),
        },
    )
    async def download_patch(run_id: str) -> FileResponse:
        path = runs.patch_path(run_id)
        if path is None:
            raise DemoError(404, "not_found", "No patch for this run.")
        return FileResponse(path, media_type="text/x-diff", filename=f"{run_id}.diff")

    @app.get("/api/replays", operation_id="listReplays", response_model=list[ReplayEntry])
    async def list_replays() -> list[ReplayEntry]:
        return runs.replays()

    @app.get(
        "/api/replays/{name}/events",
        operation_id="streamReplay",
        response_class=StreamingResponse,
        responses={200: _EVENT_STREAM, **_error(404)},
    )
    async def stream_replay(
        name: str, speed: Annotated[float, Query(ge=1, le=20)] = 4.0
    ) -> StreamingResponse:
        path = runs.replay_path(name)
        if path is None:
            raise DemoError(404, "not_found", f"Unknown replay {name!r}.")
        return event_stream(replay_trace(path, speed))

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
