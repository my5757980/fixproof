---
id: 0004
title: Explain Project Idea Simply
stage: general
date: 2026-10-03
surface: agent
model: claude-opus-5-5
feature: none
branch: none
user: unknown
command: none (chat)
labels: ["explanation", "roman-urdu", "project-idea"]
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
achaaa likin mujayy short mayy asan lafzoo mayy ya to batoo ya project kiaa haii is mayy kia banayaa ga kia karayy gaaa
```

## Response snapshot

Explained the proposed project in short, simple Roman Urdu: an AI coding agent that takes a
GitHub repository link and a bug description, copies the project into a Nebius Token Factory
Sandbox, finds and fixes the bug with an NVIDIA Nemotron model, runs the tests, retries on
failure, and returns the fix with test proof and a plain explanation. Also covered the parallel
fix attempts for hard bugs, the two deliverables (a web demo for judges and a CLI), a concrete
example, and why the idea matches what the judges asked for.

## Outcome

- ✅ Impact: The user understands what will be built before running /sp.specify.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: /sp.specify with the drafted prompt.
- 🧠 Reflection: A concrete before/after example makes the idea clearer than a feature list.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Offer the user a choice of idea before /sp.specify
  if they want something different.
