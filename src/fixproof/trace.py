"""JSONL traces: secret redaction, writing, reading, and labeled replay (Constitution IV).

Each run writes ``<runs_dir>/<run_id>/trace.jsonl``, one JSON object per line. Secrets are
redacted before anything is written or published (FR-020).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from pathlib import Path
from typing import IO, Any

from fixproof.events import EventBus, TraceEvent

REDACTED = "[REDACTED]"
SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|token|secret)(\s*[:=]\s*)(\S+)")
_MIN_SECRET_LENGTH = 4


class Redactor:
    """Replace secret values and ``key=value``-style credentials with ``[REDACTED]``.

    Dict keys are kept as-is; only string values are rewritten. Numbers, booleans, and
    ``None`` pass through unchanged.

    Args:
        secrets: Exact secret values to remove wherever they appear.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        unique = {s for s in secrets if s and len(s) >= _MIN_SECRET_LENGTH}
        self._secrets = sorted(unique, key=len, reverse=True)

    def redact_text(self, text: str) -> str:
        """Return ``text`` with secret values and credential assignments redacted."""
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return SECRET_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)

    def __call__(self, value: Any) -> Any:
        """Recursively redact strings inside ``value`` and return a new structure."""
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {key: self(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self(item) for item in value)
        return value


class TraceWriter:
    """Append each event as one JSON line to a trace file.

    Use it as a listener on an ``EventBus`` (see ``attach``). The file is created on the first
    event, together with any missing parent directories.

    Args:
        path: Destination ``trace.jsonl`` file.
        redactor: Optional extra redaction applied before writing.
    """

    def __init__(self, path: Path, *, redactor: Redactor | None = None) -> None:
        self.path = path
        self._redactor = redactor
        self._file: IO[str] | None = None

    @classmethod
    def for_run(
        cls, runs_dir: Path, run_id: str, *, redactor: Redactor | None = None
    ) -> TraceWriter:
        """Create a writer for ``<runs_dir>/<run_id>/trace.jsonl``."""
        return cls(runs_dir / run_id / "trace.jsonl", redactor=redactor)

    def attach(self, bus: EventBus) -> TraceWriter:
        """Register this writer as a listener on ``bus`` and return it."""
        bus.add_listener(self)
        return self

    def __call__(self, event: TraceEvent) -> None:
        """Write ``event`` as one JSON line and flush it to disk."""
        if self._redactor is not None:
            event = event.model_copy(update={"data": self._redactor(event.data)})
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a", encoding="utf-8")
        self._file.write(event.model_dump_json() + "\n")
        self._file.flush()

    def close(self) -> None:
        """Close the underlying file, if it was opened."""
        if self._file is not None:
            self._file.close()
            self._file = None


def read_trace(path: Path) -> list[TraceEvent]:
    """Read every event from a JSONL trace file, in file order.

    Args:
        path: Path to a ``trace.jsonl`` file.

    Returns:
        The parsed events.
    """
    events: list[TraceEvent] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                events.append(TraceEvent.model_validate_json(line))
    return events


async def replay(
    path: Path,
    speed: float = 4.0,
    *,
    max_gap_s: float = 3.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[TraceEvent]:
    """Re-emit a recorded run in ``seq`` order, marked ``replay=True`` (FR-018).

    The original gaps between events are divided by ``speed`` and capped at ``max_gap_s``.

    Args:
        path: Recorded ``trace.jsonl`` file.
        speed: Playback speed multiplier; must be positive.
        max_gap_s: Longest pause between two events, in seconds.
        sleep: Awaitable sleep function; injectable for tests.

    Yields:
        Each recorded event as a replay.

    Raises:
        ValueError: If ``speed`` is not positive.
    """
    if speed <= 0:
        raise ValueError("speed must be positive")
    events = sorted(read_trace(path), key=lambda event: event.seq)
    previous: TraceEvent | None = None
    for event in events:
        if previous is not None:
            gap = (event.ts - previous.ts).total_seconds() / speed
            if gap > 0:
                await sleep(min(gap, max_gap_s))
        previous = event
        yield event.as_replay()
