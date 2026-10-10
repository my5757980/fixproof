---
id: 0001
title: Ratify Hackathon Coding Agent Constitution
stage: constitution
date: 2026-09-28
surface: agent
model: claude-opus-5-5
feature: none
branch: none
user: unknown
command: /sp.constitution
labels: ["constitution", "hackathon", "nebius", "nemotron", "coding-agent", "governance"]
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
# Constitution

You are helping me build a high-quality submission for the Nebius x NVIDIA Global AI Hackathon.

## Core Rules
- The project MUST run on Nebius Token Factory or Nebius AI Cloud
- Must use at least one NVIDIA open-source model (prefer Nemotron)
- Track: Coding and Agentic Engineering
- Goal: Build a practical Coding Agent that can help developers write, understand, debug, and improve code
- Code must be production-quality, clean, and well-documented
- Use open-source license (MIT preferred)
- Focus on real usefulness, not just demo features

## Principles
- Prefer simple and reliable architecture over complex over-engineering
- Make tool use and agent reasoning clear
- Strong README is mandatory
- Everything should be reproducible
```

## Response snapshot

Ratified constitution v1.0.0 from the unfilled template with six principles: I. Hackathon
Eligibility & Platform Compliance (NON-NEGOTIABLE), II. Real Developer Usefulness Over Demo
Features, III. Simple, Reliable Architecture, IV. Transparent Tool Use & Agent Reasoning,
V. Production-Quality, Documented Code, VI. Reproducibility & a Strong README. Added Security &
Safety Requirements, Development Workflow & Quality Gates, and Governance sections. Propagated
the principles to plan-template (concrete Constitution Check gates, Inference Platform and
Model(s) fields, stale workflow path fixed), spec-template (Developer Job field per story), and
tasks-template plus the /sp.tasks command (tests required for tools and agent-loop changes;
config, trace, README, and fresh-clone tasks).

## Outcome

- ✅ Impact: Project constitution ratified at v1.0.0; SDD templates now gate plans on hackathon
  eligibility, usefulness, simplicity, transparency, quality, reproducibility, and safety.
- 🧪 Tests: none (governance/documentation change); constitution validated for placeholders,
  line length, and trailing whitespace.
- 📁 Files: 5 modified (constitution, plan/spec/tasks templates, /sp.tasks command).
- 🔁 Next prompts: /sp.specify for the first coding-agent feature; confirm in /sp.plan research
  that the chosen Nemotron model is served on Nebius Token Factory with tool calling; create an
  MIT LICENSE and README skeleton.
- 🧠 Reflection: Encoding the hackathon eligibility rules as a NON-NEGOTIABLE principle plus plan
  gates makes compliance checkable at plan time instead of at submission time.

## Evaluation notes (flywheel)

- Failure modes observed: The run was interrupted once (two parallel Bash reads were rejected
  while the user switched model and effort, then resumed with "continue"); resumed using
  Read/Grep. `.specify/scripts/bash/create-phr.sh` does not exist (only PowerShell scripts
  ship), so this PHR was written agent-natively. The project is not a git repository, so branch
  and user are unavailable.
- Graders run and results (PASS/FAIL): Placeholder scan PASS (only intentional template slot
  names remain inside the Sync Impact Report comment); line length under 100 chars PASS;
  trailing whitespace PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Add a PowerShell create-phr script, or point the
  command files at the agent-native path, so PHR creation no longer depends on the fallback.
