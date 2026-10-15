---
id: 0033
title: Implement Personal Mode NVIDIA API
stage: green
date: 2026-10-15
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: /sp.implement
labels: ["implementation", "phase-8", "personal-mode", "nvidia-api", "tdd"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: history/adr/0001-inference-platform-and-model-roles.md
  pr: null
files:
 - src/fixproof/config.py
 - src/fixproof/cli.py
 - src/fixproof/sandbox/factory.py
 - src/fixproof/agent/orchestrator.py
 - src/fixproof/bench/runner.py
 - .env.example
 - .env.personal.example
 - .gitignore
 - README.md
 - specs/001-verified-fix-agent/spec.md
 - specs/001-verified-fix-agent/plan.md
 - specs/001-verified-fix-agent/tasks.md
 - specs/001-verified-fix-agent/quickstart.md
tests:
 - tests/unit/test_config.py (+11 personal mode, env examples)
 - tests/unit/test_factory.py (+1 demo refuses personal mode)
 - tests/integration/test_cli.py (+1 doctor in personal mode)
 - tests/integration/test_orchestrator_single.py (+1 report flag)
 - tests/integration/test_bench_runner.py (+1 summary label)
---

## Prompt

```text
haaaaaa shuruuuu karooooo
```

## Response snapshot

After the constitution amendment (2.1.0, PHR 0032), added Phase 8 to tasks.md (T092–T097),
FR-024 to the spec, and D12 to the plan, then implemented personal mode tests first:

- `FIXPROOF_PROVIDER=nvidia` switches the defaults to NVIDIA's API
  (`https://integrate.api.nvidia.com/v1/`, key in `NVIDIA_API_KEY`) and the Nemotron IDs
  `nvidia/nemotron-3-ultra-550b-a55b`, `nvidia/nemotron-3-super-120b-a12b`, and
  `nvidia/nemotron-3.5-lightning-30b-a3b` (from third-party documentation; `doctor` verifies them).
  Explicitly set values still win; role models in personal mode are priced at $0.
- Labels: `doctor` names `NVIDIA_API_KEY` and says "personal mode, not the hackathon platform";
  `fix` and `bench run` print the note; every report gets a "Not the hackathon platform" flag;
  benchmark summaries carry it; the hosted demo refuses personal mode unless
  `FIXPROOF_ALLOW_DEV=1`.
- Found a trap and fixed it: copying `.env.example` and only switching the provider would keep
  its explicit Token Factory URL and model IDs, which override the personal defaults. Added
  `.env.personal.example` (with a test that it selects personal mode) and a test that
  `.env.example` lists every setting.
- Created the user's `.env` from `.env.personal.example` (gitignored); the key is still a
  placeholder for the user to fill in.

**Checkpoint**: 409 passed, 10 skipped; ruff, format, and mypy strict (41 files) clean. Commit
`f3572b5`. T096 (real run with the key) and T097 (Docker speed) remain.

## Outcome

- ✅ Impact: FixProof can run without Nebius as soon as the user has an NVIDIA key.
- 🧪 Tests: 409 passed offline.
- 📁 Files: provider setting, labels, personal env example, docs.
- 🔁 Next prompts: the user creates the key at build.nvidia.com and pastes it into `.env`; then
  `doctor` and a first real run (T096), and Docker speed work from measurements (T097).
- 🧠 Reflection: A config default that explicit example lines silently override is a usability
  bug; a test on the example file itself catches it.

## Evaluation notes (flywheel)

- Failure modes observed: config.py had CRLF line endings in the working copy (from an older
  checkout); normalized to LF.
- Graders run and results (PASS/FAIL): pytest PASS; ruff PASS; ruff format PASS; mypy PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): run `doctor` with a real NVIDIA key to confirm the
  model IDs before the first real run.
