---
id: 0007
title: Check Token Factory Access Without Billing
stage: general
date: 2026-10-04
surface: agent
model: claude-opus-5-5
feature: none
branch: main
user: unknown
command: none (chat)
labels: ["onboarding", "token-factory", "billing", "playwright", "roman-urdu"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .gitignore
tests:
 - none
---

## Prompt

```text
to nahii claudee likin jab logon nahii kiaa thaaa is ka main pagee sab kuch tab bhi samnayy ayaaa thaaa check karoo seen kiaa haiii
```

## Response snapshot

Checked with Playwright in the user's logged-in browser session. The Token Factory home page
(model list, docs, links) is public, but /playground, /project/api-keys, and /sandboxes all
redirect to the "Billing details" form. Without completed billing there is no API key, no
Playground, and no Sandboxes. Explained in short Roman Urdu that the home page is like a shop
window and that the real use is locked behind billing. Repeated the legitimate options (Nebius
Discord, a teammate in a supported country). Added `.gitignore` for `.env` files and the
`.playwright-mcp/` folder, since the screenshots contain personal data.

## Outcome

- ✅ Impact: Confirmed that billing completion is mandatory for any Token Factory use; the repo
  is protected from committing secrets and browser screenshots.
- 🧪 Tests: none
- 📁 Files: .gitignore (new)
- 🔁 Next prompts: Post the Discord message; continue with /sp.specify.
- 🧠 Reflection: Public landing pages do not imply usable access; verify the gated pages directly.

## Evaluation notes (flywheel)

- Failure modes observed: Playwright writes snapshots into the project root by default; they are
  now gitignored.
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
