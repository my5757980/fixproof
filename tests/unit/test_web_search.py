"""The optional Tavily web search (FR-022, research.md R12): off by default, short queries only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from fixproof.events import EventBus
from fixproof.llm.toolcall import ToolCall
from fixproof.sandbox.pytest_results import TestRunner
from fixproof.tools.handlers import ToolContext, ToolPhase
from fixproof.tools.registry import build_registry, web_search_enabled
from fixproof.tools.tavily import TAVILY_SEARCH_URL, TavilySearch
from fixproof.tools.toolbox import ToolBox
from fixproof.wiring import web_search_backend
from tests.fakes.fake_executor import FakeExecutor
from tests.fakes.settings import make_settings

KEY = "tvly-test-key-123456"
RESULTS = {
    "query": "pytest raises match",
    "results": [
        {
            "title": f"Result {i}",
            "url": f"https://example.com/{i}",
            "content": f"snippet {i} " + "x" * 2000,
            "score": 0.9,
            "raw_content": "<html>full page</html>",
        }
        for i in range(7)
    ],
    "response_time": 0.5,
}


class Recorder:
    """An ``httpx.MockTransport`` handler that records requests and returns a fixed reply."""

    def __init__(self, status: int = 200, payload: Any = RESULTS) -> None:
        self.status, self.payload = status, payload
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload)


def search_with(recorder: Recorder, secrets: tuple[str, ...] = ()) -> TavilySearch:
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    return TavilySearch(KEY, secrets=(KEY, *secrets), http=http)


def test_the_backend_exists_only_with_the_flag_and_a_key() -> None:
    assert web_search_backend(make_settings()) is None
    assert web_search_backend(make_settings(web_search=True)) is None
    assert web_search_backend(make_settings(tavily_api_key=KEY)) is None
    assert not web_search_enabled(make_settings(web_search=True, tavily_api_key=""))
    backend = web_search_backend(make_settings(web_search=True, tavily_api_key=KEY))
    assert isinstance(backend, TavilySearch)


async def test_the_request_holds_only_a_short_query() -> None:
    recorder = Recorder()
    search = search_with(recorder)
    await search("  pytest   raises\nmatch " + "y" * 400)
    await search.aclose()
    [request] = recorder.requests
    assert request.method == "POST" and str(request.url) == TAVILY_SEARCH_URL
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert set(body) == {"query", "max_results", "search_depth"}
    assert body["max_results"] == 5 and body["search_depth"] == "basic"
    assert body["query"].startswith("pytest raises match y") and len(body["query"]) <= 200


async def test_results_are_mapped_to_title_url_and_snippet() -> None:
    search = search_with(Recorder())
    results = await search("pytest raises match")
    await search.aclose()
    assert len(results) == 5
    assert all(set(r) == {"title", "url", "snippet"} for r in results)
    assert results[0]["title"] == "Result 0" and results[0]["url"] == "https://example.com/0"
    assert results[0]["snippet"].startswith("snippet 0") and len(results[0]["snippet"]) <= 500


async def test_a_query_with_a_secret_is_never_sent() -> None:
    recorder = Recorder()
    search = search_with(recorder, secrets=("ghp_private_value_123",))
    for query in ("why ghp_private_value_123 fails", "error token=abcdef123 in config"):
        with pytest.raises(ValueError, match="secret"):
            await search(query)
    await search.aclose()
    assert recorder.requests == []


@pytest.mark.parametrize(
    "recorder",
    [Recorder(status=500, payload={"detail": "boom"}), Recorder(payload={"results": "nope"})],
)
async def test_failures_reach_the_model_as_search_failed(recorder: Recorder) -> None:
    executor = FakeExecutor({"pkg/core.py": "x = 1\n"})
    snapshot = await executor.prepare_repo(Path("no-tarball.tgz"), "python:3.12")
    bus = EventBus("run-20261014-000000-abcdef")
    search = search_with(recorder)
    context = ToolContext(
        executor=executor,
        snapshot=snapshot,
        phase=ToolPhase.FIX,
        tests=TestRunner(executor, timeout_s=60, bus=bus),
        web_search=search,
    )
    box = ToolBox(build_registry(web_search=True), context, bus)
    result = await box.call(ToolCall(id="call-1", name="web_search", args={"query": "pytest"}))
    await search.aclose()
    assert json.loads(result.content)["error"] == "search_failed"
