---
id: 0010
title: Scan Nebius Emails For Access Solution
stage: general
date: 2026-10-04
surface: agent
model: claude-opus-5-5
feature: none
branch: main
user: unknown
command: none (chat)
labels: ["onboarding", "token-factory", "billing", "gmail", "playwright", "tavily", "roman-urdu"]
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
[Pasted again: the Nebius "Welcome to the AI Builder Program!" email body (greeting name
redacted); same content as PHR 0005.]

  to nahii is gmail mayy hii deplyy dekhoo jo jo click able link haii open karoo mujayy to koi yahii sayy solution lag rahaaa haiii check karoo deeplyyyy
```

## Response snapshot

Opened the user's Gmail in the Playwright browser, at the user's request, and followed every
content link in the Nebius welcome email (unsubscribe and preference links were not clicked):
office hours → nebius.com/events; Discord invite; Tavily Nebius Builders page ($25 free, ~2.5K
calls, no card required, claim form); cookbook library; certification; NVIDIA x Nebius Academy
agentic AI course; meetups → events; Toloka event page; LangSmith Airtable redemption form. Also
read the separate "Here is your promo code from Nebius" email: a $25 Token Factory code (value
not recorded here), apply before 2026-12-31, no expiry once applied. Applying it requires
sign-in, billing address or card for fraud checks, then Profile → Top up, with support in the
Nebius Discord #token-factory-support channel. The Devpost "You're in!" email only repeats the
promo form, Builders Program, Discord, meetups, and rules links. Conclusion: no link bypasses
the Token Factory billing-country requirement. The best official channel is Discord
#token-factory-support. The Tavily credit is claimable now without a card.

## Outcome

- ✅ Impact: Every email link was checked; the user knows the promo code is valid until
  2026-12-31, that Tavily works without a card, and where official support lives.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: Post in #token-factory-support; claim Tavily credit; /sp.specify.
- 🧠 Reflection: Marketing emails route through tracking redirects; resolving each in the browser
  was needed to see the real destinations.

## Evaluation notes (flywheel)

- Failure modes observed: Gmail search results sometimes render lazily and do not appear in
  accessibility snapshots; a screenshot plus text find worked around it.
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
