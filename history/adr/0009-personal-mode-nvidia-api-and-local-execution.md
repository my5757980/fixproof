# ADR-0009: Personal Mode: NVIDIA API and Local Execution

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted (amends ADR-0001 and ADR-0003 outside the hackathon configuration)
- **Date:** 2026-10-15
- **Feature:** 001-verified-fix-agent
- **Context:** Nebius Token Factory billing is unavailable in Pakistan, and the support thread
  opened in the Nebius Discord on 2026-10-10 has had no staff reply (several other participants
  report the same blocker). Without a key, FixProof cannot run at all, although the code is
  complete and tested offline. On 2026-10-15 the project owner decided that the hackathon
  submission is optional and that FixProof must be complete and usable for personal work.
  Constitution 2.1.0 added a Personal Mode section for this; the hackathon configuration (default
  config, demo, video, published benchmark, submission) must stay on Nebius Token Factory and
  Token Factory Sandboxes. ADR-0001 says no other provider is ever used, and ADR-0003 makes the
  Docker executor development-only, so both need a scoped amendment. Implemented in Phase 8
  (T092–T095; `src/fixproof/config.py`, `cli.py`, `sandbox/factory.py`, `agent/orchestrator.py`,
  `bench/runner.py`).

## Decision

- **Selection**: one setting, `FIXPROOF_PROVIDER`, with `nebius` (default, the hackathon
  configuration) and `nvidia` (personal mode). Personal mode is never the default and never an
  automatic fallback when Nebius fails; unknown providers are rejected.
- **Inference**: NVIDIA's own OpenAI-compatible API (`https://integrate.api.nvidia.com/v1/`, key in
  `NVIDIA_API_KEY` from build.nvidia.com) through the same `openai` SDK client and `ModelGateway`
  as ADR-0001. Roles stay Nemotron: planner `nvidia/nemotron-3-ultra-550b-a55b`, worker
  `nvidia/nemotron-3-super-120b-a12b`, fallback `nvidia/nemotron-3.5-lightning-30b-a3b`, with the
  same same-provider fallback chain. These IDs come from third-party documentation of the API;
  `fixproof doctor` checks them against the endpoint's `/v1/models`.
- **Defaults, not overrides**: the provider changes only the defaults of the base URL and the
  role model IDs; any value set explicitly (environment, `.env`, or by name) still wins.
  `.env.personal.example` leaves out the Nebius-only lines that would otherwise override them.
- **Cost**: role models in personal mode are priced at $0 (NVIDIA's API is free to use for these
  models; the free tier is credit- and rate-limited). The step and time budgets still bound
  every run; `FIXPROOF_PRICES` can still set real prices.
- **Execution**: the local `DockerExecutor` (ADR-0003) is the personal-mode executor, with its
  sandbox rules unchanged (no host mounts, `--network none` for model-started commands, timeouts,
  output limits).
- **Labels everywhere**: `Settings.platform_note()` describes any setup that is not the hackathon
  platform. `doctor` shows "personal mode, not the hackathon platform"; `fix` and `bench run`
  print the note; every run report gets it as its first flag; benchmark summaries carry it and
  say not to present the results as hackathon results.
- **Demo guard**: `assert_demo_safe` (ADR-0008) refuses `FIXPROOF_PROVIDER=nvidia` unless
  `FIXPROOF_ALLOW_DEV=1` is set for local testing.

## Consequences

### Positive

- FixProof becomes usable today, without Nebius access, on the same Nemotron model family and
  the same agent code: no fork, no second code path in the agent loop.
- The hackathon configuration is untouched: Nebius stays the default, the demo refuses personal
  mode, and every personal-mode result is labeled, so it cannot be mistaken for an eligible run.
- Small change surface: one setting, provider defaults in configuration, one label helper; the
  existing offline tests still cover the agent loop, and new tests pin the provider rules.
- If Nebius access arrives later, switching back is one setting.

### Negative

- The NVIDIA model IDs are unconfirmed until `doctor` runs with a real key; a wrong default
  needs a `FIXPROOF_*_MODEL` override.
- NVIDIA's free tier is credit- and rate-limited; long runs or the full benchmark may hit the
  limit, and the $0 cost makes the cost budget ineffective in personal mode.
- Local Docker on a small machine is slow (image commits took minutes during task validation),
  so runs need larger time budgets until the executor is made faster (T097).
- Tool-calling quality of these exact models on NVIDIA's API is unverified until the first real
  run (T096).
- Two providers mean two sets of defaults to keep in sync with the documentation.

## Alternatives Considered

- **Wait for Nebius only** (or the teammate-account route): keeps one provider but leaves the
  project unusable for the owner until an unknown date; the teammate route needs someone in a
  supported country. Kept open (personal mode does not block it), rejected as the only path.
- **OpenRouter** (some Nemotron models free): one key for many models, but free endpoints log
  prompts and are trial use only, and routing through a third party adds a privacy and
  reliability layer. Rejected as the default personal provider; still reachable as a manual
  development override of the base URL.
- **Local models (Ollama or similar)**: no API key and nothing leaves the machine, but this
  computer has 3.9 GB of RAM, far too little for Nemotron models of useful size. Rejected.
- **A multi-provider router (LiteLLM-style) or plugin system**: general, but a new dependency and
  much more surface for one extra endpoint (Constitution III). Rejected in favor of one setting.
- **Replace Nebius entirely with NVIDIA's API**: simpler configuration, but it would drop the
  hackathon configuration that may still be submitted. Rejected.

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (FR-024, Mandated Platform
  Constraints)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D12); tasks.md
  Phase 8 (T092–T097)
- Constitution: [constitution.md](../../.specify/memory/constitution.md) 2.1.0, Personal Mode
- Related ADRs: ADR-0001 (inference platform; amended for personal mode), ADR-0003 (execution;
  Docker executor allowed in personal mode), ADR-0008 (demo guard; refuses personal mode)
- Evaluator Evidence: `tests/unit/test_config.py` (personal mode, env examples),
  `tests/unit/test_factory.py`, `tests/integration/test_cli.py` (doctor),
  `tests/integration/test_orchestrator_single.py` (report flag),
  `tests/integration/test_bench_runner.py` (summary label); PHR 0032 and 0033
