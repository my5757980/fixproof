---
id: 0006
title: Token Factory Billing Country Pakistan
stage: general
date: 2026-10-04
surface: agent
model: claude-opus-5-5
feature: none
branch: main
user: unknown
command: none (chat)
labels: ["onboarding", "token-factory", "billing", "access-risk", "roman-urdu"]
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
[Pasted Token Factory "Billing details" form: first name, last name, street address, city,
postal code, and billing email were filled in — all personal values redacted here because this
record will be public. The "Country of residence" field was empty.]

   may login kar rahaa thaaaa pak to is mayy haii hii nahii to kia choose karoooo
```

## Response snapshot

Advised, in short Roman Urdu, not to choose any other country: it would misstate residence on a
billing form, a Pakistani card would likely fail verification anyway, and it could get the
account blocked or the entry disqualified. Gave legitimate options: ask on the Nebius Discord
(drafted an English message), find a teammate in a supported country who owns the Token Factory
account and invites the user to their project, and keep building in the meantime. Asked the user
not to paste their home address in chat.

## Outcome

- ✅ Impact: The user avoids a false billing declaration and has a clear path to request access.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: Post the Discord message; report Nebius's answer; continue with /sp.specify.
- 🧠 Reflection: Token Factory access is the project's top risk; the code can be built against a
  fake model client meanwhile, but the final demo must run on Token Factory.

## Evaluation notes (flywheel)

- Failure modes observed: The user shared personal address details in chat; they were redacted
  from this record.
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Explore Token Factory team invitations as a
  legitimate route once a teammate in a supported country is found.
