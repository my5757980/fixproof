---
id: 0050
title: Result in Three Plain Lines
stage: explainer
date: 2026-10-16
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["status", "roman-urdu", "T096"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - none
tests:
 - none
---

## Prompt

```text
short mayy batoo kia bol rahayyyy hooooo
```

## Response snapshot

Restated the run's result in three plain lines without technical words: the AI found the bug but
could not fully fix it, today's free limit is used up, and Claude asked whether to run it again
tomorrow.

## Outcome

- ✅ Impact: the user understands the result and the single decision left.
- 🧪 Tests: none.
- 📁 Files: none.
- 🔁 Next prompts: the user's answer about running again tomorrow.
- 🧠 Reflection: avoid words like steps, verified, planner, model names, and commit.

## Evaluation notes (flywheel)

- Failure modes observed: a four-line reply was still too technical.
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): three lines, everyday words only.
