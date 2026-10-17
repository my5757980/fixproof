---
id: 0057
title: Set Up Requesty Provider
stage: green
date: 2026-10-17
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["personal-mode", "requesty", "config", "api-key"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - src/fixproof/config.py
 - tests/unit/test_config.py
 - tests/unit/test_factory.py
 - tests/integration/test_cli.py
 - .env.example
 - .env.personal.example
 - README.md
 - specs/001-verified-fix-agent/spec.md
 - specs/001-verified-fix-agent/plan.md
 - specs/001-verified-fix-agent/tasks.md
 - specs/001-verified-fix-agent/quickstart.md
 - .specify/memory/constitution.md
 - .specify/templates/plan-template.md
tests:
 - full offline suite (439 passed, 10 skipped)
---

## Prompt

```text
continue
```

## Response snapshot

The user rejected the question about which free option to use and said "continue", so Claude
went ahead with the recommended one, Requesty. It opened Requesty's sign-in page in the browser
for the user (who signed in with Google), amended the constitution to 2.3.0 (PHR 0056), and added
Requesty as a third entry in `PERSONAL_PROVIDERS` (`https://router.requesty.ai/v1/`,
`REQUESTY_API_KEY`, the NVIDIA Nemotron IDs, $0 only for the three listed models), with tests
(defaults, key, prices, label, demo guard, doctor), the `.env` examples, README, spec FR-024,
plan D14, tasks T100-T102, and quickstart. The full offline suite passed (439 passed, 10
skipped). After the sign-in, Claude created a key named "fixproof" (completions only, no admin
rights), switched the ignored `.env` to Requesty with Super as planner and an empty key line, and
asked the user to paste the key.

## Outcome

- ✅ Impact: a free provider with a larger daily limit is ready.
- 🧪 Tests: 439 offline tests.
- 📁 Files: config, tests, docs, constitution.
- 🔁 Next prompts: the key in `.env`, then doctor and a real run (T102).
- 🧠 Reflection: the provider table made the third provider a ten-line code change.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): offline suite PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
