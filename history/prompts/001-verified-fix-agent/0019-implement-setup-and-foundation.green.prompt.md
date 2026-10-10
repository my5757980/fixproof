---
id: 0019
title: Implement Setup And Foundation Phases
stage: green
date: 2026-10-10
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.implement
labels: ["implementation", "phase-1", "phase-2", "tdd", "foundation"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - pyproject.toml
 - uv.lock
 - LICENSE
 - README.md
 - .env.example
 - .gitignore
 - .github/workflows/ci.yml
 - docs/feedback.md
 - src/fixproof/__init__.py
 - src/fixproof/models.py
 - src/fixproof/config.py
 - src/fixproof/events.py
 - src/fixproof/trace.py
 - src/fixproof/budget.py
 - src/fixproof/llm/toolcall.py
 - src/fixproof/llm/pricing.py
 - src/fixproof/llm/client.py
 - src/fixproof/sandbox/pytest_results.py
 - src/fixproof/sandbox/executor.py
 - src/fixproof/sandbox/recipes.py
 - src/fixproof/repo/github.py
 - tests/fakes/fake_executor.py
 - tests/fakes/fake_model.py
 - specs/001-verified-fix-agent/tasks.md
tests:
 - tests/unit/test_config.py (12)
 - tests/unit/test_events_trace.py (8)
 - tests/unit/test_budget.py (6)
 - tests/unit/test_toolcall.py (8)
 - tests/unit/test_pricing.py (2)
 - tests/unit/test_llm_client.py (6)
 - tests/unit/test_pytest_results.py (9)
 - tests/unit/test_executor_helpers.py (13)
 - tests/unit/test_fakes.py (3)
 - tests/unit/test_recipes.py (10)
 - tests/unit/test_github.py (21)
---

## Prompt

```text
Work through tasks.md phase by phase, starting with Phase 1 Setup and Phase 2 Foundational (M0). T009 (GitHub repo) is deferred by the user: skip it, keep committing locally. Write tests before implementation, run the offline test suite plus ruff and mypy at each phase checkpoint, and report results before continuing. Never mark a task done while its tests fail. Log Token Factory or Sandboxes friction in docs/feedback.md.
```

## Response snapshot

The requirements checklist passed (16/16).

**Phase 1 (T001–T008)**

- Created the uv project:
  - runtime: openai 3.28, contree-sdk 0.3.6, httpx, pydantic 2.14, pydantic-settings, fastapi,
    uvicorn, typer, rich;
  - dev: pytest 9, pytest-asyncio, ruff 0.17, mypy 2.4.
- Ruff rules include D (google docstrings), and SpecKit folders are excluded from linting.
- Added the package skeleton, MIT LICENSE, `.env.example`, `.gitignore`, the CI workflow, a
  seeded `docs/feedback.md`, and the README skeleton.
- T009 was skipped (deferred by the user).
- Committed as `fc8d643`.

**Phase 2 (T010–T031)**

Tests were written first for each component. Implemented:

- models (data-model.md);
- config (pydantic-settings, dev-endpoint detection, secrets, model chains, price table,
  budgets);
- events (EventBus with history plus live subscribers, redaction) and trace (Redactor,
  TraceWriter, `read_trace`, labeled replay);
- budget (steps, time, cost; split for parallel branches with parent propagation);
- toolcall (native calls plus a tagged or fenced fallback; malformed native arguments keep their
  call ID);
- pricing;
- the TokenFactoryClient. Verified against the installed openai 3.28 SDK: it uses `httpx2`, so
  the client accepts an injected `AsyncOpenAI`. It has a fallback chain on
  5xx/404/429/connection errors, no fallback on 400, model_call events with the sampling
  parameters, and reasoning capture;
- pytest_results (xunit1 JUnit for exact node IDs, shell-quoted selectors, markers);
- the executor protocol, plus git baseline and diff commands, `is_test_path`, and `parse_patch`;
- recipes;
- the GitHub client (URL parsing, public and size checks, a tarball download with a size cap
  where the token is stripped on the codeload redirect, issue, tree, rate-limit message);
- the FakeExecutor and FakeModelClient test fakes, with sanity tests.

**Checkpoint**: ruff (lint and format) clean, mypy strict clean (20 files), 98 tests passed
offline. T010–T031 marked done.

## Outcome

- ✅ Impact: M0 Foundation is complete; every User Story 1 component can now be built on tested
  primitives.
- 🧪 Tests: 98 passed, 0 failed (offline, no credentials).
- 📁 Files: 23 source, config, and doc files plus 13 test files.
- 🔁 Next prompts: /sp.implement Phase 3 (User Story 1: tool schemas, registry, handlers,
  verify, prompts, worker, report, orchestrator, ContreeExecutor, DockerExecutor, CLI).
- 🧠 Reflection: Checking the installed SDK before coding caught the move from httpx to httpx2
  in openai 3.x. Mocking with plain httpx would have produced false-passing or broken tests.

## Evaluation notes (flywheel)

- Failure modes observed:
  - Ruff 0.17 also formats Python blocks inside Markdown, which flagged SpecKit command files;
    fixed by excluding the tooling folders.
  - One test made a wrong assumption about `shlex.quote` (safe words are not quoted); the test
    was corrected to check the real security property.
  - One scripted replacement failed on escaping; it was applied with Edit instead.
- Graders run and results (PASS/FAIL): pytest 98/98 PASS; ruff PASS; ruff format PASS; mypy
  strict PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Add `.gitattributes` (`* text=auto eol=lf`) to stop
  CRLF warnings on Windows.
