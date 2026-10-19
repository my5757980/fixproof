"""The demo HTTP API (contracts/openapi.yaml) with fakes, through httpx's ASGI transport."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from fixproof.web.app import create_app
from fixproof.web.runs import RunManager
from tests.fakes.calc_repo import CALC_FILES, ISSUE_URL, REPO_URL
from tests.fakes.fake_github import FakeGitHub
from tests.fakes.settings import make_settings
from tests.fakes.web import SAMPLE, Fakes, make_manager, wait_until, write_replay


@dataclass
class Demo:
    client: httpx.AsyncClient
    manager: RunManager
    fakes: Fakes
    tmp_path: Path

    async def start(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.client.post("/api/runs", json=body or {"sample_id": SAMPLE.id})
        assert response.status_code == 202, response.text
        return dict(response.json())

    async def events(self, url: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
        async with self.client.stream("GET", url, headers=headers) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            messages: list[dict[str, str]] = []
            current: dict[str, str] = {}
            async for line in response.aiter_lines():
                if not line:
                    if current:
                        messages.append(current)
                    current = {}
                elif not line.startswith(":"):
                    field, _, value = line.partition(": ")
                    current[field] = value
        return [
            {"id": int(m["id"]), "event": m["event"], "data": json.loads(m["data"])}
            for m in messages
        ]


MakeDemo = Callable[..., Any]


@pytest.fixture
async def make_demo(tmp_path: Path) -> AsyncIterator[MakeDemo]:
    created: list[Demo] = []

    async def build(
        *, github: FakeGitHub | None = None, gated: bool = False, **overrides: Any
    ) -> Demo:
        settings = make_settings(state_dir=tmp_path / "state", **overrides)
        fakes = Fakes(github, gated=gated)
        manager, _ = make_manager(tmp_path, fakes=fakes, settings=settings)
        transport = httpx.ASGITransport(
            app=create_app(manager=manager), client=("203.0.113.9", 4567)
        )
        client = httpx.AsyncClient(transport=transport, base_url="http://demo")
        demo = Demo(client, manager, fakes, tmp_path)
        created.append(demo)
        return demo

    yield build
    for demo in created:
        await demo.manager.shutdown()
        await demo.client.aclose()


async def test_a_run_streams_ordered_events_until_run_finished(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    created = await demo.start()
    assert set(created) >= {"run_id", "status", "control_token", "events_url", "queue_position"}
    assert created["status"] in ("queued", "setting_up")
    assert 32 <= len(created["control_token"]) <= 64

    events = await demo.events(created["events_url"])
    assert [e["id"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["event"] == "run_started" and events[-1]["event"] == "run_finished"
    assert all(e["event"] == e["data"]["type"] and e["data"]["replay"] is False for e in events)
    assert events[-1]["data"]["data"]["label"] == "verified"


async def test_the_initial_plan_arrives_before_setup_finishes(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    events = await demo.events((await demo.start())["events_url"])
    order = [e["event"] for e in events]
    plan_index = next(
        i
        for i, e in enumerate(events)
        if e["event"] == "plan" and e["data"]["data"]["stage"] == "initial"
    )
    assert plan_index < order.index("install_result")


async def test_last_event_id_resumes_the_stream(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    created = await demo.start()
    everything = await demo.events(created["events_url"])
    resumed = await demo.events(created["events_url"], headers={"Last-Event-ID": "5"})
    assert resumed[0]["id"] == 6 and len(resumed) == len(everything) - 5


async def test_stop_requires_the_runs_control_token(make_demo: MakeDemo) -> None:
    demo = await make_demo(gated=True)
    created = await demo.start()
    await wait_until(demo.fakes.started.is_set)
    stop_url = f"/api/runs/{created['run_id']}/stop"

    missing = await demo.client.post(stop_url)
    wrong = await demo.client.post(stop_url, headers={"X-Run-Token": "w" * 43})
    assert missing.status_code == wrong.status_code == 403
    assert wrong.json()["error"] == "forbidden"
    running = await demo.client.get(f"/api/runs/{created['run_id']}")
    assert running.json()["status"] != "done"

    stopped = await demo.client.post(stop_url, headers={"X-Run-Token": created["control_token"]})
    assert stopped.status_code == 202
    events = await demo.events(created["events_url"])
    assert events[-1]["data"]["data"]["stop_reason"] == "user_stop"
    again = await demo.client.post(stop_url, headers={"X-Run-Token": created["control_token"]})
    assert again.status_code == 409 and again.json()["error"] == "already_finished"


async def test_the_patch_downloads_as_a_diff(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    created = await demo.start()
    await demo.events(created["events_url"])
    patch = await demo.client.get(f"/api/runs/{created['run_id']}/patch")
    assert patch.status_code == 200
    assert patch.headers["content-type"].startswith("text/x-diff")
    assert "+    return a + b" in patch.text
    missing = await demo.client.get("/api/runs/run-20261020-000000-abcdef/patch")
    assert missing.status_code == 404


async def test_the_run_view(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    created = await demo.start()
    await demo.events(created["events_url"])
    view = (await demo.client.get(f"/api/runs/{created['run_id']}")).json()
    assert view["status"] == "done" and view["label"] == "verified"
    assert view["stop_reason"] == "completed" and view["replay"] is False
    assert view["repo_url"] == REPO_URL and view["task"] == {"kind": "issue", "value": ISSUE_URL}
    assert view["plan"] and view["summary"] and view["changed_lines"] > 0
    for unknown in ("run-20261020-000000-abcdef", "not-a-run-id"):
        response = await demo.client.get(f"/api/runs/{unknown}")
        assert response.status_code == 404 and response.json()["error"] == "not_found"


GITLAB = "https://gitlab.com/acme/calc"
BUG = {"kind": "description", "value": "x"}
OTHER_ISSUE = {"kind": "issue", "value": "https://github.com/other/repo/issues/1"}


@pytest.mark.parametrize(
    ("body", "github", "code"),
    [
        ({"repo_url": GITLAB, "task": {"kind": "bug_text", "value": "x"}}, None, None),
        ({"repo_url": GITLAB, "task": BUG}, None, "invalid_repo"),
        ({"repo_url": REPO_URL, "task": BUG}, FakeGitHub(CALC_FILES, private=True), "private_repo"),
        (
            {"repo_url": REPO_URL, "task": BUG},
            FakeGitHub(CALC_FILES, size_kb=61440),
            "repo_too_large",
        ),
        ({"repo_url": REPO_URL, "task": OTHER_ISSUE}, None, "invalid_task"),
        ({"sample_id": SAMPLE.id, "repo_url": REPO_URL}, None, "invalid_task"),
    ],
)
async def test_invalid_requests_are_rejected(
    make_demo: MakeDemo, body: dict[str, Any], github: FakeGitHub | None, code: str | None
) -> None:
    demo = await make_demo(github=github)
    response = await demo.client.post("/api/runs", json=body)
    if code is None:
        assert response.status_code == 422
    else:
        assert response.status_code == 400 and response.json()["error"] == code
        assert response.json()["message"]
    assert demo.manager.runs() == []


async def test_the_visitor_limit_suggests_a_replay(make_demo: MakeDemo, tmp_path: Path) -> None:
    recorder = await make_demo()
    recording = await recorder.start()
    await recorder.events(recording["events_url"])
    write_replay(
        tmp_path / "replays",
        "calc-verified",
        list(recorder.manager.events_history(recording["run_id"])),
        "calc: a verified fix",
    )
    demo = await make_demo(demo_runs_per_visitor=1)
    await demo.start()
    limited = await demo.client.post("/api/runs", json={"sample_id": SAMPLE.id})
    assert limited.status_code == 429
    assert limited.json()["error"] == "visitor_limit"
    assert limited.json()["replay_suggestion"] == "calc-verified"


async def test_the_daily_cap_pauses_live_runs(make_demo: MakeDemo) -> None:
    demo = await make_demo(demo_daily_cap_usd=0.5)
    response = await demo.client.post("/api/runs", json={"sample_id": SAMPLE.id})
    assert response.status_code == 503 and response.json()["error"] == "daily_limit"
    health = (await demo.client.get("/api/health")).json()
    assert health["live_runs_available"] is False and health["status"] == "degraded"


async def test_health_reports_availability_budget_and_models(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    health = (await demo.client.get("/api/health")).json()
    assert health["status"] == "ok" and health["live_runs_available"] is True
    assert health["executor"] == "contree" and health["budget_remaining_usd"] == 2.0
    assert set(health["models"]) == {"planner", "worker", "condenser"}
    assert health["active_runs"] == 0 and health["queue_length"] == 0


async def test_health_labels_a_setup_that_is_not_the_hackathon_platform(
    make_demo: MakeDemo,
) -> None:
    platform = await make_demo()
    assert (await platform.client.get("/api/health")).json()["platform_note"] is None
    personal = await make_demo(provider="requesty", executor="docker", allow_dev=True)
    note = (await personal.client.get("/api/health")).json()["platform_note"]
    assert note.startswith("Not the hackathon platform")
    assert "Requesty (personal mode)" in note and "local Docker" in note


async def test_samples_are_listed(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    [sample] = (await demo.client.get("/api/samples")).json()
    assert sample["id"] == SAMPLE.id and sample["task"] == {"kind": "issue", "value": ISSUE_URL}
    assert sample["expected_minutes"] == 5 and sample["repo_url"] == REPO_URL


async def test_replays_are_listed_and_every_event_is_marked(
    make_demo: MakeDemo, tmp_path: Path
) -> None:
    recorder = await make_demo()
    recording = await recorder.start()
    await recorder.events(recording["events_url"])
    history = list(recorder.manager.events_history(recording["run_id"]))
    write_replay(tmp_path / "replays", "calc-verified", history, "calc: a verified fix")

    demo = await make_demo()
    [entry] = (await demo.client.get("/api/replays")).json()
    assert entry["name"] == "calc-verified" and entry["label"] == "verified"
    assert entry["recorded_at"].startswith("2026-10-11T10:00:00")
    events = await demo.events("/api/replays/calc-verified/events?speed=20")
    assert len(events) == len(history)
    assert all(e["data"]["replay"] is True for e in events)
    for name in ("missing", "..%2Fsecret"):
        assert (await demo.client.get(f"/api/replays/{name}/events")).status_code == 404


async def test_no_endpoint_applies_patches_or_opens_pull_requests(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    created = await demo.start()
    await demo.events(created["events_url"])
    app = create_app(manager=demo.manager)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not [p for p in paths if any(word in p.lower() for word in ("apply", "pull", "/pr"))]
    for suffix in ("apply", "pr", "pull-request"):
        response = await demo.client.post(f"/api/runs/{created['run_id']}/{suffix}")
        assert response.status_code in (404, 405)


async def test_the_page_and_static_files_are_served(make_demo: MakeDemo) -> None:
    demo = await make_demo()
    page = await demo.client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "FixProof" in page.text and "app.js" in page.text
    for asset in ("app.js", "style.css"):
        assert (await demo.client.get(f"/static/{asset}")).status_code == 200
