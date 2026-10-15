---
id: 0032
title: Add Personal Mode To Constitution
stage: constitution
date: 2026-10-15
surface: agent
model: claude-opus-5-5
feature: none
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.constitution
labels: ["constitution", "personal-mode", "nvidia-api", "governance"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .specify/memory/constitution.md
 - .specify/templates/plan-template.md
 - .specify/templates/tasks-template.md
tests:
 - none
---

## Prompt

User message:

```text
haaaaaa shuruuuu karooooo
```

`/sp.constitution` input (drafted by Claude from the agreed plan):

```text
Amend Principle I (Hackathon Eligibility & Platform Compliance) to add a scoped "personal mode". Context: on 2026-10-15 the project owner decided FixProof must also be complete and usable for personal use even if the hackathon submission does not happen, because Nebius Token Factory billing is unavailable in Pakistan (no staff reply since 2026-10-10). Keep every existing hackathon rule for the hackathon configuration (default config, hosted demo, video, published benchmark results, Devpost submission): those still MUST use Nebius Token Factory and Token Factory Sandboxes. Add: outside the hackathon configuration, FixProof MAY run in a personal mode that uses NVIDIA's own OpenAI-compatible API (build.nvidia.com, https://integrate.api.nvidia.com/v1) for NVIDIA Nemotron models and the local Docker executor, selected explicitly by configuration (FIXPROOF_PROVIDER=nvidia, FIXPROOF_EXECUTOR=docker); it must be clearly labeled as not the hackathon platform wherever results are shown, must never be an automatic fallback, and its keys follow the same secret rules. The Nemotron-by-role rule (Ultra planner, Super worker, small fallback) applies in both modes. Version bump: MINOR (2.0.0 -> 2.1.0) because hackathon rules are unchanged and personal mode is a new scoped allowance. Update the Sync Impact Report.
```

## Response snapshot

Amended the constitution to 2.1.0 (MINOR):

- Principle I now states its scope (the hackathon configuration: default config, demo, video,
  published benchmark results, submission); its endpoint and executor bullets name personal mode
  as the only other, explicitly selected setup. No hackathon rule was relaxed.
- New section **Personal Mode (outside the hackathon)**: explicit selection only
  (`FIXPROOF_PROVIDER=nvidia`, usually `FIXPROOF_EXECUTOR=docker`), never the default or an
  automatic fallback; Nemotron by role through NVIDIA's API with IDs verified by `doctor`; the
  same sandbox and secret rules; always labeled as not the hackathon platform; the hosted demo
  still refuses it unless `FIXPROOF_ALLOW_DEV=1`.
- Governance: the amendment rule previously allowed Principle I changes only when the hackathon
  rules change. It now also allows owner-decided modes outside the hackathon configuration that
  never relax it, recorded with the decision and date (this amendment cites the owner's
  2026-10-15 decision and the unanswered Discord thread).
- Templates: plan-template Constitution Check I and tasks-template T009 mention personal mode;
  README, `.env.example`, and the feature's spec, plan, and tasks are updated by the
  implementation that follows.

## Outcome

- ✅ Impact: Personal mode is allowed without weakening the hackathon configuration.
- 🧪 Tests: none (governance change).
- 📁 Files: constitution, plan template, tasks template.
- 🔁 Next prompts: implement personal mode (provider setting, NVIDIA defaults, labels, docs).
- 🧠 Reflection: The old amendment rule would have blocked this change; amending governance
  openly beats quietly working around Principle I.

## Evaluation notes (flywheel)

- Failure modes observed: none.
- Graders run and results (PASS/FAIL): no unresolved placeholders; version line matches the
  report; dates in ISO format.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
