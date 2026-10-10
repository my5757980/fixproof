---
id: 0005
title: Nebius Builder Program Credits Next Steps
stage: general
date: 2026-10-04
surface: agent
model: claude-opus-5-5
feature: none
branch: main
user: unknown
command: none (chat)
labels: ["onboarding", "credits", "token-factory", "tavily", "roman-urdu"]
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
Welcome to the AI Builder Program!
Inbox

Nebius <no-reply@nebius.com> Unsubscribe
Sat, Oct 3, 11:25 AM (1 day ago)
to me

logo-nebius
Hello [name redacted],

Welcome to the Nebius AI Builder Program! You’re joining a community of builders, founders and engineers creating AI on their own terms.

Together with Cognition, Composio, Hugging Face, LangChain, MiniMax, NVIDIA, OpenHands, Prime Intellect, Qwen, Tavily, Toloka and our growing ecosystem of partners, we’re bringing together the models, tools and expertise to help you build, ship and scale AI systems.

Claim your credits and set up your tools
Explore models, frameworks, search, and evaluation tools to find what works best for you.

Your $25 Nebius Token Factory credit is already coming your way in a separate email!

Claim your credits from our partners using the links below:

$100 in LangSmith credit from LangChain
If the program name isn’t prefilled, enter AI Builder Program. 
$25 in Tavily credit
$50 in Toloka credit and $50 in Tandem credit
Partner terms and conditions apply to each offer.

Start with working code
Put your credits to work with runnable cookbooks and blueprints. Build your first agent, try a new model, or add retrieval and evaluation to a project already underway.

Explore the cookbook library →

Build your skills and get certified
Learn to build AI agents with open models and developer tools through free courses from Nebius Academy and NVIDIA. As an AI Builder Program member, you can earn your first Nebius certification for just $1.

Explore Nebius Certification →

Get support and meet fellow builders
Bring your questions to regular office hours and build sessions with Nebius engineers. Get help debugging, tuning performance and moving past roadblocks.

Join the community on Discord and at meetups, workshops, and hackathons around the world. Share your project, get feedback and connect with people working on similar problems.

As your project grows, the program grows with you — with production infrastructure, connections to the Nebius Startup Program and opportunities to showcase your work through Nebius and partner channels.

We can’t wait to see what you build!

 
Regards,
The Nebius AI Builder Program team

Follow us to stay tuned:

youtube-1 linkedin-1 discord-1 x-1-2
Nebius AI Cloud    Blog
Nebius Token Factory    Events
© 2026 Nebius B.V., Schiphol Boulevard 165, 1118 BG Schiphol, NL, Netherlands.

You are receiving this because you’ve filled out a Nebius registration form. 

Privacy Policy | Unsubscribe | Manage preferences
```

## Response snapshot

Explained in short Roman Urdu that joining the AI Builder Program is good news: a $25 Token
Factory credit arrives by separate email and a $25 Tavily credit can be claimed. LangSmith,
Toloka, and Tandem credits are not needed for this project. Listed next steps: open the credit
email and confirm that Token Factory login and credit activation work (billing country), fill the
hackathon promo form for another $25, claim the Tavily credit, request Sandboxes beta access,
create an API key and keep it out of chat, then run /sp.specify.

## Outcome

- ✅ Impact: The user knows which credits matter and the access checks to finish before coding.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: Report whether Token Factory credit activation worked; run /sp.specify.
- 🧠 Reflection: Builder Program membership does not confirm Token Factory billing access; the
  credit activation step is the real test.

## Evaluation notes (flywheel)

- Failure modes observed: The user pasted an email without a question; the intent was inferred
  as "what does this mean, what next".
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Ask the user to report the credit activation result
  in one line.
