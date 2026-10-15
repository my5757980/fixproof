---
id: 0034
title: ADR Personal Mode NVIDIA Provider
stage: plan
date: 2026-10-15
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.adr
labels: ["adr", "personal-mode", "nvidia-api", "architecture"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: history/adr/0009-personal-mode-nvidia-api-and-local-execution.md
  pr: null
files:
 - history/adr/0009-personal-mode-nvidia-api-and-local-execution.md
 - history/adr/0001-inference-platform-and-model-roles.md
 - history/adr/0003-isolated-execution-and-snapshot-model.md
 - specs/001-verified-fix-agent/plan.md
tests:
 - none
---

## Prompt

```text
/sp.ad personal-mode-nvidia-provider
```

(Typo for `/sp.adr`; run as `/sp.adr personal-mode-nvidia-provider`.)

## Response snapshot

Loaded the planning context (plan D12, spec FR-024, constitution 2.1.0) and the existing ADRs.
The decision cluster (provider selection, NVIDIA API inference with Nemotron roles, defaults
rather than overrides, $0 pricing, the local Docker executor, labels everywhere, the demo guard)
passed the significance test: it touches configuration, the CLI, the demo guard, the
orchestrator's reports, and the benchmark; it had real alternatives; and it will be revisited
(model IDs, free-tier limits, Nebius access).

Created ADR-0009 "Personal Mode: NVIDIA API and Local Execution" with five alternatives (wait
for Nebius or the teammate route, OpenRouter, local models, a multi-provider router, replacing
Nebius). Two existing ADRs conflicted in scope: ADR-0001 ("no other provider is ever used") and
ADR-0003 (Docker executor development-only). Both now say they are amended by ADR-0009 outside
the hackathon configuration and still govern it. plan.md D12 links ADR-0009. No create-adr
script exists, so the ADR was written from the template (as ADR-0001 to ADR-0008 were).

## Outcome

- ✅ Impact: The personal-mode decision and its tradeoffs are on record, and the older ADRs no
  longer contradict the code.
- 🧪 Tests: none (documentation).
- 📁 Files: ADR-0009, ADR-0001 and ADR-0003 status lines, plan.md.
- 🔁 Next prompts: the user's NVIDIA key in `.env`; then T096 (doctor and a first real run).
- 🧠 Reflection: A scoped amendment line in the older ADRs keeps the record consistent without
  rewriting accepted decisions.

## Evaluation notes (flywheel)

- Failure modes observed: none; the decision is clustered and lists alternatives.
- Graders run and results (PASS/FAIL): clustered decision PASS; at least one alternative with
  rationale PASS (five); pros and cons PASS; concise and referenced PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
