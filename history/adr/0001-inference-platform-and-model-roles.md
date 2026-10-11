# ADR-0001: Inference Platform and Model Roles

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** The hackathon rules require every model call in the agent loop to use NVIDIA open
  models served by Nebius Token Factory; the FAQ states that the same models reached through
  OpenRouter or Hugging Face do not count (Constitution I). The agent needs one strong model for
  planning and diagnosis and a cheaper, faster one for dozens of mechanical tool steps, within a
  budget of about $1 per CLI run and $0.60 per demo run. Published model IDs differ in casing
  between Nebius pages. Implemented in Phase 2 and 3 (`src/fixproof/llm/`,
  `src/fixproof/agent/worker.py`).

## Decision

- **Client**: the official `openai` Python SDK against the Token Factory OpenAI-compatible API
  (`https://api.tokenfactory.nebius.com/v1/`, key in `NEBIUS_API_KEY`), with native `tools`
  function calling. SDK-level retries (2) and a 120 s request timeout.
- **Roles** (all configurable):
  - planner: `nvidia/Nemotron-3-Ultra-550b-a55b` (plans, re-diagnosis, final root cause);
  - worker: `nvidia/nemotron-3-super-120b-a12b` (the tool loop and the install-retry suggestion);
  - fallback/condenser: `nvidia/nvidia-nemotron-3-nano-30b-a3b`.
- **Fallback chain, same provider only**: planner Ultra → Super → Nano; worker Super → Nano. A
  fallback happens on 5xx, 404, rate limits after retries, or connection errors; a 400 is not
  retried on another model. No other provider is ever used.
- **Explicit sampling** on every call (temperature 0.3, top_p 0.95, max_tokens 4096 by default),
  recorded in `run_started` and in every `model_call` event (Constitution IV).
- **One gateway for every model call** (`ModelGateway`): check the budget first, then call, then
  count the step, charge the cost from a configurable price table, and publish `model_call`,
  any `reasoning` text (≤ 4,000 characters, verbose view), and a warning when a fallback answered.
- **Configuration, not code**: model IDs, prices, sampling, and the base URL come from settings.
  `fixproof doctor` checks `/v1/models` case-insensitively. A non-Nebius base URL is dev-only:
  the CLI warns, and the demo refuses it (ADR-0008).

## Consequences

### Positive

- Eligible by construction: the only model path is Token Factory with NVIDIA Nemotron models.
- Cost matches the work: Ultra only for a handful of reasoning calls, Super for the many tool
  steps (about $0.25 per single-path run in research R2).
- A brief model outage degrades to a smaller NVIDIA model instead of failing the run.
- Every call is auditable: model, sampling, tokens, cost, and fallback are in the trace.
- The `ModelClient` protocol keeps the agent testable offline with a scripted fake.

### Negative

- Single-provider dependency: if all three models fail, the run stops with
  `service_unavailable` (partial results are still reported).
- Quality depends on Nemotron tool calling, which is unverified until live access (mitigated by
  ADR-0002 and the live smoke tests).
- Fallback answers can be weaker than the primary model; the trace shows when this happened.
- Price-table drift: costs are estimated from configured prices, not billed amounts.

## Alternatives Considered

- **Single model for every role** (Super only, or Ultra only): Super only is cheaper but loses
  the strong-planner story the judges ask for; Ultra only costs about 3× more per tool step for
  little gain on mechanical steps. Rejected.
- **Multi-provider abstraction or agent framework** (LiteLLM-style routers, LangChain): adds a
  dependency and invites non-Nebius fallbacks that break eligibility (Constitution I and III).
  Rejected.
- **Same models through OpenRouter or Hugging Face**: explicitly not eligible per the FAQ.
  Rejected; allowed only as a local dev override that the demo refuses.
- **Raw `httpx` calls**: more code with no benefit over the documented SDK. Rejected.
- **Nemotron 3.5 Lightning as worker**: kept as a configurable alternative if Super's tool calling
  proves weak.

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (Mandated Platform Constraints)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D1); research R1, R2
- Related ADRs: ADR-0002 (tool calling), ADR-0005 (budgets), ADR-0008 (demo guard)
- Evaluator Evidence: `tests/unit/test_llm_client.py`, `tests/contract/test_trace_contract.py`;
  PHR 0019 and 0020 in `history/prompts/001-verified-fix-agent/`
