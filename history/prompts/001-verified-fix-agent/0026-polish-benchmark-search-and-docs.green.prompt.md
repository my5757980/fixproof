---
id: 0026
title: Polish Benchmark Search And Docs
stage: green
date: 2026-10-14
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.implement
labels: ["implementation", "phase-7", "benchmark", "web-search", "docs", "tdd"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - src/fixproof/tools/tavily.py
 - src/fixproof/tools/registry.py
 - src/fixproof/wiring.py
 - src/fixproof/bench/runner.py
 - src/fixproof/bench/tasks.py
 - src/fixproof/repo/patches.py
 - src/fixproof/sandbox/recipes.py
 - src/fixproof/agent/orchestrator.py
 - src/fixproof/models.py
 - src/fixproof/cli.py
 - src/fixproof/web/runs.py
 - src/fixproof/web/app.py
 - .github/workflows/uptime.yml
 - .gitattributes
 - README.md
 - docs/licenses.md
 - docs/video-script.md
 - docs/devpost-submission.md
 - docs/submission-checklist.md
 - specs/001-verified-fix-agent/tasks.md
 - specs/001-verified-fix-agent/data-model.md
tests:
 - tests/unit/test_web_search.py (6)
 - tests/integration/test_bench_runner.py (12)
 - tests/contract/test_replays_redacted.py (2)
 - tests/unit/test_recipes.py (+6 pins)
 - tests/unit/test_bench_tasks.py (+2)
 - tests/integration/test_orchestrator_single.py (+1 pins)
 - tests/unit/test_run_manager.py (+1 sample pins)
 - tests/integration/test_cli.py (+1 web search)
 - tests/live/test_docker_end_to_end.py (+1 benchmark checks, opt-in)
---

## Prompt

```text
haaaaa
```

## Response snapshot

Started Phase 7 (polish and submission), tests first for every code change:

- **T075/T076 web search**: `TavilySearch` sends only a whitespace-normalized query of at most
  200 characters (`max_results` 5, `search_depth` basic), maps results to title, URL, and
  snippet, and refuses a query that contains a secret before any request. It is built only when
  `FIXPROOF_WEB_SEARCH=1` and a non-empty `TAVILY_API_KEY` are set. API shape checked against
  the Tavily docs.
- **T077/T078 benchmark runner**: `fixproof bench run` (with `--parallel`, `--compare-single`,
  `--only`, `--out`) and `fixproof bench report`. After each run, a fresh environment is set up
  with the run's own install commands; verified fixes are re-verified there, and the hidden
  reference tests (from the official test patch, never shown to the agent or put into its
  sandbox) run without and with the fix. `results.json` is rewritten after each run;
  `summary.md` has the verified rate, re-check failures, hidden-test agreement, p50/p90 time,
  the share within 15 minutes and within the budget, cost, and single versus parallel.
- **T081** redaction contract test, **T082** license table (all runtime dependencies are
  MIT-compatible), **T089** daily uptime workflow.
- **Dependency pins**: old revisions break with today's dependency releases, so benchmark tasks
  and demo samples can list `pip_packages`, installed after the normal recipe (as SWE-bench's
  environments do; its flask pins were checked in its v3.0.0 constants). Only plain
  requirements are accepted.
- **Docs**: README (all sections; sample output, benchmark numbers, and demo URL marked pending),
  video script, Devpost draft, and the submission checklist with a fresh-clone check
  (`uv sync --frozen`, 385 tests passed, lint and mypy clean).
- **T079 (in progress)**: validating SWE-bench tasks in Docker. `docker commit` takes 3–10
  minutes on this machine, so validation uses plain containers on a named volume. Of the
  Verified requests tasks only `psf__requests-1142` qualifies without pins (others fail on
  ancient pins or dependency drift). The batch with pinned flask and requests tasks was stopped
  by Claude Code because the system ran low on memory (3.9 GB RAM, 0.4 GB free); it was not
  restarted.

**Checkpoint**: affected suites green after each change (last full run 385 passed, 10 skipped);
ruff, format, and mypy strict (41 files) clean. Commits `ac61e0e` through `37cb67b`.

## Outcome

- ✅ Impact: Phase 7 code work is done except the benchmark task list; docs are drafted.
- 🧪 Tests: offline suites green; the opt-in Docker benchmark test is ready.
- 📁 Files: 3 new modules or major additions (tavily, bench runner, pins), 5 new docs.
- 🔁 Next prompts: re-run the task validation in small batches when memory allows, then write
  `bench/tasks.toml` (at least 10 tasks) and update the demo samples; live work once access
  arrives.
- 🧠 Reflection: validating benchmark tasks on real environments found problems that offline
  tests could not: two of the three seeded tasks and the README example would have failed
  for environment reasons, not agent reasons.

## Evaluation notes (flywheel)

- Failure modes observed:
  - The README first claimed the Nano model condenses conversations; the code collapses old
    tool results without a model call. Corrected.
  - A test asserted that "Token Factory" was absent from a Docker run's PR body, which also
    names the models' platform; narrowed to "Token Factory sandbox".
- Graders run and results (PASS/FAIL): pytest PASS; ruff PASS; ruff format PASS; mypy PASS;
  fresh clone PASS; requests-1142 validation PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): when the baseline cannot start because of an
  import error, ask the model for one repair install command (same guard as the install retry).
