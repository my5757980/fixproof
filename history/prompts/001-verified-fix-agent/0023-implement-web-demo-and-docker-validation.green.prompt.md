---
id: 0023
title: Implement Web Demo And Docker Validation
stage: green
date: 2026-10-11
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.implement
labels: ["implementation", "phase-4", "user-story-2", "web-demo", "docker", "tdd"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: history/adr/0008-judge-demo-hosting-and-access-control.md
  pr: null
files:
 - src/fixproof/web/runs.py
 - src/fixproof/web/app.py
 - src/fixproof/web/samples.toml
 - src/fixproof/web/static/index.html
 - src/fixproof/web/static/app.js
 - src/fixproof/web/static/style.css
 - src/fixproof/wiring.py
 - src/fixproof/cli.py
 - src/fixproof/agent/orchestrator.py
 - src/fixproof/budget.py
 - src/fixproof/sandbox/docker_dev.py
 - Dockerfile
 - .dockerignore
 - replays/index.toml
 - pyproject.toml
 - uv.lock
 - specs/001-verified-fix-agent/tasks.md
tests:
 - tests/unit/test_run_manager.py (12)
 - tests/integration/test_web_api.py (19)
 - tests/contract/test_openapi_contract.py (11)
 - tests/integration/test_cli.py (+2 serve)
 - tests/integration/test_orchestrator_single.py (+2)
 - tests/unit/test_budget.py (+1)
 - tests/unit/test_docker_executor.py (+1)
 - tests/live/test_docker_end_to_end.py (1, opt-in with FIXPROOF_DOCKER=1; passed in real containers)
---

## Prompt

```text
shruuuu karooo agayyyy or docker desktop tum khud on run kaar loooooo
```

## Response snapshot

Started Docker Desktop (server 29.1.3) and pulled `python:3.12`. Ran the whole agent end to end in
real Docker containers with a scripted model: real `pip install`, git baseline, pytest with JUnit
parsing, edits, verification, and patch. The result was **verified** in 3.5 minutes (opt-in test
`tests/live/test_docker_end_to_end.py`). The Docker executor now removes the images it created
when it closes.

Phase 4 (User Story 2), tests first (the three new test files failed with import errors before
the code existed):

- `RunManager`: FIFO admission with exact queue positions, a per-visitor daily allowance keyed by
  a hashed IP, a daily budget persisted in `_budget.json` that admits a run only if today's rest
  covers its worst case (model cap plus sandbox minutes), one-time control tokens stored as
  SHA-256, stop while queued, replays from `replays/index.toml`, and finished runs served from
  disk with only the newest 200 kept.
- FastAPI app per `contracts/openapi.yaml`: SSE with `Last-Event-ID` and keep-alives, labeled
  replays, the patch download, contract error codes, and no apply or pull-request endpoint.
- A static UI without a framework; all untrusted text is rendered with `textContent`.
- `fixproof serve`, which refuses dev settings unless `FIXPROOF_ALLOW_DEV=1`.
- A Dockerfile (non-root user, health check) and `.dockerignore`. The image was built (384 MB)
  and probed: health reported "degraded" with a clear reason (no key), the 3 samples, the page,
  503 `live_paused` on a run request, and the user `fixproof`.
- Orchestrator fixes found along the way: `run_started` is now always the first event (a run
  stopped while queued previously had none), the time budget now starts when a run leaves the
  queue (queue time used to count), and a request can choose its base image (the benchmark tasks
  need Python 3.9 and 3.11).
- A jsdom smoke check of the real page with a real trace passed 21 checks, including the REPLAY
  banner, the patch viewer, and HTML in model text shown as text (kept out of the repository to
  avoid a Node toolchain).

**Checkpoint**: 335 passed, 8 skipped (7 live, 1 Docker opt-in); ruff, format, and mypy strict
(37 files) are clean. Commit `56eee4c`.

**Blocked**: T064 (record real replays) and T065 (deploy to Hugging Face Spaces) need Nebius
access; T060's final sample choice waits for T054.

## Outcome

- ✅ Impact: Stories 1 and 2 are implemented; the demo runs locally and in its container image.
- 🧪 Tests: 335 passed, 0 failed; the opt-in Docker end-to-end test passed in real containers.
- 📁 Files: 9 new source and asset files, Dockerfile and .dockerignore, 5 new test files.
- 🔁 Next prompts: Phase 5 (parallel hypotheses) or Phase 6 (apply and pull request); T054,
  T064, and T065 once a Token Factory key is available.
- 🧠 Reflection: Running the real executor found nothing broken but showed image buildup;
  designing the queue found a real time-budget bug that the fake-only tests could not see.

## Evaluation notes (flywheel)

- Failure modes observed:
  - A test set a sandbox rate of $0.50 per minute, which made one run's worst case larger than
    the daily cap; the code refused correctly and the test was corrected to a realistic rate.
  - `SampleTask.model_dump` included internal task fields that the API schema forbids; the
    samples endpoint now builds its response explicitly.
- Graders run and results (PASS/FAIL): pytest 335 PASS (8 skipped); Docker end-to-end PASS;
  container probe PASS; jsdom UI smoke 21/21 PASS; ruff PASS; ruff format PASS; mypy PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): add `.gitattributes` with `* text=auto eol=lf` before
  publishing, so files keep LF endings on Windows checkouts.
