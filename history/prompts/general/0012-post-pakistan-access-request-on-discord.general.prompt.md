---
id: 0012
title: Post Pakistan Access Request On Discord
stage: general
date: 2026-10-10
surface: agent
model: claude-opus-5-5
feature: none
branch: main
user: unknown
command: none (chat)
labels: ["onboarding", "token-factory", "billing", "discord", "support-request", "playwright", "roman-urdu"]
links:
  spec: null
  ticket: https://discord.com/channels/1222156136380235877/1387298727835861113/threads/1558354806010019901
  adr: null
  pr: null
files:
 - none
tests:
 - none
---

## Prompt

```text
kar diaaa hai login
```

## Response snapshot

With the user logged into Discord in the Playwright browser, opened the Nebius server and finished
its onboarding question (chose "Token Factory" notifications only). Opened #token-factory-support,
which is a forum channel. Read existing posts from participants in India, the Philippines, and
Nepal with the same problem, and the staff reply from Jasmine White (2026-10-09) in the
Philippines thread: Nebius has asked an internal team to consider adding unsupported countries,
with no timeline because of business and compliance approvals; billing information must be
accurate; updates will be shared in that thread. Then created a new forum post with the "help"
tag, as the user had asked. Title: "Pakistan missing from Token Factory billing country list
(hackathon participant)". The body explains hackathon and Builder Program membership, the Oman →
Poland gap, the refusal to enter an incorrect country, and the FAQ's case-by-case process. It
asks Nebius to add Pakistan to the request and for any interim approved access to Token Factory
and Sandboxes, and offers to share the account or org ID privately. The post was published and
is followed for notifications.

## Outcome

- ✅ Impact: The official case-by-case support request is filed; the user will be notified of
  replies.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: Watch the Discord post for Nebius replies; /sp.specify to keep building
  against a fake model client.
- 🧠 Reflection: The forum already had a staff answer with no timeline, so the project plan must
  assume access could arrive late; build and test offline first.

## Evaluation notes (flywheel)

- Failure modes observed: The channel is a forum, not a chat channel, so a titled post with a tag
  was required. A Discord promo dialog had to be closed first.
- Graders run and results (PASS/FAIL): Post published and visible with the "help" tag (PASS).
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
