from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from fixproof.config import Settings
from fixproof.events import EventType
from fixproof.llm.client import ModelUnavailableError, TokenFactoryClient
from fixproof.models import ModelRole

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        nebius_api_key="test-key-123456",
        nebius_base_url=BASE_URL,
        temperature=0.25,
        top_p=0.9,
        max_tokens=2048,
    )


def completion(
    model: str, message: dict[str, Any], prompt: int = 1000, completion_tokens: int = 200
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1760000000,
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt + completion_tokens,
        },
    }


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict[str, Any]]] = []
        self.requests: list[dict[str, Any]] = []

    def __call__(self, type: EventType, data: dict[str, Any]) -> None:
        self.events.append((type, data))


def make_client(handler: Any, recorder: Recorder) -> TokenFactoryClient:
    def wrapped(request: httpx2.Request) -> httpx2.Response:
        if request.content:
            recorder.requests.append(json.loads(request.content))
        response: httpx2.Response = handler(request)
        return response

    openai_client = AsyncOpenAI(
        base_url=BASE_URL,
        api_key="test-key-123456",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(wrapped)),
    )
    return TokenFactoryClient(settings(), on_event=recorder, openai_client=openai_client)


async def test_tool_call_reply_cost_and_sampling_event() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": json.dumps({"path": "a.py"})},
                }
            ],
            "reasoning_content": "The bug is probably in a.py.",
        }
        return httpx2.Response(200, json=completion(body["model"], message))

    recorder = Recorder()
    client = make_client(handler, recorder)
    tools = [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    ]
    reply = await client.complete(
        ModelRole.WORKER, [{"role": "user", "content": "hi"}], tools=tools
    )

    assert reply.model == "nvidia/nemotron-3-super-120b-a12b"
    assert reply.fallback_from is None
    assert [c.name for c in reply.tool_calls] == ["read_file"]
    assert reply.tool_calls[0].args == {"path": "a.py"}
    assert reply.reasoning == "The bug is probably in a.py."
    # Super: $0.30 in / $0.90 out per 1M tokens
    assert reply.cost_usd == pytest.approx((1000 * 0.30 + 200 * 0.90) / 1_000_000)
    assert reply.message["tool_calls"][0]["id"] == "call_1"

    sent = recorder.requests[0]
    assert sent["temperature"] == 0.25 and sent["top_p"] == 0.9 and sent["max_tokens"] == 2048
    assert sent["tool_choice"] == "auto"

    model_calls = [d for t, d in recorder.events if t is EventType.MODEL_CALL]
    assert len(model_calls) == 1
    event = model_calls[0]
    assert event["temperature"] == 0.25 and event["top_p"] == 0.9 and event["max_tokens"] == 2048
    assert event["role"] == "worker" and event["has_reasoning"] is True
    assert any(t is EventType.REASONING for t, _ in recorder.events)


async def test_planner_falls_back_on_503() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if body["model"] == "nvidia/Nemotron-3-Ultra-550b-a55b":
            return httpx2.Response(503, json={"error": {"message": "overloaded"}})
        return httpx2.Response(
            200, json=completion(body["model"], {"role": "assistant", "content": "plan"})
        )

    recorder = Recorder()
    reply = await make_client(handler, recorder).complete(
        ModelRole.PLANNER, [{"role": "user", "content": "x"}]
    )
    assert reply.model == "nvidia/nemotron-3-super-120b-a12b"
    assert reply.fallback_from == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert reply.content == "plan"
    [event] = [d for t, d in recorder.events if t is EventType.MODEL_CALL]
    assert event["fallback_from"] == "nvidia/Nemotron-3-Ultra-550b-a55b"


async def test_all_models_unavailable_raises() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"error": {"message": "down"}})

    with pytest.raises(ModelUnavailableError):
        await make_client(handler, Recorder()).complete(
            ModelRole.WORKER, [{"role": "user", "content": "x"}]
        )


async def test_bad_request_is_not_retried_on_other_models() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(json.loads(request.content)["model"])
        return httpx2.Response(400, json={"error": {"message": "invalid tools"}})

    with pytest.raises(Exception, match="invalid tools"):
        await make_client(handler, Recorder()).complete(
            ModelRole.WORKER, [{"role": "user", "content": "x"}]
        )
    assert len(calls) == 1


async def test_list_models() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/models")
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "nvidia/nemotron-3-super-120b-a12b",
                        "object": "model",
                        "created": 0,
                        "owned_by": "nvidia",
                    },
                    {
                        "id": "nvidia/Nemotron-3-Ultra-550b-a55b",
                        "object": "model",
                        "created": 0,
                        "owned_by": "nvidia",
                    },
                ],
            },
        )

    models = await make_client(handler, Recorder()).list_models()
    assert models == ["nvidia/nemotron-3-super-120b-a12b", "nvidia/Nemotron-3-Ultra-550b-a55b"]


async def test_malformed_content_tool_call_is_reported_not_raised() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        message = {
            "role": "assistant",
            "content": '<tool_call>{"name": "read_file", "arguments": {</tool_call>',
        }
        return httpx2.Response(200, json=completion(body["model"], message))

    reply = await make_client(handler, Recorder()).complete(
        ModelRole.WORKER, [{"role": "user", "content": "x"}]
    )
    assert reply.tool_calls == []
    assert reply.parse_error is not None
