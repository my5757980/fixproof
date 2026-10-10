"""Model access through Nebius Token Factory's OpenAI-compatible API (research.md R1, R2).

``TokenFactoryClient`` maps a role (planner, worker, condenser) to its configured NVIDIA
Nemotron model and sends explicit sampling parameters. If a model is unavailable (5xx, 404,
rate-limited after retries, or unreachable), it falls back along the role's chain of NVIDIA
models on Nebius. It never falls back to another provider (Constitution I).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai
from openai import AsyncOpenAI

from fixproof.config import Settings
from fixproof.events import EventType
from fixproof.llm.pricing import PriceTable
from fixproof.llm.toolcall import ToolCall, ToolCallParseError, extract_tool_calls
from fixproof.models import ModelRole

_REASONING_LIMIT = 4000

# Errors after which the next model in the role's chain is tried.
_FALLBACK_ERRORS: tuple[type[Exception], ...] = (
    openai.InternalServerError,
    openai.NotFoundError,
    openai.RateLimitError,
    openai.APIConnectionError,
)

EventCallback = Callable[[EventType, dict[str, Any]], None]


@dataclass(frozen=True)
class ModelReply:
    """One model response, normalized for the agent loop.

    Attributes:
        content: Assistant text, if any.
        tool_calls: Requested tool calls (native or parsed from content).
        reasoning: Reasoning text returned by the model, if any (verbose view only).
        prompt_tokens: Billed input tokens.
        completion_tokens: Billed output tokens.
        cost_usd: Cost of this call in USD.
        model: The model that actually served the call.
        fallback_from: The role's primary model, when a fallback model served the call.
        elapsed_s: Wall-clock duration of the successful request.
        message: The assistant message to append to the conversation.
        parse_error: Why a tool call written in the content could not be parsed, if so.
    """

    content: str | None
    tool_calls: list[ToolCall]
    reasoning: str | None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    model: str
    fallback_from: str | None = None
    elapsed_s: float = 0.0
    message: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None


class ModelClient(Protocol):
    """Interface of the model client used by the agent loop (faked in tests)."""

    async def complete(
        self,
        role: ModelRole,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ModelReply:
        """Send one chat request for ``role`` and return the normalized reply."""
        ...

    async def list_models(self) -> list[str]:
        """Return the model IDs available on the endpoint."""
        ...


class ModelUnavailableError(RuntimeError):
    """Raised when every model in a role's fallback chain failed.

    Args:
        role: The role that was requested.
        failures: One ``"model: error"`` description per attempted model.
    """

    def __init__(self, role: ModelRole, failures: Sequence[str]) -> None:
        super().__init__(
            f"No {role.value} model is available on Nebius Token Factory: " + "; ".join(failures)
        )
        self.role = role
        self.failures = list(failures)


class TokenFactoryClient:
    """Chat-completions client for NVIDIA Nemotron models on Nebius Token Factory.

    Args:
        settings: Configuration with the endpoint, key, model roles, sampling, and prices.
        on_event: Callback receiving ``model_call``, ``reasoning``, and fallback ``error`` events.
        openai_client: Pre-built ``AsyncOpenAI`` client (tests inject a mock transport here).
        max_retries: SDK-level retries with backoff before falling back to the next model.
        timeout_s: Per-request timeout in seconds.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        on_event: EventCallback | None = None,
        openai_client: AsyncOpenAI | None = None,
        max_retries: int = 2,
        timeout_s: float = 120.0,
    ) -> None:
        self._settings = settings
        self._on_event = on_event
        self._prices = PriceTable(settings.price_table())
        self._client = openai_client or AsyncOpenAI(
            base_url=settings.nebius_base_url,
            api_key=settings.require_api_key(),
            max_retries=max_retries,
            timeout=timeout_s,
        )

    async def complete(
        self,
        role: ModelRole,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> ModelReply:
        """Send one chat request for ``role``, falling back along its model chain.

        Args:
            role: Planner, worker, or condenser.
            messages: The conversation so far, in OpenAI chat format.
            tools: Tool definitions in OpenAI ``tools`` format, if tools are allowed.

        Returns:
            The normalized reply.

        Raises:
            ModelUnavailableError: If every model in the chain failed with a fallback error.
            openai.APIStatusError: For non-recoverable errors such as an invalid request.
        """
        chain = self._settings.model_chain(role)
        sampling = self._settings.sampling()
        failures: list[str] = []
        for model in chain:
            started = time.monotonic()
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=list(messages),  # type: ignore[arg-type]
                    temperature=float(sampling["temperature"]),
                    top_p=float(sampling["top_p"]),
                    max_tokens=int(sampling["max_tokens"]),
                    **_tool_kwargs(tools),
                )
            except _FALLBACK_ERRORS as exc:
                failures.append(f"{model}: {type(exc).__name__}")
                self._emit(
                    EventType.ERROR,
                    {
                        "where": "model_call",
                        "message": (
                            f"{model} unavailable ({type(exc).__name__}); trying the next model"
                        ),
                        "fatal": False,
                    },
                )
                continue
            if not response.choices:
                failures.append(f"{model}: empty response")
                continue
            fallback_from = chain[0] if model != chain[0] else None
            return self._to_reply(role, model, response, started, fallback_from, sampling)
        raise ModelUnavailableError(role, failures)

    async def list_models(self) -> list[str]:
        """Return the model IDs listed by the endpoint's ``/v1/models``."""
        page = await self._client.models.list()
        return [model.id for model in page.data]

    def _to_reply(
        self,
        role: ModelRole,
        model: str,
        response: Any,
        started: float,
        fallback_from: str | None,
        sampling: Mapping[str, float | int],
    ) -> ModelReply:
        message = response.choices[0].message
        extra: dict[str, Any] = message.model_extra or {}
        reasoning = extra.get("reasoning_content") or extra.get("reasoning")
        reasoning_text = str(reasoning) if reasoning else None
        usage = response.usage
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = self._prices.cost_usd(model, prompt_tokens, completion_tokens)

        parse_error: str | None = None
        try:
            tool_calls = extract_tool_calls(message)
        except ToolCallParseError as exc:
            tool_calls, parse_error = [], f"{exc} (raw: {exc.snippet[:200]})"

        elapsed = time.monotonic() - started
        self._emit(
            EventType.MODEL_CALL,
            {
                "role": role.value,
                "model": model,
                "temperature": sampling["temperature"],
                "max_tokens": sampling["max_tokens"],
                "top_p": sampling["top_p"],
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": round(cost, 8),
                "elapsed_s": round(elapsed, 3),
                "fallback_from": fallback_from,
                "has_reasoning": reasoning_text is not None,
            },
        )
        if reasoning_text:
            self._emit(
                EventType.REASONING,
                {"role": role.value, "text": reasoning_text[:_REASONING_LIMIT]},
            )

        return ModelReply(
            content=message.content,
            tool_calls=tool_calls,
            reasoning=reasoning_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            model=model,
            fallback_from=fallback_from,
            elapsed_s=elapsed,
            message=_assistant_message(message.content, tool_calls),
            parse_error=parse_error,
        )

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(event_type, data)


def _tool_kwargs(tools: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    if not tools:
        return {}
    return {"tools": list(tools), "tool_choice": "auto"}


def _assistant_message(content: str | None, tool_calls: Sequence[ToolCall]) -> dict[str, Any]:
    """Build the assistant message to append to the conversation history."""
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    native = [call for call in tool_calls if call.native]
    if native:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.raw_args or "{}"},
            }
            for call in native
        ]
    return message
