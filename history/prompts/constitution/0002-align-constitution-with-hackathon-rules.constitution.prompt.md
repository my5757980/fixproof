---
id: 0002
title: Align Constitution With Hackathon Rules
stage: constitution
date: 2026-10-03
surface: agent
model: claude-opus-5-5
feature: none
branch: none
user: unknown
command: /sp.constitution (amendment via chat)
labels: ["constitution", "hackathon", "devpost-rules", "token-factory-sandboxes", "nemotron", "judging"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - .specify/memory/constitution.md
 - .specify/templates/plan-template.md
 - .specify/templates/spec-template.md
 - .specify/templates/tasks-template.md
 - .claude/commands/sp.tasks.md
tests:
 - none
---

## Prompt

```text
achaaa grok aik kam karoooo ya link haiii   [REDACTED: a platform.claude.com OAuth callback URL containing a one-time login code; removed because this record will live in a public repository]  is link ko open karooo ya is hackathone ka haii jis mayy manayy participate kiaaaaa haiiii to tum jaoooo is kayy aik aikk section ko ful scan karoo deeplyyy word by word line by line kia haii kia bananaa haii sara section kuch bhi miss mat karnaaaa phit tum dekh lenaa constitution sahi banaya haiiii sahii banaya hai to theek warna tum dekh lena jo change add karna hoooo or phir agayy sayy mayyy specify plan tasks impemented commands chaloo gaaaa tum ko aik aik kar kayyy do gaaa tum khud is project kayy related prompts banaaaa phir end mayyy poora implemented
```

## Response snapshot

Did not open the pasted link: it was a Claude OAuth login callback containing a one-time code,
not the hackathon page. Located the official Devpost site and reviewed the overview, rules,
resources, updates (judging, winning-project, kickoff posts), and forum threads, plus the Token
Factory docs (OpenAI-compatible inference, function calling, Sandboxes/ConTree SDK). Found three
gaps in constitution v1.0.0: no Token Factory Sandboxes execution (the track is "agents that
write, run, and test code in Token Factory"), a per-action approval rule that conflicts with the
judges' "minimal human input" bar, and missing submission deliverables (working demo with judge
access through 2026-12-15, video under 3 minutes, required feedback, Built With, deadline).
Amended to v2.0.0 (MAJOR) and synced the plan, spec, and tasks templates and the /sp.tasks
command. Drafted ready-to-run prompts for /sp.specify, /sp.plan, /sp.tasks, and /sp.implement,
and flagged the Token Factory billing block reported for Pakistan-based participants.

## Outcome

- ✅ Impact: Constitution v2.0.0 now matches the official rules, judging criteria, track bar,
  submission checklist, and deadlines; the templates enforce the new gates.
- 🧪 Tests: none (governance change); constitution validated for placeholders, line length, and
  trailing whitespace.
- 📁 Files: 5 modified (constitution, plan/spec/tasks templates, /sp.tasks command).
- 🔁 Next prompts: /sp.specify with the drafted feature prompt, then /sp.clarify, /sp.plan,
  /sp.tasks, /sp.analyze, /sp.implement.
- 🧠 Reflection: The judges' track guidance ("plans, writes, tests, and iterates on a real repo
  with minimal human input") and the Sandboxes product reshaped the safety model from per-action
  approval to sandboxed autonomy with approval at the boundary.

## Evaluation notes (flywheel)

- Failure modes observed: The user pasted an OAuth callback URL instead of the hackathon link;
  it was not opened, and the official page was found by search. WebFetch returns summaries
  rather than verbatim text for long pages, so key sections were re-fetched with narrower,
  quote-focused prompts. Several forum questions had no official answers (organizers point to
  the Nebius Discord).
- Graders run and results (PASS/FAIL): Placeholder scan PASS; line length under 100 chars PASS;
  trailing whitespace PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Recheck the Devpost rules and updates pages the
  week before submission and amend the constitution if organizer guidance changed.
