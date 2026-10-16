---
id: 0041
title: Add OpenRouter to Personal Mode
stage: constitution
date: 2026-10-15
surface: agent
model: claude-opus-5-5
feature: none
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.constitution
labels: ["constitution", "personal-mode", "openrouter", "governance"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .specify/memory/constitution.md
 - .specify/templates/plan-template.md
tests:
 - none
---

## Prompt

```text
Amend the Personal Mode section (project owner's decision, 2026-10-15). Context: the owner's NVIDIA account on build.nvidia.com cannot create API keys; the API Keys page shows "API Access Unavailable - Please contact support to verify your account access". The owner is emailing NVIDIA support on 2026-10-15; NVIDIA developer-forum reports say such replies often take one to two weeks or longer. The owner decided that personal mode MAY also use OpenRouter (https://openrouter.ai/api/v1, OpenAI-compatible), which serves the same NVIDIA Nemotron models as free ":free" variants (verified on 2026-10-15 in https://openrouter.ai/api/v1/models: planner nvidia/nemotron-3-ultra-550b-a55b:free, worker nvidia/nemotron-3-super-120b-a12b:free, fallback nvidia/nemotron-3.5-lightning:free; all three support tool calls; free variants have a per-day request limit). Selection: FIXPROOF_PROVIDER=openrouter with the key in OPENROUTER_API_KEY. Everything else in Personal Mode applies unchanged and equally to both providers: explicit selection only, never the shipped default and never an automatic fallback (also no automatic fallback from one personal provider to another), the core loop still on NVIDIA Nemotron models by role, `fixproof doctor` verifies the IDs against the endpoint's model list, the local Docker executor with the same sandbox rules, every result labeled "not the hackathon platform" (naming the provider), the hosted demo refuses it unless FIXPROOF_ALLOW_DEV=1, and OPENROUTER_API_KEY follows the same secret rules as every other key. Billed (non-free) OpenRouter models need an explicit price in FIXPROOF_PRICES so cost budgets stay correct. In Principle I, the endpoint bullet should say the only other built-in endpoints are the personal-mode providers' (NVIDIA's API and OpenRouter), used only when personal mode is explicitly selected. The hackathon configuration and every hackathon rule stay unchanged. Version bump: MINOR (2.1.0 -> 2.2.0) because existing guidance is materially expanded and nothing is relaxed for the hackathon configuration. Update the Sync Impact Report.
```

## Response snapshot

Amended the constitution to 2.2.0 (MINOR): Personal Mode now allows two explicitly selected
providers, NVIDIA's API (`NVIDIA_API_KEY`) and OpenRouter (`OPENROUTER_API_KEY`, free `:free`
Nemotron variants), with no fallback between them; billed OpenRouter models need a
`FIXPROOF_PRICES` entry; labels name the provider; both keys follow the secret rules. Principle
I's endpoint bullet names both providers as the only other built-in endpoints. The Sync Impact
Report records the owner's decision and date. The plan template's Constitution Check I names
both providers; the tasks and spec templates, CLAUDE.md, and command files needed no change.

## Outcome

- ✅ Impact: the OpenRouter provider is allowed for personal mode without relaxing any hackathon
  rule.
- 🧪 Tests: none (governance text).
- 📁 Files: constitution, plan template.
- 🔁 Next prompts: implement the provider and update the README, spec FR-024, plan D13, tasks,
  and quickstart.
- 🧠 Reflection: the owner-decided-mode clause from 2.1.0 made this a scoped MINOR amendment.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): no unresolved placeholders; version line and report agree.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
