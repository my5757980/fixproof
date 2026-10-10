---
id: 0003
title: Simple Urdu Summary Of Hackathon Review
stage: general
date: 2026-10-03
surface: agent
model: claude-opus-5-5
feature: none
branch: none
user: unknown
command: none (chat)
labels: ["summary", "roman-urdu", "hackathon", "constitution"]
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
short mayyy batoooo kiaaa bol rahayyy hooo asan lafzooo mayyyy
```

## Response snapshot

Gave a short, simple Roman Urdu summary of the previous answer: the pasted link was a private
Claude login link and was not opened; the official Devpost hackathon page was read instead; the
constitution was mostly correct, and three gaps were fixed in v2.0.0 (Token Factory Sandboxes,
autonomy with approval only at the end, submission checklist and deadline); two urgent actions
(confirm Token Factory access, request Sandboxes beta access); the project idea; and the command
order (git init, then specify, clarify, plan, tasks, analyze, implement).

## Outcome

- ✅ Impact: The user received the previous answer in plain language.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: `! git init`, then /sp.specify with the drafted prompt.
- 🧠 Reflection: This user prefers short answers in simple Roman Urdu; long English reports are
  hard to follow.

## Evaluation notes (flywheel)

- Failure modes observed: The previous answer was too long and too technical for the user.
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Lead with a 5-line Roman Urdu summary, then details.
