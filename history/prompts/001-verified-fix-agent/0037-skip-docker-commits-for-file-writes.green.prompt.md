---
id: 0037
title: Skip Docker Commits for File Writes
stage: green
date: 2026-10-15
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["personal-mode", "docker", "performance", "T097", "nvidia-login"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: history/adr/0009-personal-mode-nvidia-api-and-local-execution.md
  pr: null
files:
 - src/fixproof/sandbox/docker_dev.py
 - tests/unit/test_docker_executor.py
tests:
 - tests/unit/test_docker_executor.py (13 passed)
---

## Prompt

```text
continue
```

## Response snapshot

Resumed the NVIDIA key step in the Playwright browser. "Log in with Google" now reached NVIDIA's
"Link Your Account" page, which needs the existing NVIDIA password; Claude asked the user to type
it (or reset it) themselves and did not touch the browser while they did.

Meanwhile, started T097. `docker commit` is the slow step on this machine, and every model file
write committed a new image. The Docker executor now keeps written files in memory as a pending
layer on top of the last committed image: `write_files` makes no Docker call, every container
started from the snapshot gets the files as one tar stream (`docker cp -`) before its command
runs, `read_file` serves pending files from memory, a mutating run commits them once with its
other changes, and `tag` only labels a pending snapshot. Tests cover all of this with the fake
docker CLI.

## Outcome

- ✅ Impact: file writes no longer cost a Docker commit; commits remain only for the repository
  upload and mutating runs (install, git baseline, `git apply`).
- 🧪 Tests: tests/unit/test_docker_executor.py, 13 passed; ruff, format, mypy clean.
- 📁 Files: the Docker executor and its unit tests.
- 🔁 Next prompts: time a real run before and after on Docker; get the user's model key.
- 🧠 Reflection: the executor protocol did not need to change; snapshot IDs of pending layers
  stay unique per write, which the tool handlers rely on.

## Evaluation notes (flywheel)

- Failure modes observed: the NVIDIA login could not be finished without the user's password.
- Graders run and results (PASS/FAIL): unit tests PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): measure commit time versus diff size on this
  Docker setup.
