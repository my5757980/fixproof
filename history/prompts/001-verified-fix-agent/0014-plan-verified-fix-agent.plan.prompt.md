---
id: 0014
title: Plan Verified Fix Agent
stage: plan
date: 2026-10-10
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: unknown
command: /sp.plan
labels: ["plan", "architecture", "token-factory", "sandboxes", "contree", "nemotron", "research"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - specs/001-verified-fix-agent/plan.md
 - specs/001-verified-fix-agent/research.md
 - specs/001-verified-fix-agent/data-model.md
 - specs/001-verified-fix-agent/quickstart.md
 - specs/001-verified-fix-agent/contracts/openapi.yaml
 - specs/001-verified-fix-agent/contracts/agent-tools.md
 - specs/001-verified-fix-agent/contracts/trace-events.md
 - specs/001-verified-fix-agent/contracts/cli.md
 - CLAUDE.md
tests:
 - none
---

## Prompt

```text
/sp.plan
```

(The command was run with no arguments. Following the agreed workflow, the plan prompt drafted
earlier in this conversation, "Prompt 3 — /sp.plan", was used as the input: Python 3.12 + uv,
Typer CLI, FastAPI + SSE + static UI, Pydantic; Token Factory via the openai SDK with Nemotron
planner/worker roles and fallback; Sandboxes via contree-sdk behind an Executor interface; GitHub
REST; optional Tavily; demo hosting with budgets and labeled replay; JSONL traces; pytest, ruff,
mypy, CI, and a benchmark; follow the constitution.)

## Response snapshot

Ran setup-plan.ps1 and researched the unknowns against the live docs:

- **Sandboxes SDK**: `contree-sdk` clients, the `run()` signature with `timeout`, `files`,
  `disposable`, and `truncate_output_at`, `apply_files`, `read`/`ls`, branching, the CLI base URL
  `https://api.tokenfactory.nebius.com/sandboxes` plus project ID, and beta limits.
- **Models**: verified Nemotron 3 IDs and prices (Ultra $1/$3, Super $0.30/$0.90, Nano
  $0.06/$0.24) from Nebius pages and the cookbook.
- **Tavily**: the search API.
- **Local tooling**: Python 3.12.6, uv 0.9.5, Docker 29.1.3, git 2.50.1.

Wrote `research.md` (15 decisions, VERIFY-ON-ACCESS list, cost model of about $0.25 per run) and
`plan.md`:

- Technical Context;
- Constitution Check, pre- and post-design: all gates PASS;
- source tree;
- architecture and run lifecycle;
- key design decisions D1–D8;
- milestones M0–M5 with feature freeze on Oct 23, submission on Oct 29, and an access gate on
  Oct 20;
- top 3 risks;
- Complexity Tracking: no violations.

Also wrote:

- `data-model.md`: entities, labeling rule, state machine.
- Contracts: `openapi.yaml`, `agent-tools.md` (9 tools with guards), `trace-events.md`, and
  `cli.md`.
- `quickstart.md`, which doubles as the validation script.

Updated the CLAUDE.md agent context. The script did not add the Recent Changes entry because of a
heading-handling bug, so that entry was added manually.

## Outcome

- ✅ Impact: Implementation-ready design for FixProof that respects every constitution gate and
  the hackathon rules.
- 🧪 Tests: none (planning stage); the test strategy is defined (unit, contract, integration,
  opt-in live).
- 📁 Files: 8 planning artifacts plus a CLAUDE.md context update.
- 🔁 Next prompts: /sp.tasks, then /sp.analyze, then /sp.implement. Optionally /sp.adr for the
  runtime stack and the verification policy.
- 🧠 Reflection: Putting the verification label in the harness, not the model, is the design's
  core integrity guarantee. The pending Nebius access is the only gating risk.

## Evaluation notes (flywheel)

- Failure modes observed: /sp.plan was invoked with empty arguments, so the drafted prompt was
  used. update-agent-context.ps1 consumes the "## Recent Changes" heading inside the
  Active Technologies branch, so no change entry was written; it was added manually. WebFetch
  summarizes instead of returning verbatim text, so key facts were cross-checked across two or
  more sources.
- Graders run and results (PASS/FAIL): Constitution Check pre-design PASS; post-design PASS; no
  unresolved NEEDS CLARIFICATION markers (grep).
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Fix update-agent-context.ps1 so the Recent Changes
  heading is handled even when it directly follows the Active Technologies section.
