---
id: 0013
title: Specify Verified Fix Agent
stage: spec
date: 2026-10-10
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: unknown
command: /sp.specify
labels: ["spec", "coding-agent", "verified-fix", "sandboxes", "nemotron", "hackathon"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - specs/001-verified-fix-agent/spec.md
 - specs/001-verified-fix-agent/checklists/requirements.md
tests:
 - none
---

## Prompt

```text
/sp.specify
```

(The command was run with no arguments. Following the agreed workflow, the feature description
drafted earlier in this conversation, "Prompt 1 — /sp.specify", was used as the input. It is
quoted in full in the spec's Input field.)

## Response snapshot

Created branch `001-verified-fix-agent` and wrote `specs/001-verified-fix-agent/spec.md`, which
specifies an autonomous agent that fixes bugs in real public Python repositories and proves each
fix with sandbox test evidence. Re-ordered the stories for the deadline: P1 fix with proof (MVP),
P2 live transparent run with a public judge demo, P3 parallel hypotheses from a shared sandbox
state, P4 take the fix home with approval at the boundary. Wrote 23 testable functional
requirements, including strict "Verified" labeling (three consecutive passes plus no baseline
regressions), no weakening of existing tests, credential isolation, and prompt-injection
resistance. Isolated the mandated platform constraints (Nebius Token Factory, Sandboxes,
Nemotron) in their own section, listed 10 key entities, 8 measurable success criteria, edge cases,
assumptions (including name candidates ForkFix, FixProof, ReproFix), and dependencies (pending
Token Factory access). The quality checklist passed in two passes, with no clarification markers.

## Outcome

- ✅ Impact: The feature spec is ready for /sp.clarify or /sp.plan.
- 🧪 Tests: none (specification stage)
- 📁 Files: spec.md and checklists/requirements.md created
- 🔁 Next prompts: /sp.clarify (optional), then /sp.plan with the drafted plan prompt.
- 🧠 Reflection: Moving the live demo to P2 aligns the MVP with the hackathon's working-demo
  requirement; the strict "Verified" definition is the core differentiator and must survive
  planning unchanged.

## Evaluation notes (flywheel)

- Failure modes observed: /sp.specify was invoked with empty arguments. The drafted description
  from the conversation was used instead of erroring, which the user had already approved as the
  workflow.
- Graders run and results (PASS/FAIL): Spec quality checklist, 16/16 items PASS after one fix
  (FR-020 acceptance scenario).
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Run /sp.clarify to confirm demo limits and benchmark
  task selection before planning.
