---
id: 0066
title: README Real Results
stage: misc
date: 2026-10-18
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["docs", "readme", "personal-mode", "results"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - README.md
tests:
 - full offline suite (448 passed, 10 skipped)
---

## Prompt

```text
haaaaaa
```

## Response snapshot

The user agreed to put the real results in the README. Claude updated the status note (no
Nebius access from Pakistan, no hackathon submission planned, real runs in personal mode), added
a shortened sample output of the verified psf__requests-1142 run, and a "Results in personal
mode" section: psf__requests-1142 Verified with `fixproof fix` (15.9 min) and pallets__flask-5014
Verified with the benchmark runner (16.1 min, fresh re-check passed, hidden tests agree), the
models and machine used, $0 per run, and the FixProof problems those runs exposed and fixed.
Every result is labeled as personal mode, not the hackathon platform.

## Outcome

- ✅ Impact: the README shows that FixProof works, honestly labeled.
- 🧪 Tests: offline suite still passes.
- 📁 Files: README.md.
- 🔁 Next prompts: psf__requests-5414 after the free limit resets; GitHub when the user asks.
- 🧠 Reflection: personal-mode results stay clearly separate from hackathon claims.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
