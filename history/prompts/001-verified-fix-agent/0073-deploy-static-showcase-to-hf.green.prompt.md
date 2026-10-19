---
id: 0073
title: Deploy Static Showcase to HF
stage: green
date: 2026-10-19
surface: agent
model: claude-opus-5-5
feature: 001-verified-fix-agent
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["deploy", "hugging-face-spaces", "showcase", "static-site", "replays"]
links:
  spec: specs/001-verified-fix-agent/spec.md
  ticket: null
  adr: null
  pr: null
files:
 - src/fixproof/config.py
 - src/fixproof/web/runs.py
 - src/fixproof/web/showcase.py
 - src/fixproof/web/static/app.js
 - src/fixproof/cli.py
 - replays/index.toml
 - replays/flask-empty-blueprint-name.jsonl
 - replays/requests-invalid-url-label.jsonl
 - replays/requests-get-content-length.jsonl
 - tests/unit/test_showcase.py
 - tests/unit/test_run_manager.py
 - tests/integration/test_web_api.py
 - tests/integration/test_cli.py
 - specs/001-verified-fix-agent/contracts/cli.md
 - README.md
 - .env.example
 - .gitignore
 - history/prompts/001-verified-fix-agent/0073-deploy-static-showcase-to-hf.green.prompt.md
tests:
 - tests/integration/test_web_api.py::test_a_showcase_starts_no_live_runs
 - tests/unit/test_run_manager.py::test_the_bundled_replays_are_complete_recorded_runs
 - tests/unit/test_showcase.py (3 tests)
 - tests/integration/test_cli.py::test_showcase_writes_a_static_site_and_keeps_existing_files
 - full offline suite: 457 passed, 10 skipped; ruff, format, mypy clean
 - browser check of the static site locally and on the Space
---

## Prompt

```text
too open karoo browser mayyy mayy login kar detaaa huuuu
kar diaaa haiiii loginnn
```

## Response snapshot

The user logged in to Hugging Face in the browser themselves (account `ms5373268`). Claude
added a server-side showcase mode (`FIXPROOF_SHOWCASE=1`: no live runs, a visitor-facing
reason) and bundled the three verified personal-mode runs as replays, checked first for
secrets and local paths. The new-Space form then showed that Docker Spaces are now paid on
Hugging Face (only Static and Gradio are free), so the plan changed to a static site: the new
`fixproof showcase OUT_DIR` command saves the showcase app's health, samples, and replay
catalog as JSON next to the page, its assets, and the traces, and `app.js` in
`data-mode="static"` reads those files and plays each trace in the browser with the server's
timing (gaps divided by the speed, at most 3 s; `?speed=` 1-20). Tests cover the showcase
refusal, the bundled replays, the builder, and the CLI command.

Checked locally in a browser: a sample click shows the showcase notice and highlights a
replay, the Flask replay plays to Verified with all 223 events, and leaving a replay stops it.
Claude created the Space `ms5373268/fixproof` as a **private** Static Space and uploaded the
ten files through the web page (the first commit attempt did not go through; the second did,
commit c06209f). On the Space, the page loads and a replay plays. The owner makes the Space
public in its settings. The README documents the showcase and how to rebuild it.

## Outcome

- ✅ Impact: FixProof has a free, keyless, serverless showcase on Hugging Face that replays
  real verified runs; the live agent keeps running only on the owner's computer.
- 🧪 Tests: 6 added; 457 passed, 10 skipped.
- 📁 Files: showcase mode and builder, static mode in app.js, three replays, tests, docs.
- 🔁 Next prompts: the owner makes the Space public; later updates rebuild with
  `fixproof showcase` and upload again.
- 🧠 Reflection: check the host's current free tier before planning a deployment; the static
  route turned out simpler than the Docker one.

## Evaluation notes (flywheel)

- Failure modes observed: Docker Spaces are paid now; the browser upload's first commit did not
  go through; uploads work only from files inside the project folder.
- Graders run and results (PASS/FAIL): offline suite PASS; static site in the browser PASS;
  Space page and replay PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
