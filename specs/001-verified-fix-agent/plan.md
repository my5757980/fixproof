# Implementation Plan: Verified Fix Agent ("FixProof", working name)

**Branch**: `001-verified-fix-agent` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-verified-fix-agent/spec.md`

**Note**: This template is filled in by the `/sp.plan` command. See `.claude/commands/sp.plan.md` for the execution workflow.

## Summary

FixProof takes a public GitHub repository and one task (an issue link, a failing test, or a bug
description) and returns a fix that comes with proof.

A single bounded agent loop works inside **Nebius Token Factory Sandboxes**, with **NVIDIA
Nemotron 3** models on **Token Factory**: Ultra plans and diagnoses, and Super runs the tool loop.
The loop:

1. installs the project;
2. records a test baseline;
3. reproduces the bug with a failing test;
4. edits code through schema-validated tools;
5. re-runs tests until the harness can independently verify the fix (3 consecutive reproduction
   passes, no baseline regressions, no tampering with existing tests).

Every step is an event that streams to the CLI, to a public web demo for judges (SSE), and to a
JSONL trace that doubles as a labeled replay. Parallel mode forks the sandbox from the
reproduction snapshot to test competing hypotheses side by side and keeps the smallest verified
fix. Research: [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: openai (Token Factory client), contree-sdk (Token Factory Sandboxes), httpx, pydantic v2 + pydantic-settings, FastAPI + uvicorn, Typer + Rich  
**Inference Platform**: Nebius Token Factory (default, `https://api.tokenfactory.nebius.com/v1/`) — see Constitution I  
**Model(s)**: planner `nvidia/Nemotron-3-Ultra-550b-a55b`, worker `nvidia/nemotron-3-super-120b-a12b`, fallback `nvidia/nvidia-nemotron-3-nano-30b-a3b` (IDs validated against `/v1/models` by `fixproof doctor`)  
**Code Execution**: Token Factory Sandboxes via contree-sdk (default; demo and video). Docker executor is dev-only while access is pending (research R5)  
**Storage**: Local files only. Per-run folder `runs/<run_id>/` (`trace.jsonl`, `report.json`, `report.md`, `patch.diff`) plus `runs/_budget.json`. No database.  
**Testing**: pytest + pytest-asyncio (offline fakes by default; live tests opt-in with `FIXPROOF_LIVE=1`), ruff, mypy (strict on `src/`), GitHub Actions CI  
**Target Platform**: Linux container for the judge demo (Hugging Face Spaces, Docker); Windows, macOS, or Linux developer machines for the CLI
**Project Type**: single project (one Python package exposing a CLI and a web service)  
**Performance Goals**:
- plan visible within 30 s and live events within 5 s of completion; Stop within 10 s (SC-006);
- 90% of runs reach an outcome within 15 min (SC-004);
- at least 5 of 10 benchmark tasks verified (SC-001).

**Constraints**:
- Per-run budgets (CLI defaults): 40 model steps, 15 min, $1.00. Demo defaults: 30 steps,
  10 min, $0.60.
- At most 3 parallel branches; model-facing tool output of 8,000 characters or less.
- Sandbox command timeout 300 s (install 600 s).
- Demo: at most 2 concurrent live runs, 3 runs per visitor per day, a $2 per day cost cap, and
  public repositories of 50 MB or less.
- Secrets never enter sandboxes, traces, or logs.

**Scale/Scope**: Hackathon demo traffic (tens of runs per day through 2026-12-15); a benchmark of
at least 10 tasks; target repositories are small-to-medium public Python projects with pytest
suites.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Check each gate against `.specify/memory/constitution.md`. Any unchecked gate MUST be fixed or
justified in Complexity Tracking before proceeding.

**Pre-design (before Phase 0): PASS**

- [x] **I. Eligibility**: LLM calls go to Nebius Token Factory (or Nebius AI Cloud with an ADR)
  by default; code runs and is tested in Token Factory Sandboxes; the core agent loop runs on
  an NVIDIA open-source model (Nemotron preferred), with models assigned by role; model IDs,
  endpoints, and keys come from configuration; dependencies are MIT-compatible.
  *Evidence*: Ultra and Super roles on Token Factory, ContreeExecutor default, all IDs and
  endpoints in `.env`; dependencies are MIT, BSD, or Apache-2.0. The dev-only Docker executor and
  endpoint override are allowed by Principle I and blocked from `serve` and the demo.
- [x] **II. Autonomous & verified**: The feature advances the plan → write → run/test → iterate
  loop on real repositories, names its developer job, audience, and problem, reports success
  only with sandbox evidence, and has no canned or mocked behavior in the shipped path.
  *Evidence*: harness-computed labels (research R8); fakes live only in `tests/`; replays are
  real recorded runs, always labeled.
- [x] **III. Simplicity**: One service, one agent loop, and few pinned dependencies (or a
  justified exception below); step, branch, cost, and time budgets, bounded retries, schema
  validation of tool arguments, bounded tool output, and sandbox checkpoints are defined.
  *Evidence*: one package with CLI and web entry points; no agent framework, vector DB, or extra
  services; nine runtime dependencies.
- [x] **IV. Transparency**: Every new tool has a name, description, validated schema, and
  documented output; tool calls, sandbox commands, and test results stream to the progress
  view and are recorded in the run trace with sandbox IDs.
  *Evidence*: [contracts/agent-tools.md](./contracts/agent-tools.md),
  [contracts/trace-events.md](./contracts/trace-events.md).
- [x] **V. Quality**: Tests are planned for every tool and agent-loop change (offline, with a
  fake model client and fake sandbox executor); linter, formatter, and type checker are
  configured.
- [x] **VI. Reproducibility & judge access**: README (including the hackathon highlights),
  `.env.example`, pinned dependencies, the one-command run and test paths, and demo access
  through 2026-12-15 are updated for this feature.
  *Evidence*: `uv.lock`, `uv run fixproof ...`, `uv run pytest`, Hugging Face Spaces deployment
  with budgets and labeled replay ([quickstart.md](./quickstart.md)).
- [x] **Safety**: Code executes only in the sandbox; actions that leave it are previewed and
  approval-gated; secrets stay out of code, logs, traces, and sandboxes; optional third-party
  tools receive minimal data; the public demo is rate-limited and budget-capped.
  *Evidence*: `apply` and `pr` are CLI-only with interactive confirmation; redaction in the trace
  writer; Tavily is off by default and sends queries only.

**Post-design re-check (after Phase 1): PASS.** The data model, contracts, and quickstart add no
new services or dependencies. The verification rule (R8) is encoded in `data-model.md` and
enforced by the harness. The tool guards (`agent-tools.md`) keep every file change visible and
freeze source edits during reproduction. The one open item is external: Token Factory and
Sandboxes **access** (see Risks). It does not violate any gate, but it blocks the demo and video.

## Project Structure

### Documentation (this feature)

```text
specs/001-verified-fix-agent/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output (also the validation script)
├── contracts/
│   ├── openapi.yaml     # Web demo HTTP API (SSE events)
│   ├── agent-tools.md   # Tool registry contract (schemas, outputs, guards)
│   ├── trace-events.md  # JSONL trace + live stream contract
│   └── cli.md           # CLI commands and exit codes
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /sp.specify)
└── tasks.md             # Phase 2 output (/sp.tasks; NOT created by /sp.plan)
```

### Source Code (repository root)

```text
src/fixproof/
├── __init__.py
├── config.py            # pydantic-settings: keys, endpoints, model roles, prices, budgets, demo limits
├── models.py            # domain models from data-model.md (Run, Task, Evidence, Report, ...)
├── events.py            # TraceEvent + per-run EventBus (fan-out to CLI, SSE, trace writer)
├── trace.py             # JSONL writer with secret redaction; reader/replayer
├── budget.py            # BudgetTracker (steps, wall clock, cost from token usage)
├── llm/
│   ├── client.py        # ModelClient protocol + TokenFactoryClient (openai SDK, retries, fallback chain)
│   ├── pricing.py       # price table → cost per call
│   └── toolcall.py      # native tool_calls + lenient <tool_call> fallback parser
├── sandbox/
│   ├── executor.py      # Executor protocol (prepare, run, read, ls, write, snapshot, diff, cancel_all)
│   ├── factory.py       # executor selection + demo-safety guard (FIXPROOF_ALLOW_DEV)
│   ├── contree.py       # ContreeExecutor — Token Factory Sandboxes (default; bounded retries)
│   ├── docker_dev.py    # DockerExecutor — DEV ONLY, opt-in
│   ├── recipes.py       # install-command detection (pyproject/setup.py/requirements)
│   └── pytest_results.py# JUnit XML → TestRun
├── repo/
│   └── github.py        # URL validation, repo metadata, tarball, issue fetch, PR creation (CLI only)
├── tools/
│   ├── schemas.py       # Pydantic input models (agent-tools.md)
│   ├── registry.py      # name → (schema, handler, phases); JSON-schema export for the model
│   └── handlers.py      # tool implementations on top of Executor (+ guards)
├── agent/
│   ├── prompts.py       # system/user prompt builders for planner and worker
│   ├── worker.py        # single-attempt tool loop (bounded)
│   ├── orchestrator.py  # phases: setup → baseline → plan → reproduce → fix ⇄ verify → report
│   ├── hypotheses.py    # parallel mode: branch from repro snapshot, pick smallest verified
│   ├── verify.py        # harness verification + labeling rule (R8)
│   └── report.py        # Report building (markdown + JSON), citations check
├── bench/
│   └── runner.py        # benchmark runner + results summary (FR-023)
├── web/
│   ├── app.py           # FastAPI app (openapi.yaml), SSE, static files
│   ├── runs.py          # RunManager: queue, concurrency, visitor + daily limits, replays
│   ├── samples.toml     # curated one-click sample tasks (FR-019)
│   └── static/          # index.html, app.js, style.css (no framework)
└── cli.py               # Typer app (contracts/cli.md)

tests/
├── fakes/               # FakeModelClient (scripted responses), FakeExecutor (in-memory FS)
├── unit/                # config, budget, pricing, toolcall parser, recipes, junit parsing, verify rule, redaction
├── contract/            # tool schemas vs agent-tools.md, trace guarantees, OpenAPI shape
├── integration/         # orchestrator end-to-end with fakes; web API + SSE with httpx ASGI transport
└── live/                # opt-in (FIXPROOF_LIVE=1): Token Factory model call, Sandboxes smoke test

bench/tasks.toml         # ≥10 real bug tasks (hidden reference tests)
bench/results/<date>/    # benchmark results.json + summary.md (SC-001, SC-002, SC-004, SC-007)
replays/                 # recorded real-run traces + index.toml for the labeled demo replay
docs/feedback.md         # running Nebius/NVIDIA feedback log (constitution requirement)
docs/licenses.md         # dependency license table (Constitution I)
docs/submission-checklist.md  # fresh-clone, judge-access, and constitution gate records
docs/video-script.md, docs/devpost-submission.md  # submission package
Dockerfile               # judge demo image (Hugging Face Spaces, port 7860)
pyproject.toml, uv.lock, .env.example, LICENSE (MIT), README.md
.github/workflows/ci.yml, .github/workflows/uptime.yml   # CI + daily demo health check (SC-008)
```

**Structure Decision**: This is a single Python project under `src/fixproof/`, with the CLI and
the web demo as two thin entry points over the same orchestrator and event stream
(Constitution III: one service, one loop). Tests are split into unit, contract, integration, and
opt-in live suites. Fakes live only under `tests/` (Constitution II).

## Architecture

```text
            ┌──────────── CLI (Typer/Rich) ───────────┐     ┌──── Web demo (FastAPI + SSE + static UI) ────┐
            │ fix · replay · apply · pr · bench · doctor │     │ RunManager: queue, limits, replays           │
            └───────────────────────┬────────────────────┘     └──────────────────────┬───────────────────────┘
                                    └──────────────► Orchestrator ◄───────────────────┘
                                                        │  phases + budgets + EventBus ──► trace.jsonl / CLI / SSE
              ┌──────────────────────┬──────────────────┼────────────────────┬──────────────────────┐
              ▼                      ▼                  ▼                    ▼                      ▼
     repo/github.py          llm/TokenFactoryClient  tools/registry      agent/verify.py       agent/report.py
     (tarball, issue)        planner=Ultra           (schemas, guards)   (harness label R8)    (md + json, citations)
                             worker=Super ──────────► tools/handlers ───► sandbox/Executor
                             fallback→Nano                                ├─ ContreeExecutor (Token Factory Sandboxes)
                                                                          └─ DockerExecutor (DEV ONLY)
```

**Run lifecycle** (state machine in [data-model.md](./data-model.md)):

0. **initial plan (≤ 30 s, SC-006)**: Right after the run starts, the planner reads the task and
   the repository file tree from the GitHub API (no sandbox needed). It publishes a `plan` event
   with `stage: initial` while setup continues in parallel.
1. **setting_up**:
   - Validate the URL, check that the repository is public and within size limits.
   - Download the tarball, upload it into the sandbox from `python:3.12`, and extract it.
   - Run the detected install command, with one model-assisted retry.
   - Make the git baseline commit and tag the `installed` snapshot.
2. **baseline**: Run the full test suite with JUnit output and re-run failures once to detect
   flakes.
3. **planning**: The planner (Ultra) reads the task, the repository map, and the baseline summary,
   and publishes the **refined** plan (`stage: refined`). In parallel mode it produces up to 3
   hypotheses.
4. **reproducing**: The worker (Super) uses the existing failing test, or creates a reproduction
   test that must fail. Source files stay frozen. The result is tagged as the `repro` snapshot.
5. **fixing**: The worker runs the edit/test tool loop and calls `finish`.
6. **verifying**: The harness runs the reproduction test 3× plus the full suite and checks for
   test-file tampering, then computes the label. If verification fails and budget remains, the
   planner re-diagnoses and the run goes back to step 5.
7. **reporting**: The planner writes the root cause with citations. The harness assembles the
   label, evidence, patch, and flags, then emits `run_finished`.

**Stop and cancellation (FR-012, SC-006)**:

- `stop()` cancels the run's asyncio task. That interrupts any in-flight model request or
  sandbox wait immediately.
- Executors also cancel their remote operations (`Executor.cancel_all()`).
- Reporting then runs with partial results under a 10-second deadline.

A long command or model call therefore never delays a stop beyond 10 seconds.

**Key design decisions** (details and alternatives in research.md):

| # | Decision | Research |
|---|----------|----------|
| D1 | OpenAI SDK against Token Factory; roles: Ultra planner, Super worker, fallback chain to Nano | R1, R2 |
| D2 | Native tool calls plus a lenient fallback parser; Pydantic validation; 3 invalid calls stop the run | R3 |
| D3 | Sandboxes via contree-sdk; repository uploaded as a tarball; git baseline for diffs; `disposable=False` only for mutations | R4 |
| D4 | Executor protocol: Contree (default), Docker (dev-only), Fake (tests only) | R5 |
| D5 | Harness-computed labels: 3× repro pass, no baseline regressions, no test tampering | R8 |
| D6 | Parallel mode = same worker loop on sandbox branches from the `repro` snapshot; smallest verified wins | R9 |
| D7 | One EventBus feeding the CLI, SSE, and the JSONL trace; replays are recorded real runs | R10 |
| D8 | Judge demo on Hugging Face Spaces (Docker) with budgets and labeled replay; Nebius hosting if access allows | R11 |
| D9 | Two-stage plan: initial (≤ 30 s, from the task and the GitHub tree) and refined (after the baseline); stop cancels in-flight work within 10 s | Spec SC-006 |
| D10 | Bounded retries with exponential backoff (3 tries) for transient sandbox API errors, matching the model client (Constitution III) | R4 |
| D11 | Demo stop requires a per-run control token (only its hash is stored); the daily budget includes estimated sandbox cost and lives in `FIXPROOF_STATE_DIR` | R11 |
| D12 | Personal mode (FR-024, constitution 2.1.0): `FIXPROOF_PROVIDER=nvidia` switches the defaults to NVIDIA's API (`https://integrate.api.nvidia.com/v1`, `NVIDIA_API_KEY`) and Nemotron IDs for the same roles, priced at $0 (NVIDIA's free tier); explicitly set values still win; `doctor`, reports, and benchmark summaries say "not the hackathon platform"; `serve` keeps refusing it unless `FIXPROOF_ALLOW_DEV=1` | Constitution 2.1.0, ADR-0009 |
| D13 | Personal mode through OpenRouter (constitution 2.2.0): `FIXPROOF_PROVIDER=openrouter` uses `https://openrouter.ai/api/v1` with `OPENROUTER_API_KEY` and the free `:free` Nemotron variants for the same roles (`nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3-super-120b-a12b:free`, `nvidia/nemotron-3.5-lightning:free`); only `:free` models are priced at $0, so `doctor` fails a billed role model without a `FIXPROOF_PRICES` entry; providers are a table in `config.py` (`PERSONAL_PROVIDERS`), the client and labels are shared, and there is no fallback between providers | Constitution 2.2.0 |
| D14 | Personal mode through Requesty (constitution 2.3.0): `FIXPROOF_PROVIDER=requesty` uses `https://router.requesty.ai/v1` with `REQUESTY_API_KEY` and the NVIDIA IDs of D12, which Requesty lists at $0 with tool calling; only those three are priced at $0; a third entry in `PERSONAL_PROVIDERS`, chosen because OpenRouter's free tier allows about 50 requests a day | Constitution 2.3.0 |

These decisions are recorded as ADRs in `history/adr/`: D1 → ADR-0001, D2 → ADR-0002,
D3/D4/D10 → ADR-0003, D5 → ADR-0004, D9 → ADR-0005, D6 → ADR-0006, D7 → ADR-0007, and
D8/D11 → ADR-0008.

## Delivery Milestones (deadline 2026-10-30 10:00 PDT; feature freeze 2026-10-23)

| Milestone | Dates | Exit criteria |
|-----------|-------|---------------|
| **M0 Foundation** | Oct 10–11 | Scaffold, config, models, events and trace, budget, fakes, CI; `uv run pytest` green offline |
| **M1 Story 1 (MVP)** | Oct 12–15 | Orchestrator plus tools working end to end with fakes; DockerExecutor (dev) fixes a real sample repository from the CLI; reports and patches correct |
| **M2 Nebius live** | Oct 16–18, or as soon as access lands | `doctor` green on Token Factory and Sandboxes; ContreeExecutor passes live smoke tests; benchmark runner working on 3 or more tasks |
| **M3 Story 2 (demo)** | Oct 19–21 | Web demo with SSE, Stop, samples, limits, and replay; deployed to Hugging Face Spaces; first recorded replays |
| **M4 Stories 3 + 4** | Oct 22–23 | Parallel hypotheses plus apply and pr. **Feature freeze 2026-10-23** |
| **M5 Submission** | Oct 24–29 | Full benchmark run with results in the README; README and `docs/feedback.md` complete; video under 3 minutes; Devpost submitted **by Oct 29** (one day of buffer) |

**Access gate**: If Token Factory and Sandboxes access is still missing on **2026-10-20**, switch
to the teammate-account route immediately. The video and benchmark require real Nebius runs, and
replays alone cannot satisfy the rules.

## Risks (top 3)

1. **Access blocked** (Pakistan billing gap). Blast radius: the whole submission. Mitigations:
   offline development with fakes and Docker, the Discord case, the teammate route, and the
   access gate above.
2. **Nemotron tool-calling or long-horizon reliability.** Blast radius: the verified rate.
   Mitigations: strict schemas, the lenient parser, short worker contexts, planner
   re-diagnosis, and early live smoke tests (M2).
3. **Sandbox egress or limits differ** (VERIFY-ON-ACCESS items in R4). Blast radius: setup
   failures. Mitigation: pre-built tagged images for the samples and benchmark tasks.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations. For transparency, these elements might look like added complexity
but stay within the principles:

| Element | Why needed | Simpler alternative rejected because |
|---------|------------|--------------------------------------|
| Two entry points (CLI + web) in one package | Story 1 (developers) and Story 2 (judges need a working demo) | A web-only design loses local developer use; a CLI-only design fails the "working demo" requirement |
| Dev-only DockerExecutor | Develop against real repositories before Sandboxes access (R5) | Running on the host violates sandboxed execution; waiting for access misses the deadline |
| Parallel branches (Story 3) | Differentiator built on Sandboxes branching | It is the same worker loop run N times (bounded at 3), not multi-agent orchestration |
