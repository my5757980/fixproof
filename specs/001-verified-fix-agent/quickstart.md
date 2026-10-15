# Quickstart: Verified Fix Agent ("FixProof", working name)

**Feature**: `001-verified-fix-agent` | This file is both the developer quickstart and the
validation script for the user stories. The README Quickstart is derived from it (Constitution
VI).

## 0. Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/). Run every command from the repository root.
- A Nebius Token Factory account with credits, plus an API key. Create the key at
  tokenfactory.nebius.com → API keys.
- Token Factory Sandboxes (beta) access. Request it at tokenfactory.nebius.com/sandboxes/about.
  You also need your Sandboxes project ID.
- Optional: `GITHUB_TOKEN` (read-only) for higher GitHub API limits, and `TAVILY_API_KEY` for web
  search.
- Optional, development only: Docker, if you need the dev executor while Sandboxes access is
  pending.

## 1. Install and configure

```bash
uv sync                      # creates .venv from uv.lock
cp .env.example .env         # then edit .env (never commit it)
uv run fixproof doctor       # checks keys, model IDs (/v1/models), and sandbox access
```

Minimum `.env` for real runs:

```dotenv
NEBIUS_API_KEY=...                         # Token Factory inference
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
FIXPROOF_PLANNER_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b
FIXPROOF_WORKER_MODEL=nvidia/nemotron-3-super-120b-a12b
FIXPROOF_FALLBACK_MODEL=nvidia/nvidia-nemotron-3-nano-30b-a3b
CONTREE_URL=https://api.tokenfactory.nebius.com/sandboxes
CONTREE_PROJECT=...                        # Sandboxes project ID
# CONTREE_TOKEN=...                        # only if different from NEBIUS_API_KEY
```

`doctor` must report every check as OK. Each failed check prints the exact variable to fix.

## 2. Run the tests (offline, no credentials)

```bash
uv run pytest                 # unit + contract + integration tests with fake model and fake sandbox
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

Expected: all tests pass with no network access. Live tests are skipped unless `FIXPROOF_LIVE=1`.

## 3. Validate User Story 1: fix with proof (CLI)

```bash
uv run fixproof fix --repo https://github.com/<owner>/<repo> --ref <sha-before-fix> \
  --issue https://github.com/<owner>/<repo>/issues/<n>
```

Use one of the curated sample tasks listed in `src/fixproof/web/samples.toml` for a known-good
case.

Check that:

- the plan appears before any edit;
- every step streams with its purpose;
- `runs/<run_id>/` contains `trace.jsonl`, `report.md`, `report.json`, and `patch.diff`;
- `report.md` shows label **Verified**, the reproduction test failing before and passing 3× after,
  no regressions, and a root cause with file and line citations;
- re-running the evidence independently (`git apply patch.diff` on a fresh checkout at the same
  SHA, then `pytest <repro test>`) passes (SC-002);
- the exit code is `0`.

Negative checks:

- `--bug "some behavior that cannot be reproduced"` ends with **Not verified**, stop reason
  `not_reproducible`, and exit code `40`.
- `--max-steps 5` on a hard task ends with stop reason `budget_steps`, partial results, and exit
  code `30`.
- Press Ctrl+C mid-run: the run stops within 10 seconds and partial results are written.

## 4. Validate User Story 2: live demo

```bash
uv run fixproof serve --port 7860
# open http://localhost:7860
```

Check that:

- a one-click sample shows the plan within 30 seconds;
- events stream live, and Stop works within 10 seconds;
- the patch downloads;
- when the visitor limit is reached (set `FIXPROOF_DEMO_RUNS_PER_VISITOR=1` to test), the page
  offers a **labeled REPLAY**;
- a private or oversized repository is rejected with a clear reason.

## 5. Validate User Story 3: parallel hypotheses

```bash
uv run fixproof fix --repo ... --issue ... --parallel 3
```

Check that `report.md` contains a hypothesis table (statement, outcome, changed lines, why the
winner won) and that no more than 3 branches ran at once (see the `sandbox_op` events in
`trace.jsonl`).

## 6. Validate User Story 4: take the fix home

```bash
uv run fixproof apply runs/<run_id> --to ../local-checkout   # shows diff + evidence, asks [y/N]
uv run fixproof pr runs/<run_id>                              # uses YOUR GITHUB_TOKEN, asks [y/N]
```

Answering `N` changes nothing.

## 7. Benchmark (FR-023, SC-001, SC-002, SC-007)

```bash
uv run fixproof bench run --tasks bench/tasks.toml --compare-single
uv run fixproof bench report bench/results/<date>
```

The results table (verified rate, independent re-check, hidden-test agreement, single versus
parallel) is copied into the README.

## 8. Deploy the judge demo (Hugging Face Spaces, Docker)

```bash
docker build -t fixproof-demo .
docker run -p 7860:7860 --env-file .env fixproof-demo        # local smoke test
```

Then create a Docker Space, push the repository, and set the `.env` values as **Space secrets**.
**Never** set `FIXPROOF_ALLOW_DEV` or a non-Nebius `NEBIUS_BASE_URL` there. Verify that
`/api/health` reports `live_runs_available: true` and `executor: contree`.

## Personal mode (constitution 2.1.0, FR-024)

```bash
cp .env.personal.example .env      # FIXPROOF_PROVIDER=nvidia, NVIDIA_API_KEY, FIXPROOF_EXECUTOR=docker
uv run fixproof doctor             # key set, model IDs listed by NVIDIA's API, Docker reachable
FIXPROOF_BASE_IMAGE=python:3.9 uv run fixproof fix --repo https://github.com/psf/requests \
  --ref 22623bd8c265b78b161542663ee980738441c307 \
  --bug "requests.get always sends a Content-Length header, even for a GET without a body."
```

Check that `doctor` reports the endpoint as "personal mode, not the hackathon platform", and that
`report.md` starts its flags with "Not the hackathon platform". Never use this setup for the
demo, the video, or published benchmark results.

## Development-only: before Sandboxes access arrives

```bash
# Docker Desktop must be running
FIXPROOF_EXECUTOR=docker uv run fixproof fix --repo ... --issue ...   # prints "DEV ONLY" banner
```

Model calls still need a Token Factory key. A non-Nebius OpenAI-compatible endpoint may be set
in `NEBIUS_BASE_URL` **for local development only**. The hackathon FAQ states that other
providers do not satisfy the rules, so they are never used for the demo, the video, or the
benchmark results.
