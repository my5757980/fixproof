# FixProof

FixProof is an autonomous coding agent that fixes bugs in public Python repositories **and
proves each fix**. It reproduces the bug with a failing test, changes the code, and then the
harness, not the model, checks the result: the reproduction test must pass three times in a
row and no test that passed before may fail. Every model call goes to NVIDIA Nemotron models
on **Nebius Token Factory**, and every command runs in **Token Factory Sandboxes**.

Built for the Nebius x NVIDIA Global AI Hackathon, track **Coding and Agentic Engineering**.

> **Status (2026-10-14)**: all features are implemented and tested offline (fake model, fake
> sandbox) and end to end on a local Docker executor with a scripted model. The first live runs
> on Nebius, the benchmark results, the sample output below, and the public demo URL will be
> added once our Token Factory and Sandboxes access is active.

## What it does and who it is for

Maintainers and developers of open-source Python projects spend a lot of time on bug reports
they cannot trust: "it fails for me" with no test, or a pull request that "fixes" the bug
without proof. AI coding assistants make this worse when they claim success without running
anything.

FixProof takes a public GitHub repository and one task (an issue URL, a failing test, or a bug
description) and works on its own:

1. it plans, sets the repository up in a sandbox, and runs the test suite;
2. it writes a test that reproduces the bug and fails;
3. it fixes the code and runs the tests again;
4. the harness verifies the fix and labels the result **Verified**, **Needs review**, or
   **Not verified**;
5. it writes a report with the root cause (with file and line citations), the evidence, and a
   patch.

You review the result and decide: apply the patch to your checkout, or open a pull request
from your own account. Nothing leaves the sandbox without your approval. In the developer jobs
of the track, FixProof **debugs** and **improves** code, and its reports help people
**understand** it.

## How it works

```text
            ┌──────────── CLI (Typer/Rich) ───────────┐     ┌──── Web demo (FastAPI + SSE + static UI) ────┐
            │ fix · replay · apply · pr · bench · doctor │     │ RunManager: queue, limits, replays           │
            └───────────────────────┬────────────────────┘     └──────────────────────┬───────────────────────┘
                                    └──────────────► Orchestrator ◄───────────────────┘
                                                        │  phases + budgets + EventBus ──► trace.jsonl / CLI / SSE
              ┌──────────────────────┬──────────────────┼────────────────────┬──────────────────────┐
              ▼                      ▼                  ▼                    ▼                      ▼
     repo/github.py          llm/TokenFactoryClient  tools/registry      agent/verify.py       agent/report.py
     (tarball, issue)        planner=Ultra           (schemas, guards)   (harness label)       (md + json, citations)
                             worker=Super ──────────► tools/handlers ───► sandbox/Executor
                             fallback→Nano                                ├─ ContreeExecutor (Token Factory Sandboxes)
                                                                          └─ DockerExecutor (DEV ONLY)
```

One orchestrator runs one agent loop with one tool registry. Each run goes through these
phases:

1. **Initial plan** (within 30 seconds): the planner reads the task and the repository's file
   tree from GitHub while the sandbox is being set up.
2. **Setting up**: the repository tarball is uploaded into a sandbox, installed with a recipe
   detected from `pyproject.toml`, `setup.py`, or `requirements*.txt` (one model-suggested
   retry, `pip install` only), and recorded as a git baseline.
3. **Baseline**: the full test suite runs; failing tests are re-run once to find flaky ones.
4. **Planning**: the planner refines the plan from the baseline (and, in parallel mode,
   proposes up to three hypotheses).
5. **Reproducing**: the worker writes a test that must fail before any source change.
6. **Fixing**: the worker edits the code with the tools below and calls `finish`.
7. **Verifying**: the harness runs the reproduction test three times and the full suite, and
   checks that no existing test file was changed. If verification fails and budget remains, the
   planner re-diagnoses from the failures and the worker tries again.
8. **Reporting**: the planner explains the root cause with citations; the harness assembles the
   label, evidence, and patch.

Every run is bounded by a step, time, and cost budget, and every model call, sandbox command,
and tool has a timeout. Each run writes `runs/<run_id>/` with `trace.jsonl` (every event, with
secrets redacted), `report.md`, `report.json`, and `patch.diff`.

**Parallel hypotheses** (`--parallel 2` or `3`): the planner proposes ranked hypotheses, and
each one is tried on its own sandbox branch, started from the same saved reproduction snapshot,
with an equal share of the budget. The first verified branch stops the others (unless
`--exhaustive`), and among verified branches the smallest change wins. The report compares the
branches.

## How FixProof uses NVIDIA Nemotron and Nebius Token Factory

### Models by role

| Role | Model ID (default) | Why |
|---|---|---|
| Planner | `nvidia/Nemotron-3-Ultra-550b-a55b` | The strongest reasoning model, called a few times per run: plans, hypotheses, re-diagnosis after a failed verification, and the root-cause report. |
| Worker | `nvidia/nemotron-3-super-120b-a12b` | Runs the tool loop (many calls per run): reads code, writes the reproduction test, edits, runs tests. A good balance of quality, speed, and cost. |
| Fallback | `nvidia/nvidia-nemotron-3-nano-30b-a3b` | The smallest and cheapest model; takes over when a model is unavailable (5xx or not found), so a run can still finish. |

The fallback chain is planner: Ultra → Super → Nano, worker: Super → Nano. When a worker
conversation grows long, older tool results are collapsed to one-line summaries without an
extra model call. Sampling parameters
are sent explicitly with every call (`temperature` 0.3, `top_p` 0.95, `max_tokens` 4096 by
default). All model IDs and parameters are configuration, not code; `fixproof doctor` checks
that each configured ID is listed by the endpoint's `/v1/models`.

### Where Token Factory accelerated the workflow

- **Inference**: one OpenAI-compatible endpoint serves all three Nemotron models, so routing by
  role, fallback between models, and per-model cost tracking need no extra infrastructure. The
  agent uses native tool calling, with a lenient parser for tool calls written as text.
- **Sandboxes**: every command the agent runs (installs, tests, shell commands) runs in Token
  Factory Sandboxes, never on the host. Commands that change files save a new sandbox image, so
  FixProof keeps checkpoints (`source`, `installed`, `repro`): each fix attempt starts from the
  saved reproduction instead of reinstalling, read-only commands run in throwaway sandboxes, and
  parallel hypotheses branch from the same snapshot.

No other Nebius services are used.

## Tools the agent can use

All tools are registered in `src/fixproof/tools/registry.py`, validated against their input
schema before they run, and executed only inside the sandbox. Output sent back to the model is
limited to 8,000 characters, with a `…[truncated N chars]` marker.

| Tool | Changes the sandbox | Phases | What it does |
|---|---|---|---|
| `list_dir` | no | reproduce, fix | List files and folders under a repository path, up to a depth. |
| `read_file` | no | reproduce, fix | Read a range of lines from a repository file, with line numbers. |
| `search_code` | no | reproduce, fix | Search repository files for a regular expression and return matching lines. |
| `create_file` | yes | reproduce, fix | Create a new file (fails if it exists), e.g. a reproduction test. |
| `edit_file` | yes | fix (reproduce: new test files only) | Replace one exact, unique occurrence of text in an existing file. |
| `run_tests` | no | reproduce, fix | Run pytest on a selector (or the full suite) and return structured results. |
| `run_command` | no | reproduce, fix | Run a short, read-only shell command for inspection (e.g. `python -c`). |
| `web_search` | no | fix, only when enabled | Search the web for documentation or an error message (short query only). |
| `finish` | no | reproduce, fix | Declare the attempt done and hand over to independent verification. |

Paths must stay inside the repository. `run_command` refuses `git push`, `curl`, `wget`,
`pip install`, and `rm -rf /`; in the reproduce phase, existing files cannot be edited.

## Prerequisites and credentials

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- A Nebius Token Factory account with credits and an API key: create the key at
  [tokenfactory.nebius.com](https://tokenfactory.nebius.com) under API keys.
- Token Factory Sandboxes (beta) access: request it at
  [tokenfactory.nebius.com/sandboxes/about](https://tokenfactory.nebius.com/sandboxes/about),
  then copy your Sandboxes project ID from the console.
- Optional: a read-only `GITHUB_TOKEN` for higher GitHub API limits; your own `GITHUB_TOKEN`
  (allowed to fork and open pull requests) for `fixproof pr`; a `TAVILY_API_KEY` for web
  search.
- Development only: Docker Desktop, for the local `docker` executor.

## Quickstart

```bash
git clone <this repository> fixproof && cd fixproof
uv sync                       # creates .venv from uv.lock
cp .env.example .env          # set NEBIUS_API_KEY and CONTREE_PROJECT (never commit .env)
uv run fixproof doctor        # checks the key, the model IDs, and sandbox access
```

Run the agent (one command). This example is a real, already-fixed bug in Requests, at the
commit before the fix; that old revision needs Python 3.9, which the first part of the command
selects (or set `FIXPROOF_BASE_IMAGE=python:3.9` in `.env`):

```bash
FIXPROOF_BASE_IMAGE=python:3.9 uv run fixproof fix --repo https://github.com/psf/requests \
  --ref 22623bd8c265b78b161542663ee980738441c307 \
  --bug "requests.get always sends a Content-Length header, even for a GET without a body. Some servers reject such requests."
```

Run the tests (one command, offline, no credentials needed):

```bash
uv run pytest
```

## Personal mode (without the hackathon platform)

If you cannot use Nebius Token Factory (for example, its billing is not available in your
country), FixProof also runs with the same Nemotron models from NVIDIA's own API or from
OpenRouter, and with local Docker containers instead of Token Factory Sandboxes. This is
**not** the hackathon platform: every report, benchmark summary, and `doctor` check says so.

1. Create an API key, at [build.nvidia.com](https://build.nvidia.com/settings/api-keys) for
   NVIDIA's API or at [openrouter.ai](https://openrouter.ai/settings/keys) for OpenRouter.
2. Start Docker Desktop.
3. Configure and check:

   ```bash
   cp .env.personal.example .env   # then set FIXPROOF_PROVIDER and put in your key
   uv run fixproof doctor          # confirms the key, the model IDs, and Docker
   ```

4. Run the agent as in the Quickstart. Old revisions may need an older Python
   (`FIXPROOF_BASE_IMAGE=python:3.9`), and a slow computer may need a larger time budget
   (`--max-minutes 60`).

| `FIXPROOF_PROVIDER` | Key | Endpoint | Planner, worker, fallback | Cost |
|---|---|---|---|---|
| `nvidia` | `NVIDIA_API_KEY` | `https://integrate.api.nvidia.com/v1` | `nvidia/nemotron-3-ultra-550b-a55b`, `nvidia/nemotron-3-super-120b-a12b`, `nvidia/nemotron-3.5-lightning-30b-a3b` | $0 (free to use) |
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | the same models as free variants: `...-ultra-550b-a55b:free`, `...-super-120b-a12b:free`, `nvidia/nemotron-3.5-lightning:free` | $0, with a daily request limit |

Values you set yourself always win. A billed OpenRouter model (without `:free`) needs a price in
`FIXPROOF_PRICES`, and `doctor` says so. The step and time budgets always apply. Personal mode
is never used automatically, one provider never falls back to the other, and the public demo
refuses it.

## Usage

```text
fixproof fix     --repo URL (--issue URL | --test NODEID | --bug TEXT) [--ref REF]
                 [--parallel 1-3] [--exhaustive] [--max-steps N] [--max-minutes N]
                 [--max-cost USD] [--out DIR] [--verbose] [--json]
fixproof replay  TRACE_PATH [--speed X]          # replay a recorded run, labeled REPLAY
fixproof apply   RUN_DIR [--to PATH]             # apply the patch to your checkout, after [y/N]
fixproof pr      RUN_DIR [--title TEXT]          # open a draft PR from your account, after [y/N]
fixproof bench   run [--tasks FILE] [--only IDS] [--parallel N] [--compare-single] [--out DIR]
fixproof bench   report RESULTS_DIR [--json]
fixproof doctor  [--json]                         # check configuration and access
fixproof serve   [--host HOST] [--port PORT]      # start the web demo
```

`fix` prints the plan first, then one line per step (tool calls with their purpose, test runs,
verification). Exit codes: `0` verified, `10` needs review, `20` not verified, `30` stopped or
out of budget, `40` setup failed or not reproducible, `2` invalid input, `1` internal error.
Ctrl+C stops a run within 10 seconds and still writes the partial report.

`apply` and `pr` always show the full diff and the evidence and ask `Apply this patch? [y/N]`;
there is no auto-approve flag. They refuse runs that are not verified unless you pass
`--force-unverified`. `pr` uses only your own `GITHUB_TOKEN`, forks the repository, and opens a
**draft** pull request whose description cites the evidence and says that an AI agent prepared
it.

**Sample output**: pending. A real run on Nebius Token Factory and Sandboxes will be shown here.

## Benchmark

`bench/tasks.toml` holds real, already-fixed bugs from public Python repositories, taken from
SWE-bench. The agent sees only the issue text and the repository at the commit before the
official fix. Some old revisions break with today's releases of their dependencies, so a task
can pin a few packages (`pip_packages`), installed after FixProof's normal install recipe, as
SWE-bench's own environments do. After each run, the benchmark sets up a fresh sandbox with the
run's own install commands and:

- re-runs the evidence of every **Verified** fix there (a verified fix must never fail this
  re-check);
- runs the task's **hidden** reference tests, added by the official fix's test patch, without
  and with the agent's fix. The hidden tests and the test patch are never shown to the agent or
  put into its sandbox. Agreement means the hidden tests pass exactly when FixProof said
  Verified.

```bash
uv run fixproof bench run --parallel 3 --compare-single   # parallel and single-path, same budget
uv run fixproof bench report bench/results/<date>         # Markdown table for this README
```

**Results**: pending the first live run on Nebius.

## Judge demo

**URL**: pending deployment (Hugging Face Spaces, Docker). The first page load after a quiet
period can take about a minute while the Space wakes up.

The demo offers one-click sample tasks and accepts any public GitHub repository up to 50 MB.
Runs stream live (plan, tool calls, tests, verification), can be stopped, and end with a report
and a downloadable patch. Each visitor can start 3 live runs per day, at most 2 run at once
(others wait in a queue with their position shown), and a daily budget caps spending. When a
limit or the budget is reached, the demo offers a recorded real run, clearly labeled
**REPLAY**. The demo has no apply or pull-request buttons.

## Configuration reference

All settings come from environment variables or `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `FIXPROOF_PROVIDER` | `nebius` | `nebius` (Token Factory, the hackathon configuration), or `nvidia` or `openrouter` (personal mode) |
| `NVIDIA_API_KEY` | (personal mode) | NVIDIA API key from build.nvidia.com |
| `OPENROUTER_API_KEY` | (personal mode) | OpenRouter API key from openrouter.ai |
| `NEBIUS_API_KEY` | (required) | Token Factory API key |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1/` (personal mode: the provider's endpoint) | Inference endpoint; anything else is development only and prints a DEV ONLY warning |
| `FIXPROOF_PLANNER_MODEL` | `nvidia/Nemotron-3-Ultra-550b-a55b` | Planner model |
| `FIXPROOF_WORKER_MODEL` | `nvidia/nemotron-3-super-120b-a12b` | Worker model |
| `FIXPROOF_FALLBACK_MODEL` | `nvidia/nvidia-nemotron-3-nano-30b-a3b` | Fallback model |
| `FIXPROOF_TEMPERATURE` | `0.3` | Sampling temperature |
| `FIXPROOF_TOP_P` | `0.95` | Nucleus sampling |
| `FIXPROOF_MAX_TOKENS` | `4096` | Maximum completion tokens per call |
| `FIXPROOF_PRICES` | built-in table | Optional price override, USD per 1M tokens: `{"model-id": [input, output]}` |
| `CONTREE_URL` | `https://api.tokenfactory.nebius.com/sandboxes` | Sandboxes endpoint |
| `CONTREE_PROJECT` (or `NEBIUS_PROJECT_ID`) | (required) | Sandboxes project ID |
| `CONTREE_TOKEN` | `NEBIUS_API_KEY` | Sandboxes token, if it differs from the API key |
| `FIXPROOF_EXECUTOR` | `contree` | `contree` (Token Factory Sandboxes) or `docker` (development only) |
| `FIXPROOF_BASE_IMAGE` | `python:3.12` | Base image of the sandbox |
| `GITHUB_TOKEN` | (none) | Read-only token for higher GitHub limits; for `fixproof pr`, your own token |
| `TAVILY_API_KEY` | (none) | Key for the optional web search |
| `FIXPROOF_WEB_SEARCH` | `0` | `1` enables `web_search` (also needs `TAVILY_API_KEY`) |
| `FIXPROOF_ALLOW_DEV` | `0` | `1` lets `serve` start with development settings, for local UI testing only. Never set it for the public demo or the video |
| `FIXPROOF_LIVE` | `0` | `1` runs the live tests against Nebius |
| `FIXPROOF_STATE_DIR` | `runs` | Where the demo keeps runs and its daily budget |
| `FIXPROOF_DEMO_MAX_CONCURRENT` | `2` | Demo runs at once |
| `FIXPROOF_DEMO_RUNS_PER_VISITOR` | `3` | Live runs per visitor per day |
| `FIXPROOF_DEMO_DAILY_CAP_USD` | `2.0` | Demo spending cap per day |
| `FIXPROOF_DEMO_MAX_REPO_MB` | `50` | Largest repository the demo accepts |
| `FIXPROOF_SANDBOX_COST_PER_MIN_USD` | `0.0` | Estimated sandbox cost per minute, counted in the demo budget |
| `FIXPROOF_DEMO_URL` | (none) | Public demo URL, for the daily uptime check (a GitHub Actions variable) |

Default budget per CLI run: 40 model steps, 15 minutes, $1.00 (`--max-steps`, `--max-minutes`,
`--max-cost`). Per demo run: 30 steps, 10 minutes, $0.60.

## Running the tests

```bash
uv run pytest                                   # offline: fake model and fake sandbox, no credentials
uv run ruff check . && uv run ruff format --check . && uv run mypy src
FIXPROOF_LIVE=1 uv run pytest -m live           # live tests against Nebius (needs .env)
FIXPROOF_DOCKER=1 uv run pytest -m docker       # end to end on local Docker with a scripted model
```

The offline suite covers every tool (success and failure paths), the verification rule,
multi-step runs that end verified, invalid tool calls, re-diagnosis after a failed
verification, budget stops, parallel branches, the web API against its OpenAPI contract, the
apply and pull-request flows, the benchmark runner, and secret redaction.

## Safety model

- **Sandboxed autonomy**: the agent acts without asking only inside the sandbox, within its
  budget. Installs, tests, and shell commands never run on your machine.
- **Approval at the boundary**: applying a patch to your checkout and opening a pull request
  always show the diff and the evidence first and need an explicit `y`. The web demo cannot do
  either.
- **Patch safety**: before applying, every path in the patch must be relative, without `..`,
  outside `.git`, and not through a symbolic link.
- **Secrets**: keys come only from the environment or `.env`. They are never sent into a
  sandbox (commands and files are checked), and they are redacted from traces, logs, and error
  messages.
- **Untrusted input**: repository files, issue text, test output, and search results are
  treated as data. Text in them cannot trigger anything outside the sandbox.
- **Honest labels**: the label comes from the harness's own test runs, never from the model.
  A fix that changes existing test files, or a repository with no other passing tests, can at
  best be **Needs review**.

## Data that leaves your machine

| Service | What it receives |
|---|---|
| Nebius Token Factory (inference) | Prompts with the task, repository file names and excerpts, test output, and tool results |
| NVIDIA API or OpenRouter (personal mode only, instead of Token Factory) | The same prompts; with the local Docker executor, the code itself stays on your machine. OpenRouter passes prompts to the host serving the model; its privacy settings say what free variants may log |
| Token Factory Sandboxes | The repository tarball and the commands the agent runs |
| GitHub | Requests for public repository metadata, the tarball, and the issue; with `fixproof pr`, the fork, branch, changed files, and pull request |
| Tavily (only with `FIXPROOF_WEB_SEARCH=1`) | Short search queries (at most 200 characters, never file contents, never anything that contains a secret) |

FixProof has no telemetry.

## Known limitations

- Python repositories with pytest suites only.
- Projects that need services (databases, network APIs) during tests, or that are very large
  (the demo accepts up to 50 MB), are out of scope.
- Projects whose version comes from git tags (for example setuptools-scm) may fail to install
  from a source tarball.
- FixProof installs the newest dependency versions that a project's own files allow. Old
  revisions with loose requirements can break with today's releases; the install step then
  fails or the test suite cannot start.
- The reproduction test is written by the agent; a weak reproduction can make a fix look
  better than it is. The hidden-test agreement in the benchmark measures this.
- A fix is verified against the repository's own tests in a sandbox; it is a strong signal,
  not a guarantee. Review every patch before merging.

## License and credits

MIT License (see [LICENSE](LICENSE)); dependency licenses are listed in
[docs/licenses.md](docs/licenses.md).

- Models: NVIDIA Nemotron 3 Ultra, Nemotron 3 Super, and Nemotron 3 Nano, used through Nebius
  Token Factory under NVIDIA's license terms for each model.
- Benchmark tasks: SWE-bench and SWE-bench Verified (MIT License).

**Built With**: Nebius Token Factory, Token Factory Sandboxes, NVIDIA Nemotron 3 Ultra,
NVIDIA Nemotron 3 Super, NVIDIA Nemotron 3 Nano, Python, FastAPI, Typer, Pydantic, uv.
