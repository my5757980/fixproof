"""RunManager: queue, visitor allowance, daily budget, control tokens, replays, run registry."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fixproof.events import EventType
from fixproof.models import OutcomeLabel, StopReason
from fixproof.trace import read_trace
from fixproof.web.runs import (
    DailyBudget,
    DemoError,
    RunCreate,
    RunManager,
    TaskInput,
    VisitorAllowance,
)
from tests.fakes.calc_repo import ISSUE_URL, REPO_URL
from tests.fakes.settings import make_settings
from tests.fakes.web import SAMPLE, Day, Fakes, make_manager, wait_until, write_replay

SAMPLE_RUN = RunCreate(sample_id=SAMPLE.id)


async def finish_all(manager: RunManager) -> None:
    await wait_until(lambda: all(r.finished for r in manager.runs()), timeout=10)


async def test_live_runs_are_limited_and_queued_in_order(tmp_path: Path) -> None:
    fakes = Fakes(gated=True)
    settings = make_settings(state_dir=tmp_path / "state", demo_max_concurrent=1)
    manager, _ = make_manager(tmp_path, fakes=fakes, settings=settings)
    first = await manager.create(SAMPLE_RUN, "10.0.0.1")
    second = await manager.create(SAMPLE_RUN, "10.0.0.2")
    third = await manager.create(SAMPLE_RUN, "10.0.0.3")
    await wait_until(fakes.started.is_set)

    assert (first.status, first.queue_position) == ("setting_up", 0)
    assert (second.status, second.queue_position) == ("queued", 0)
    assert (third.status, third.queue_position) == ("queued", 1)
    health = manager.health()
    assert health["active_runs"] == 1 and health["queue_length"] == 2

    fakes.gate.set()
    await finish_all(manager)
    labels = [manager.view(r.run_id)["label"] for r in (first, second, third)]
    assert labels == ["verified"] * 3
    await manager.shutdown()


def test_visitor_allowance_is_hashed_and_resets_daily() -> None:
    day = Day()
    allowance = VisitorAllowance(1, today=day)
    key = allowance.key("203.0.113.7")
    assert len(key) == 64 and "203.0.113.7" not in key
    assert allowance.remaining(key) == 1
    allowance.consume(key)
    assert allowance.remaining(key) == 0
    assert allowance.remaining(allowance.key("203.0.113.8")) == 1
    day.value += timedelta(days=1)
    assert allowance.remaining(key) == 1


async def test_visitor_limit_is_429_with_a_replay_suggestion(tmp_path: Path) -> None:
    settings = make_settings(state_dir=tmp_path / "state", demo_runs_per_visitor=1)
    manager, _ = make_manager(tmp_path, settings=settings)
    write_replay(tmp_path / "replays", "calc-verified", await recorded_events(tmp_path), "calc")
    await manager.create(SAMPLE_RUN, "198.51.100.4")
    with pytest.raises(DemoError) as info:
        await manager.create(SAMPLE_RUN, "198.51.100.4")
    assert (info.value.status, info.value.code) == (429, "visitor_limit")
    assert info.value.replay_suggestion == "calc-verified"
    await finish_all(manager)
    await manager.shutdown()


def test_daily_budget_persists_and_resets_daily(tmp_path: Path) -> None:
    day = Day()
    path = tmp_path / "state" / "_budget.json"
    budget = DailyBudget(path, cap_usd=2.0, today=day)
    budget.charge(0.5)
    assert json.loads(path.read_text()) == {"day": "2026-10-20", "cost_usd": 0.5, "cap_usd": 2.0}
    restarted = DailyBudget(path, cap_usd=2.0, today=day)
    assert restarted.spent_usd == 0.5 and restarted.remaining_usd == 1.5
    day.value = date(2026, 10, 21)
    assert restarted.spent_usd == 0.0


async def test_finished_runs_are_charged_with_estimated_sandbox_cost(tmp_path: Path) -> None:
    settings = make_settings(state_dir=tmp_path / "state", sandbox_cost_per_min_usd=0.01)
    manager, _ = make_manager(tmp_path, settings=settings)
    created = await manager.create(SAMPLE_RUN, "192.0.2.1")
    await finish_all(manager)
    finished = next(
        e for e in manager.events_history(created.run_id) if e.type is EventType.RUN_FINISHED
    )
    expected = finished.data["cost_usd"] + finished.data["duration_s"] / 60 * 0.01
    assert manager.budget.spent_usd == pytest.approx(expected, rel=1e-3)
    await manager.shutdown()


async def test_daily_cap_pauses_live_runs(tmp_path: Path) -> None:
    settings = make_settings(state_dir=tmp_path / "state", demo_daily_cap_usd=0.5)
    manager, _ = make_manager(tmp_path, settings=settings)
    with pytest.raises(DemoError) as info:
        await manager.create(SAMPLE_RUN, "192.0.2.2")
    assert (info.value.status, info.value.code) == (503, "daily_limit")
    health = manager.health()
    assert health["live_runs_available"] is False and "budget" in health["reason"]
    await manager.shutdown()


async def test_replay_catalog_loads_from_index(tmp_path: Path) -> None:
    events = await recorded_events(tmp_path)
    write_replay(tmp_path / "replays", "calc-verified", events, "calc: verified fix")
    manager, _ = make_manager(tmp_path)
    [entry] = manager.replays()
    assert (entry.name, entry.title, entry.label) == (
        "calc-verified",
        "calc: verified fix",
        OutcomeLabel.VERIFIED,
    )
    path = manager.replay_path("calc-verified")
    assert path is not None and read_trace(path)
    assert manager.replay_path("missing") is None and manager.replay_path("../etc") is None


async def test_stop_needs_the_control_token_and_works_once(tmp_path: Path) -> None:
    fakes = Fakes(gated=True)
    manager, _ = make_manager(tmp_path, fakes=fakes)
    created = await manager.create(SAMPLE_RUN, "192.0.2.3")
    await wait_until(fakes.started.is_set)
    for token in ("", "x" * 43):
        with pytest.raises(DemoError) as info:
            manager.stop(created.run_id, token)
        assert (info.value.status, info.value.code) == (403, "forbidden")
    manager.stop(created.run_id, created.control_token)
    with pytest.raises(DemoError) as again:
        manager.stop(created.run_id, created.control_token)
    assert (again.value.status, again.value.code) == (409, "already_finished")
    await finish_all(manager)
    assert manager.view(created.run_id)["stop_reason"] == StopReason.USER_STOP.value
    with pytest.raises(DemoError) as missing:
        manager.stop("run-20261020-000000-abcdef", created.control_token)
    assert missing.value.status == 404
    await manager.shutdown()


async def test_a_queued_run_stops_without_waiting_for_a_slot(tmp_path: Path) -> None:
    fakes = Fakes(gated=True)
    settings = make_settings(state_dir=tmp_path / "state", demo_max_concurrent=1)
    manager, _ = make_manager(tmp_path, fakes=fakes, settings=settings)
    await manager.create(SAMPLE_RUN, "192.0.2.4")
    queued = await manager.create(SAMPLE_RUN, "192.0.2.5")
    await wait_until(fakes.started.is_set)
    manager.stop(queued.run_id, queued.control_token)
    await wait_until(lambda: manager.get(queued.run_id).finished)  # type: ignore[union-attr]
    view = manager.view(queued.run_id)
    assert view["stop_reason"] == "user_stop" and view["status"] == "done"
    fakes.gate.set()
    await finish_all(manager)
    await manager.shutdown()


async def test_registry_keeps_the_newest_runs_on_disk(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path, keep_runs=2)
    ids = []
    for ip in ("192.0.2.10", "192.0.2.11", "192.0.2.12"):
        ids.append((await manager.create(SAMPLE_RUN, ip)).run_id)
        await finish_all(manager)
    state = tmp_path / "state"
    assert not (state / ids[0]).exists() and manager.get(ids[0]) is None
    assert (state / ids[1]).is_dir() and (state / ids[2]).is_dir()
    await manager.shutdown()


async def test_finished_runs_are_served_from_disk_after_a_restart(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    created = await manager.create(SAMPLE_RUN, "192.0.2.20")
    await finish_all(manager)
    await manager.shutdown()

    restarted, _ = make_manager(tmp_path)
    view = restarted.view(created.run_id)
    assert view is not None and view["label"] == "verified" and view["status"] == "done"
    assert restarted.patch_path(created.run_id) is not None
    assert [e async for e in restarted.events(created.run_id)][-1].type is EventType.RUN_FINISHED


async def test_custom_repository_requests_are_validated(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    custom = RunCreate(repo_url=REPO_URL, task=TaskInput(kind="issue", value=ISSUE_URL))
    created = await manager.create(custom, "192.0.2.30")
    await finish_all(manager)
    assert manager.view(created.run_id)["label"] == "verified"
    for bad, code in (
        (RunCreate(repo_url="https://gitlab.com/a/b", task=custom.task), "invalid_repo"),
        (RunCreate(sample_id=SAMPLE.id, repo_url=REPO_URL), "invalid_task"),
        (RunCreate(sample_id="no-such-sample"), "invalid_task"),
        (RunCreate(repo_url=REPO_URL), "invalid_task"),
    ):
        with pytest.raises(DemoError) as info:
            await manager.create(bad, "192.0.2.31")
        assert (info.value.status, info.value.code) == (400, code)
    await manager.shutdown()


async def recorded_events(tmp_path: Path) -> list:  # type: ignore[type-arg]
    """Events of one finished fake run, to use as a recorded replay."""
    manager, _ = make_manager(tmp_path / "recording")
    created = await manager.create(SAMPLE_RUN, "192.0.2.99")
    await finish_all(manager)
    events = list(manager.events_history(created.run_id))
    await manager.shutdown()
    return events
