---
id: 0011
title: Recheck Nebius Emails And Billing List
stage: general
date: 2026-10-10
surface: agent
model: claude-opus-5-5
feature: none
branch: main
user: unknown
command: none (chat)
labels: ["onboarding", "token-factory", "billing", "gmail", "devpost-faq", "playwright", "roman-urdu"]
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
ab check karoo dubara meri email par nebuis sayy related saari email jo jo ayii haiii dekhoo kuch ayaa mila kuch
```

## Response snapshot

Searched the user's Gmail for "nebius" (21 results) and read the new messages since 2026-10-04:
"Welcome to Nebius Token Factory" (Oct 5, generic onboarding), "Build, learn and connect at
Nebius Build Week" (Oct 6, GTC Berlin events), "FAQs - Nebius x NVIDIA Global AI Hackathon"
(Devpost, Oct 7), "Your complete open-AI toolkit" (Oct 8, marketing; mentions team invites with
RBAC), and "Did someone say... prizes?" (Devpost, Oct 9; reminder to submit early). Opened the
new official FAQ page (https://nebiusglobalaihackathon.devpost.com/details/faqs). Key answers:
missing billing countries are a Nebius provisioning gap, not an eligibility rule; there is no
workaround such as billing under another region; missing-country cases are "being handled case
by case with Nebius" via the Nebius Discord; calling NVIDIA models through other providers
(HuggingFace, OpenRouter) does NOT satisfy the platform rule; only the model call must go
through Token Factory, and the rest of the app can be hosted elsewhere; there is no maximum team
size. Re-checked the Token Factory billing form's country list (opened the dropdown only, saved
nothing): Pakistan is still missing (the list goes Oman → Poland).

## Outcome

- ✅ Impact: Confirmed with the official FAQ that Discord is the only route ("case by case") and
  that OpenRouter-style workarounds are not allowed.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: The user joins the Nebius Discord and posts in #token-factory-support (needs
  their own Discord login); /sp.specify to keep building.
- 🧠 Reflection: The FAQ removes ambiguity; the remaining blocker is purely the Discord
  case-by-case request, which only the user can submit from their own account.

## Evaluation notes (flywheel)

- Failure modes observed: Gmail lists render lazily; snapshots needed waits. The Token Factory
  session had logged out and logged back in automatically through existing Google cookies.
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
