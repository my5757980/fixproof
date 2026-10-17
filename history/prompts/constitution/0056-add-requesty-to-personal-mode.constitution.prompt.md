---
id: 0056
title: Add Requesty to Personal Mode
stage: constitution
date: 2026-10-17
surface: agent
model: claude-opus-5-5
feature: none
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.constitution
labels: ["constitution", "personal-mode", "requesty", "governance"]
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
Amend the Personal Mode section (project owner's decision, 2026-10-17). Context: OpenRouter's free tier allows only about 50 requests per day for accounts that have not bought credits, so one FixProof run a day (three real runs on 2026-10-16/17 hit the limit or the step budget). The owner asked for a 100% free setup without the repeated daily limit and told Claude to continue with the recommended option. Add Requesty (https://router.requesty.ai/v1, OpenAI-compatible) as a third personal-mode provider: its public model list (checked 2026-10-17) serves the same NVIDIA Nemotron IDs as NVIDIA's own API at $0 with tool calling (planner nvidia/nemotron-3-ultra-550b-a55b, worker nvidia/nemotron-3-super-120b-a12b, fallback nvidia/nemotron-3.5-lightning-30b-a3b); a third-party directory reports a free tier of about 200 requests per day on free models, to be confirmed in the account. Selection: FIXPROOF_PROVIDER=requesty with the key in REQUESTY_API_KEY. Every Personal Mode rule applies unchanged to all three providers: explicit selection only, never the default or an automatic fallback (and no automatic fallback between personal providers), NVIDIA Nemotron by role, doctor verifies the IDs, the local Docker executor, every result labeled "not the hackathon platform" naming the provider, the demo refuses it unless FIXPROOF_ALLOW_DEV=1, and REQUESTY_API_KEY follows the same secret rules. A billed Requesty model (any model not listed at $0) needs an explicit price in FIXPROOF_PRICES. Requesty may pass prompts to providers whose data terms allow training on them; FixProof only works on public repositories. In Principle I's endpoint bullet, the personal-mode providers become NVIDIA's API, OpenRouter, and Requesty. The hackathon configuration and every hackathon rule stay unchanged. Version bump: MINOR (2.2.0 -> 2.3.0). Update the Sync Impact Report.
```

## Response snapshot

Amended the constitution to 2.3.0 (MINOR): Personal Mode now has three explicitly selected
providers (NVIDIA's API, OpenRouter, Requesty with `REQUESTY_API_KEY`), with no fallback between
them; billed OpenRouter or Requesty models need a `FIXPROOF_PRICES` entry; Requesty may route
prompts to hosts whose terms allow training (public repositories only); `REQUESTY_API_KEY`
follows the secret rules; the rationale mentions free daily limits. Principle I's endpoint
bullet names all three. The Sync Impact Report records the owner's decision and date, and the
plan template's Constitution Check I names the providers.

## Outcome

- ✅ Impact: Requesty is allowed for personal mode without relaxing any hackathon rule.
- 🧪 Tests: none (governance text).
- 📁 Files: constitution, plan template.
- 🔁 Next prompts: implement the provider; update README, spec FR-024, plan D14, tasks, and
  quickstart.
- 🧠 Reflection: the provider table from 2.2.0 makes a third provider a small change.

## Evaluation notes (flywheel)

- Failure modes observed: none
- Graders run and results (PASS/FAIL): no unresolved placeholders; version line and report agree.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
