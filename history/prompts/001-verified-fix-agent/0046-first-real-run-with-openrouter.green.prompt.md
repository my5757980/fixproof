---
id: 0046
title: First Real Run With OpenRouter
stage: green
date: 2026-10-16
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["personal-mode", "openrouter", "T096", "real-run"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - specs/001-verified-fix-agent/tasks.md
 - .env (ignored; key and planner model, never committed)
tests:
 - uv run fixproof doctor (all OK)
 - one real fixproof fix on psf__requests-1142 (Not verified, step budget)
---

## Prompt

The user pasted their OpenRouter API key as the whole message. It is redacted here: secrets are
never recorded in PHRs or commits.

```text
[OpenRouter API key redacted]
```

## Response snapshot

Claude saved the key into the ignored `.env` without echoing it, closed the Notepad window that
still held the old `.env` (so a later save could not erase the key), closed the Playwright
browser, and deleted the day's browser logs (they held the key page). It advised replacing the
key later because chat history keeps it (the key has a $1 limit and only free models are used).

`fixproof doctor` passed: key set, OpenRouter endpoint labeled personal mode, all three `:free`
Nemotron IDs listed, Docker reachable. A one-line test call to the worker answered "OK" in 2 s at
$0. Then one real run (T096): psf__requests-1142 on python:3.9 with `--max-steps 30
--max-minutes 60`. Setup took 368 s with no commit (three installs in one chain container). The
agent reproduced the bug with a failing test and named the right root cause, but its fix was
incomplete (it also changed the `data` check) and it spent steps on extra tests and debug
scripts, so the run ended **Not verified** at the step budget after 2008 s, $0, 30 model calls.
The free Ultra planner variant timed out twice (about 6.5 minutes), so the owner's `.env` now
uses Super as the planner. The result is recorded in tasks.md T096.

## Outcome

- ✅ Impact: personal mode works end to end with real NVIDIA Nemotron models and local Docker.
- 🧪 Tests: doctor OK; real run completed with an honest Not verified label.
- 📁 Files: tasks.md; the ignored `.env`.
- 🔁 Next prompts: run again after the free daily limit resets (40 steps, Super planner); rerun
  the live Docker tests when memory allows; replace the key that was pasted in chat.
- 🧠 Reflection: the agent's diagnosis was right; the step budget went to side files, which a
  prompt nudge or a larger budget may fix.

## Evaluation notes (flywheel)

- Failure modes observed: free Ultra endpoint timeouts; the worker wandered into extra files.
- Graders run and results (PASS/FAIL): doctor PASS; run label Not verified (budget).
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): the same task with 40 steps and Super as planner.
