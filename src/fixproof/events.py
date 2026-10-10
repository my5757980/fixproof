"""Trace events and the per-run event bus (contracts/trace-events.md, Constitution IV).

Every step of a run is published as a ``TraceEvent`` on the run's ``EventBus``. The same events
feed the CLI renderer, the web demo's Server-Sent Events, and the JSONL trace, so the record and
what users see can never diverge.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fixproof.models import utc_now


class EventType(StrEnum):
    """Event types, exactly as listed in the trace-events contract."""

    RUN_STARTED = "run_started"
    PHASE_CHANGED = "phase_changed"
    REPO_FETCHED = "repo_fetched"
    SANDBOX_OP = "sandbox_op"
    SNAPSHOT = "snapshot"
    INSTALL_RESULT = "install_result"
    TEST_RUN = "test_run"
    PLAN = "plan"
    HYPOTHESES = "hypotheses"
    MODEL_CALL = "model_call"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REPRO_STATUS = "repro_status"
    VERIFICATION = "verification"
    ATTEMPT_FINISHED = "attempt_finished"
    BUDGET = "budget"
    ERROR = "error"
    REPORT = "report"
    RUN_FINISHED = "run_finished"


class TraceEvent(BaseModel):
    """One immutable trace record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(ge=1)
    ts: datetime
    run_id: str
    attempt_id: str | None = None
    type: EventType
    replay: bool = False
    data: dict[str, Any] = Field(default_factory=dict)

    def as_replay(self) -> TraceEvent:
        """Return a copy of this event marked as a replay (FR-018)."""
        return self.model_copy(update={"replay": True})


Listener = Callable[[TraceEvent], None]
Redact = Callable[[Any], Any]


class EventBus:
    """Fan-out of one run's events to history, synchronous listeners, and async subscribers.

    ``publish`` never blocks: listeners are called inline and subscriber queues are unbounded.
    Subscribers first receive the full history, then live events until the bus is closed.

    Args:
        run_id: The run these events belong to.
        redact: Optional function applied to event data before it is stored or published.
        clock: Source of event timestamps (UTC); injectable for tests.
    """

    def __init__(
        self,
        run_id: str,
        *,
        redact: Redact | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.run_id = run_id
        self._redact = redact
        self._clock = clock
        self._history: list[TraceEvent] = []
        self._listeners: list[Listener] = []
        self._queues: list[asyncio.Queue[TraceEvent | None]] = []
        self._closed = False

    @property
    def history(self) -> tuple[TraceEvent, ...]:
        """All events published so far, in ``seq`` order."""
        return tuple(self._history)

    @property
    def closed(self) -> bool:
        """Whether the bus has been closed (no more events will be published)."""
        return self._closed

    def add_listener(self, listener: Listener) -> None:
        """Register a synchronous listener called for every future event."""
        self._listeners.append(listener)

    def publish(
        self,
        type: EventType | str,
        data: Mapping[str, Any] | None = None,
        *,
        attempt_id: str | None = None,
    ) -> TraceEvent:
        """Publish a new event with the next sequence number.

        Args:
            type: The event type.
            data: Type-specific payload; redacted before storage when a redactor is set.
            attempt_id: The attempt this event belongs to, if any.

        Returns:
            The published event.

        Raises:
            RuntimeError: If the bus is already closed.
        """
        if self._closed:
            raise RuntimeError(f"event bus for {self.run_id} is closed")
        payload: dict[str, Any] = dict(data or {})
        if self._redact is not None:
            payload = self._redact(payload)
        event = TraceEvent(
            seq=len(self._history) + 1,
            ts=self._clock(),
            run_id=self.run_id,
            attempt_id=attempt_id,
            type=EventType(type),
            data=payload,
        )
        self._history.append(event)
        for listener in list(self._listeners):
            listener(event)
        for queue in list(self._queues):
            queue.put_nowait(event)
        return event

    async def subscribe(self) -> AsyncIterator[TraceEvent]:
        """Yield every past event, then live events until the bus is closed."""
        queue: asyncio.Queue[TraceEvent | None] = asyncio.Queue()
        backlog = list(self._history)
        if not self._closed:
            self._queues.append(queue)
        try:
            for event in backlog:
                yield event
            if self._closed and queue.empty():
                return
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            if queue in self._queues:
                self._queues.remove(queue)

    def close(self) -> None:
        """Close the bus; subscribers finish after draining pending events."""
        if self._closed:
            return
        self._closed = True
        for queue in list(self._queues):
            queue.put_nowait(None)
