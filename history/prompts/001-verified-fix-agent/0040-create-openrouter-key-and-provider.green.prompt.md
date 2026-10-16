---
id: 0040
title: Create OpenRouter Key and Provider
stage: green
date: 2026-10-15
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["personal-mode", "openrouter", "api-key", "config"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - src/fixproof/config.py
 - src/fixproof/cli.py
 - src/fixproof/llm/client.py
 - src/fixproof/sandbox/factory.py
 - tests/unit/test_config.py
 - tests/unit/test_factory.py
 - tests/integration/test_cli.py
 - .env.example
 - .env.personal.example
tests:
 - tests/unit/test_config.py, tests/unit/test_factory.py, tests/unit/test_docker_executor.py, tests/integration/test_cli.py (78 passed)
---

## Prompt

```text
login kar diaaa haiiiii
```

## Response snapshot

The user signed in to OpenRouter in the browser. Claude created an API key named "fixproof"
(90-day expiry, $1 credit limit). Copying the key from the page into `.env` was blocked by the
auto-mode classifier as credential materialization; Claude did not work around it. Instead it
added an `OPENROUTER_API_KEY=` line to the ignored `.env`, opened it in Notepad, and asked the
user to copy and paste the key themselves.

Then implemented OpenRouter as a second personal-mode provider: a provider table in `config.py`
(`PERSONAL_PROVIDERS`: endpoint, key variable, key page, and role models), `FIXPROOF_PROVIDER=
openrouter` with `OPENROUTER_API_KEY` (redacted), the `:free` Nemotron IDs, $0 only for `:free`
models, the provider named in the platform note, the shared key lookup in `doctor`, a
provider-neutral demo guard and "no model available" error, and both `.env` examples. The
constitution was amended first (2.2.0, PHR 0041).

## Outcome

- ✅ Impact: FixProof can run on NVIDIA Nemotron models through OpenRouter while NVIDIA's account
  verification is pending.
- 🧪 Tests: 78 passed in the touched suites; ruff, format, mypy clean.
- 📁 Files: config, CLI doctor, client error text, demo guard, tests, `.env` examples.
- 🔁 Next prompts: the user pastes the key; `fixproof doctor`; one real run (T096).
- 🧠 Reflection: a provider table kept the change small and made the rules testable per provider.

## Evaluation notes (flywheel)

- Failure modes observed: credential handling must stay with the user when auto mode blocks it.
- Graders run and results (PASS/FAIL): unit and integration tests PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
