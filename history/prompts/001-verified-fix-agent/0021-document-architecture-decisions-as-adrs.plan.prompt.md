---
id: 0021
title: Document Architecture Decisions As ADRs
stage: plan
date: 2026-10-11
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.adr
labels: ["adr", "architecture", "decisions", "verification", "sandboxes"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: history/adr/0001-inference-platform-and-model-roles.md
  pr: null
files:
 - history/adr/0001-inference-platform-and-model-roles.md
 - history/adr/0002-agent-tool-interface-and-harness-guards.md
 - history/adr/0003-isolated-execution-and-snapshot-model.md
 - history/adr/0004-harness-verification-and-outcome-labels.md
 - history/adr/0005-run-lifecycle-planning-and-cancellation.md
 - history/adr/0006-parallel-hypotheses-on-sandbox-branches.md
 - history/adr/0007-unified-event-stream-trace-and-replay.md
 - history/adr/0008-judge-demo-hosting-and-access-control.md
 - specs/001-verified-fix-agent/data-model.md
 - specs/001-verified-fix-agent/plan.md
tests:
 - none added (documentation only); the full suite was re-run: 287 passed, 7 skipped
---

## Prompt

```text
/sp.adr
```

(No arguments. It followed the previous suggestion to document the verification labeling rule,
and was run over all planning artifacts.)

## Response snapshot

Loaded plan.md, research.md, data-model.md, and the contracts. No ADRs existed. The
`create-adr.sh` script is not present in this repository (only PowerShell scripts exist), so each
ADR was created directly from `.specify/templates/adr-template.md` with sequential IDs.

The eleven plan decisions (D1–D11) were clustered into 8 ADRs; each passed the three-part test
(long-term impact, real alternatives, cross-cutting scope):

1. ADR-0001 Inference Platform and Model Roles (D1)
2. ADR-0002 Agent Tool Interface and Harness Guards (D2)
3. ADR-0003 Isolated Execution and Snapshot Model (D3, D4, D10)
4. ADR-0004 Harness Verification and Outcome Labels (D5, plus three refinements found during
   implementation)
5. ADR-0005 Run Lifecycle, Two-Stage Planning, and Cancellation (D9)
6. ADR-0006 Parallel Hypotheses on Sandbox Branches (D6, planned for Phase 5)
7. ADR-0007 Unified Event Stream, Trace, and Replay (D7)
8. ADR-0008 Judge Demo Hosting and Access Control (D8, D11, planned for Phase 4)

Every ADR lists alternatives with reasons and both positive and negative consequences, and links
to the spec, the plan, research items, and the tests that provide evidence. One inconsistency was
resolved: data-model.md now states the refined labeling rule from ADR-0004 (flaky tests excluded
only from the regression check, "prior tests" means prior passing tests, and changed reproduction
tests count as modified test files). plan.md maps D1–D11 to the ADRs. No conflicts with existing
ADRs (there were none).

## Outcome

- ✅ Impact: The main architecture decisions are recorded with their reasons and trade-offs, so
  later changes (for example, Nebius hosting replacing Hugging Face Spaces) can supersede a
  specific ADR.
- 🧪 Tests: Documentation only; the full suite still passes (287 passed, 7 skipped).
- 📁 Files: 8 new ADRs; data-model.md and plan.md updated.
- 🔁 Next prompts: Phase 4 (User Story 2, the web demo) with `/sp.implement`; T054 once Docker
  Desktop runs and a Token Factory key exists.
- 🧠 Reflection: Writing ADR-0004 surfaced that data-model.md still described the pre-implementation
  labeling rule; recording decisions also checks documents against the code.

## Evaluation notes (flywheel)

- Failure modes observed: the command expects `create-adr.sh`, which this repository does not
  have; the template was used directly instead.
- Graders run and results (PASS/FAIL): ADR checklist (clustered decision, at least one
  alternative with reasons, pros and cons, concise) PASS for all 8; no unresolved placeholders;
  every referenced file and link exists.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): add a small PowerShell `create-adr.ps1` that
  allocates the next ID, so future ADRs follow the scripted path.
