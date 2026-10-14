---
id: 0024
title: Implement Parallel Hypotheses And Apply PR
stage: green
date: 2026-10-14
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.implement
labels: ["implementation", "phase-5", "phase-6", "user-story-3", "user-story-4", "parallel", "pull-request", "tdd"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: history/adr/0006-parallel-hypotheses-on-sandbox-branches.md
  pr: null
files:
 - src/fixproof/agent/hypotheses.py
 - src/fixproof/agent/orchestrator.py
 - src/fixproof/agent/prompts.py
 - src/fixproof/agent/report.py
 - src/fixproof/agent/worker.py
 - src/fixproof/sandbox/executor.py
 - src/fixproof/web/runs.py
 - src/fixproof/repo/patches.py
 - src/fixproof/repo/github.py
 - src/fixproof/wiring.py
 - src/fixproof/cli.py
 - specs/001-verified-fix-agent/tasks.md
 - tests/fakes/parallel.py
 - tests/fakes/fake_executor.py
 - tests/fakes/web.py
tests:
 - tests/integration/test_parallel_hypotheses.py (7)
 - tests/integration/test_apply_pr.py (20, 1 skipped where symlinks are not permitted)
 - tests/integration/test_cli.py (+2 parallel)
 - tests/unit/test_executor_helpers.py (+1 patch command round trip)
 - tests/unit/test_run_manager.py (parallel mode capped at 3)
 - tests/live/test_docker_end_to_end.py (opt-in with FIXPROOF_DOCKER=1; passed again in real containers)
---

## Prompt

```text
haaaaa
```

```text
continue
```

```text
continue
```

## Response snapshot

Phase 5 (User Story 3, T066–T069), tests first:

- `agent/hypotheses.py`: the planner proposes at most N ranked hypotheses (`--parallel N`, 1–3),
  and each one runs as its own branch from the same baseline, at most N at a time, with an equal
  share of the remaining budget. The first verified branch cancels the others unless
  `--exhaustive` is set; among verified branches the smallest change wins.
- Hypotheses that are not valid JSON get one repair request; if that also fails, the run
  continues with a single attempt and says so.
- The report gains a "Hypotheses" table, and the web demo accepts `mode="parallel"`, capped at 3.
- `compute_patch` now runs one combined git command instead of three concurrent ones.

Phase 6 (User Story 4, T071–T073), tests first:

- `fixproof apply RUN_DIR --to CHECKOUT`: shows the full diff and the evidence, asks
  "Apply this patch? [y/N]" (only y or yes accepts), and refuses runs that are not verified
  unless `--force-unverified` is set. Exit codes: 3 declined, 4 patch rejected.
- `repo/patches.py` validates every path before `git apply`: relative only, no `..`, no `.git`,
  no symlinks.
- `fixproof pr RUN_DIR`: needs the user's own `GITHUB_TOKEN`, forks the repository, creates
  `fixproof/<run_id>` at the run's commit, commits the files through the contents API, and
  opens a draft pull request whose body cites the evidence and discloses the AI agent. Exit 5
  on a GitHub error.

Bugs found and fixed:

- Files committed to the pull request had CRLF line endings on Windows; the patch is now applied
  with `core.autocrlf=false`.
- The fork used to be created before the patch was checked; a patch that no longer applies now
  fails before anything is written to GitHub.
- GitHub errors now include GitHub's own message (for example HTTP 422 details).
- The pull-request body named the Token Factory sandbox even for local Docker runs; it now states
  where the tests actually ran, taken from the run's `run_started` event.

**Checkpoint**: 365 passed, 9 skipped (7 live, 1 Docker opt-in, 1 symlink); ruff, format, and
mypy strict (39 files) are clean. The real Docker end-to-end test passed again in 6 min 43 s.
Commits `694433c`, `034df53`, `50a94f1`.

**Blocked**: T070 (parallel run on a real benchmark task) and T074 (a real pull request on a
test repository) need Nebius access, as do T054, T064, and T065.

## Outcome

- ✅ Impact: User Stories 1–4 are implemented; 67 of 91 tasks are done (about 74%).
- 🧪 Tests: 365 passed, 0 failed; the opt-in Docker end-to-end test passed in real containers.
- 📁 Files: 2 new modules (`hypotheses.py`, `patches.py`), 2 new test files, 1 new fake.
- 🔁 Next prompts: Phase 7 (benchmark runner, web search T075/T076, README, docs, video,
  submission); the blocked tasks once a Token Factory key is available.
- 🧠 Reflection: The fake GitHub API passed the first version, but writing tests for failure
  paths showed the fork came too early; failure-path tests are worth writing before the happy
  path is declared done.

## Evaluation notes (flywheel)

- Failure modes observed:
  - A new test asserted that "Token Factory" was absent from a Docker run's pull-request body,
    but the agent disclosure correctly says the models run on Token Factory; the assertion was
    narrowed to "Token Factory sandbox".
  - An interrupted edit left a temporary file next to `wiring.py`; it was found and deleted, and
    the edit was applied properly.
- Graders run and results (PASS/FAIL): pytest 365 PASS (9 skipped); Docker end-to-end PASS;
  ruff PASS; ruff format PASS; mypy PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): add `.gitattributes` with `* text=auto eol=lf` before
  publishing, so files keep LF endings on Windows checkouts.
