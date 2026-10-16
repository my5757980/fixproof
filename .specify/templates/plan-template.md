# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/sp.plan` command. See `.claude/commands/sp.plan.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]  
**Inference Platform**: [Nebius Token Factory (default) or Nebius AI Cloud (requires ADR) - see Constitution I]  
**Model(s)**: [NVIDIA open-source model ID per role (planner, worker), Nemotron preferred, or NEEDS CLARIFICATION]  
**Code Execution**: [Token Factory Sandboxes (default) or Nebius AI Cloud compute (requires ADR) - see Constitution I]  
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]  
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]  
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [single/web/mobile - determines source structure]  
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]  
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]  
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Check each gate against `.specify/memory/constitution.md`. Any unchecked gate MUST be fixed or
justified in Complexity Tracking before proceeding.

- [ ] **I. Eligibility**: LLM calls go to Nebius Token Factory (or Nebius AI Cloud with an ADR)
  by default; code runs and is tested in Token Factory Sandboxes; the core agent loop runs on
  an NVIDIA open-source model (Nemotron preferred), with models assigned by role; model IDs,
  endpoints, and keys come from configuration; dependencies are MIT-compatible. Personal mode
  (NVIDIA API or OpenRouter, local Docker) is used only when explicitly selected and is always
  labeled.
- [ ] **II. Autonomous & verified**: The feature advances the plan → write → run/test → iterate
  loop on real repositories, names its developer job, audience, and problem, reports success
  only with sandbox evidence, and has no canned or mocked behavior in the shipped path.
- [ ] **III. Simplicity**: One service, one agent loop, and few pinned dependencies (or a
  justified exception below); step, branch, cost, and time budgets, bounded retries, schema
  validation of tool arguments, bounded tool output, and sandbox checkpoints are defined.
- [ ] **IV. Transparency**: Every new tool has a name, description, validated schema, and
  documented output; tool calls, sandbox commands, and test results stream to the progress
  view and are recorded in the run trace with sandbox IDs.
- [ ] **V. Quality**: Tests are planned for every tool and agent-loop change (offline, with a
  fake model client and fake sandbox executor); linter, formatter, and type checker are
  configured.
- [ ] **VI. Reproducibility & judge access**: README (including the hackathon highlights),
  `.env.example`, pinned dependencies, the one-command run and test paths, and demo access
  through 2026-12-15 are updated for this feature.
- [ ] **Safety**: Code executes only in the sandbox; actions that leave it are previewed and
  approval-gated; secrets stay out of code, logs, traces, and sandboxes; optional third-party
  tools receive minimal data; the public demo is rate-limited and budget-capped.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/sp.plan command output)
├── research.md          # Phase 0 output (/sp.plan command)
├── data-model.md        # Phase 1 output (/sp.plan command)
├── quickstart.md        # Phase 1 output (/sp.plan command)
├── contracts/           # Phase 1 output (/sp.plan command)
└── tasks.md             # Phase 2 output (/sp.tasks command - NOT created by /sp.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
