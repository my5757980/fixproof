from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fixproof.events import EventBus, EventType, TraceEvent
from fixproof.trace import REDACTED, Redactor, TraceWriter, read_trace, replay

RUN_ID = "run-20261012-094100-a1b2c3"


def test_seq_strictly_increasing() -> None:
    bus = EventBus(RUN_ID)
    events = [bus.publish(EventType.PHASE_CHANGED, {"from": "a", "to": "b"}) for _ in range(5)]
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert all(e.run_id == RUN_ID and e.ts.tzinfo is not None for e in events)


async def test_late_subscriber_gets_history_then_live() -> None:
    bus = EventBus(RUN_ID)
    bus.publish(EventType.RUN_STARTED, {"repo_url": "https://github.com/a/b"})
    bus.publish(EventType.PHASE_CHANGED, {"from": "queued", "to": "setting_up"})

    received: list[TraceEvent] = []

    async def consume() -> None:
        async for event in bus.subscribe():
            received.append(event)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber drain history
    bus.publish(EventType.RUN_FINISHED, {"label": "verified"})
    bus.close()
    await asyncio.wait_for(task, timeout=2)

    assert [e.seq for e in received] == [1, 2, 3]
    assert received[-1].type is EventType.RUN_FINISHED


async def test_subscribe_after_close_yields_history_only() -> None:
    bus = EventBus(RUN_ID)
    bus.publish(EventType.RUN_FINISHED, {})
    bus.close()
    events = [event async for event in bus.subscribe()]
    assert len(events) == 1


def test_publish_after_close_fails() -> None:
    bus = EventBus(RUN_ID)
    bus.close()
    with pytest.raises(RuntimeError):
        bus.publish(EventType.ERROR, {})


def test_redactor_replaces_secret_values_and_key_value_pairs() -> None:
    redact = Redactor(["sk-live-SECRET-123"])
    data = {
        "command": "curl -H 'Authorization: Bearer sk-live-SECRET-123' https://x",
        "nested": [{"env": "api_key=abcd1234 other=1"}, "TOKEN: zzz999"],
        "count": 3,
        "max_tokens": 4096,
    }
    out = redact(data)
    flat = repr(out)
    assert "sk-live-SECRET-123" not in flat
    assert "abcd1234" not in flat
    assert "zzz999" not in flat
    assert REDACTED in out["command"]
    assert out["count"] == 3
    assert out["max_tokens"] == 4096  # keys are never redacted, numbers untouched


def test_bus_redacts_before_publishing() -> None:
    bus = EventBus(RUN_ID, redact=Redactor(["my-secret-value"]))
    event = bus.publish(EventType.SANDBOX_OP, {"command": "echo my-secret-value"})
    assert "my-secret-value" not in event.data["command"]


def test_jsonl_round_trip(tmp_path: Path) -> None:
    bus = EventBus(RUN_ID)
    writer = TraceWriter.for_run(tmp_path, RUN_ID).attach(bus)
    bus.publish(EventType.PLAN, {"stage": "initial", "steps": ["a", "b"], "understanding": "x"})
    bus.publish(EventType.RUN_FINISHED, {"label": "verified"})
    writer.close()

    path = tmp_path / RUN_ID / "trace.jsonl"
    assert path.exists()
    events = read_trace(path)
    assert [e.type for e in events] == [EventType.PLAN, EventType.RUN_FINISHED]
    assert events[0].data["steps"] == ["a", "b"]


async def test_replay_orders_by_seq_and_marks_replay(tmp_path: Path) -> None:
    start = datetime(2026, 10, 12, 9, 41, tzinfo=UTC)
    path = tmp_path / "trace.jsonl"
    events = [
        TraceEvent(seq=2, ts=start + timedelta(seconds=4), run_id=RUN_ID, type=EventType.PLAN),
        TraceEvent(seq=1, ts=start, run_id=RUN_ID, type=EventType.RUN_STARTED),
        TraceEvent(
            seq=3, ts=start + timedelta(seconds=8), run_id=RUN_ID, type=EventType.RUN_FINISHED
        ),
    ]
    path.write_text("".join(e.model_dump_json() + "\n" for e in events), encoding="utf-8")

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    out = [e async for e in replay(path, speed=4.0, sleep=fake_sleep)]
    assert [e.seq for e in out] == [1, 2, 3]
    assert all(e.replay for e in out)
    assert slept == [pytest.approx(1.0), pytest.approx(1.0)]
