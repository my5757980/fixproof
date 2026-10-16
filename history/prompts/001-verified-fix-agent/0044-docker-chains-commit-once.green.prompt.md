---
id: 0044
title: Docker Chains Commit Once
stage: green
date: 2026-10-16
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["personal-mode", "docker", "performance", "T097", "permissions"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - src/fixproof/sandbox/docker_dev.py
 - tests/unit/test_docker_executor.py
 - specs/001-verified-fix-agent/research.md
 - specs/001-verified-fix-agent/tasks.md
tests:
 - tests/unit/test_docker_executor.py (24 passed)
 - full offline suite (431 passed, 10 skipped)
 - scripted Docker run with the real daemon (verified, 127 s, 1 commit)
---

## Prompt

```text
dayy deee permission
```

## Response snapshot

The user said they had given the permission. Claude retried reading the OpenRouter key into a
local file; auto mode still denied it, and no allow rule for `mcp__playwright__browser_evaluate`
existed in any settings file, so Claude explained how to add it through `/permissions` (or to
paste the key into the open Notepad) and did not bypass the block.

T097: measured a scripted run (fake model, real Docker) with the old executor: 888 s, of which
700 s were five `docker commit` calls (51-284 s each, whatever the size; Docker Desktop uses the
containerd image store). A second run hit 374 s for one commit. The executor now:
- keeps the repository tarball on the host until the first container extracts it;
- keeps written files in memory and streams them into each container;
- runs mutating runs as a chain in one stopped container (`STEP_SCRIPT` copied in, container
  restarted) and commits once, when a disposable run, a read, or a write needs the result;
- rebuilds an older chain state (the input of a failed or timed-out install) by running its
  earlier commands in a new container, so snapshots never change under their callers; a lock
  serializes chain changes and commits.

The same scripted run then took 127 s with one commit and was verified. Unit tests cover chains,
retries after a failure, rebuilds, timeouts, tarball reads and writes, and cleanup; the full
offline suite passes. The opt-in live Docker tests (including the benchmark's fresh-container
checks) were started but stopped by Claude Code for low system memory, so they were not rerun;
leftover FixProof containers and images from that test and from a run on 2026-10-11 were removed
(the user's postgres and redis containers were left alone).

## Outcome

- ✅ Impact: a FixProof run on this machine is about 7 times faster in the measured scenario;
  setups with several install commands save a commit per command.
- 🧪 Tests: 24 executor unit tests, 431 offline tests, one live scripted Docker run verified.
- 📁 Files: Docker executor, its tests, research R5, tasks T097.
- 🔁 Next prompts: rerun the live Docker tests when memory allows (the user decides); the
  OpenRouter key in `.env`; `doctor`; one real run (T096).
- 🧠 Reflection: measuring first showed that the number of commits, not their size, was the cost.

## Evaluation notes (flywheel)

- Failure modes observed: background jobs are killed under memory pressure on this machine.
- Graders run and results (PASS/FAIL): unit and offline suites PASS; live scripted run PASS;
  live benchmark test not completed (stopped for low memory).
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): run the live benchmark Docker test alone with other
  apps closed.
