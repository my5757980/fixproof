# Phase 0 Research: Verified Fix Agent ("FixProof", working name)

**Feature**: `001-verified-fix-agent` | **Date**: 2026-10-10 | **Spec**: [spec.md](./spec.md)

All facts below were checked on 2026-10-10 against the sources listed under each item. Anything
the docs do not state is marked **VERIFY-ON-ACCESS** and must be confirmed by the live smoke tests
once Token Factory and Sandboxes access is granted.

---

## R1. Inference client and endpoint

- **Decision**: Use the official `openai` Python SDK against the Token Factory OpenAI-compatible
  API.
  - Default base URL: `https://api.tokenfactory.nebius.com/v1/`. A regional URL,
    `https://api.tokenfactory.us-central1.nebius.com/v1/`, also appears in the Nebius cookbook.
  - The API key comes from `NEBIUS_API_KEY`.
  - Tools use native `tools` / `tool_choice` function calling.
- **Rationale**: The quickstart and function-calling docs document exactly this client and
  format. It is one well-maintained dependency with built-in retries, and the base URL is plain
  configuration (Constitution I).
- **Alternatives considered**:
  - Raw `httpx` calls: more code, with no benefit.
  - LangChain or other agent frameworks: rejected by Constitution III (no agent frameworks without
    proven need).
- **Sources**: docs.tokenfactory.nebius.com/quickstart.md;
  docs.tokenfactory.nebius.com/ai-models-inference/function-calling.md;
  github.com/nebius/token-factory-cookbook (models/nemotron).

## R2. Models, roles, and cost

| Role | Model (catalog name) | API model ID (as published) | $/1M in | $/1M out | Context |
|------|----------------------|-----------------------------|---------|----------|---------|
| Planner (plan, diagnose, hypotheses, root cause) | Nemotron-3-Ultra-550b-a55b | `nvidia/Nemotron-3-Ultra-550b-a55b` | 1.00 | 3.00 | 1M |
| Worker (tool loop: read, edit, test) | Nemotron-3-Super-120b-a12b | `nvidia/nemotron-3-super-120b-a12b` | 0.30 | 0.90 | 256K |
| Fallback / cheap condensing | Nemotron-3-Nano-30B-A3B | `nvidia/nvidia-nemotron-3-nano-30b-a3b` (cookbook) or `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (Nebius page) | 0.06 | 0.24 | 262K |

- **Decision**:
  - Roles follow the organizers' guidance ("Ultra for serious reasoning, Nano or Super for fast,
    everyday calls"): planner = Ultra, worker = Super.
  - Fallback chain on 5xx or model-unavailable errors: Ultra → Super → Nano. These are
    same-provider NVIDIA models (Constitution I).
  - All IDs, prices, and sampling parameters live in configuration.
  - `fixproof doctor` lists `/v1/models` and validates the configured IDs. It matches
    case-insensitively, because published IDs differ in casing between sources.
- **Reasoning controls**: The cookbook lists reasoning as "Available" for Ultra but documents no
  toggle. We do not depend on one. If a response carries `reasoning_content`, it is recorded in
  the trace and shown only in verbose mode (Constitution IV). **VERIFY-ON-ACCESS**.
- **Cost estimate per single-path run** (used to set default budgets):
  - Worker: about 30 calls, about 360K input and 15K output tokens. $0.108 + $0.014 ≈ **$0.12**.
  - Planner: about 5 calls, about 100K input and 10K output tokens. $0.10 + $0.03 ≈ **$0.13**.
  - Total about **$0.25 per run**. Parallel mode with 3 branches costs about $0.50.
  - With $50 of credits ($25 promo plus $25 Builders), that is about 100–200 runs. Demo defaults:
    $2/day cap, $0.60 per-run cap.
- **Alternatives considered**:
  - Super only: cheaper, but it gives up the "serious reasoning" story the judges look for.
  - Ultra only: about 3× the cost per worker step for little gain on mechanical tool steps.
  - Nemotron-3.5-Lightning (`nvidia/Nemotron-3_5-Lightning`, $0.06/$0.24, 1M context): kept as a
    configurable alternative worker if Super's tool calling proves weak.
- **Sources**: nebius.com/services/token-factory/models/nvidia-nemotron-models-inference;
  raw cookbook pages nemotron3-super-120B.md, nemotron3-ultra-550b-a55b.md, nemotron3-nano-30b.md;
  hackathon overview page (track guidance).

## R3. Tool-call robustness

- **Decision**:
  - Use native `tool_calls` as the primary path.
  - As a fallback, a lenient parser extracts a JSON object from `<tool_call>...</tool_call>` or a
    fenced JSON block in the assistant content when `tool_calls` is empty.
  - Every call is validated against its Pydantic model. Invalid calls never execute; the
    validation error is returned to the model as the tool result (Constitution III).
  - After 3 consecutive invalid calls, the run stops with a clear error.
- **Rationale**: The models are documented as supporting function calling, but serving stacks
  sometimes leak template tags. The fallback costs a few lines and removes a common failure mode.
- **Alternatives considered**: JSON-mode-only agents (more brittle multi-step state);
  grammar-constrained decoding (not documented on Token Factory).

## R4. Token Factory Sandboxes (ConTree) integration

**Documented facts**:

- **Packages**: `contree-sdk` (Python), built on `contree-client`. Async client:
  `ContreeAsyncClient(token, base_url=...)` from `contree_client.httpx`, wrapped by
  `Contree(api_client)`. Sync: `ContreeSync`. A profile-based alternative,
  `ContreeAsyncClient.from_profile()`, also exists.
  - **Verified 2026-10-11 against the installed contree-sdk 0.3.6** (the docs above are out of
    date): the async client is
    `Contree(config=ContreeConfig(auth=IAMAuth(token=..., project_id=..., base_url=...)))`;
    `IAMAuth` defaults to `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID`, and
    `https://api.tokenfactory.nebius.com/sandboxes/`. `images.oci(ref)` resolves a tag and
    imports it when missing. Errors are dataclass exceptions in `contree_sdk.sdk.exceptions`
    (429, timeouts, transport, and 5xx are retried by us). Cancelling the awaiting task cancels
    the server operation. `src/fixproof/sandbox/contree.py` follows this API.
- **Endpoint and auth**: The CLI docs use `CONTREE_URL=https://api.tokenfactory.nebius.com/sandboxes`
  plus a bearer token and a project ID. The token is `CONTREE_TOKEN`, falling back to
  `NEBIUS_API_KEY`; the project is `CONTREE_PROJECT` or `NEBIUS_AI_PROJECT`. The official demos say
  "sandbox and inference credentials can differ".
- **Images**: `images.use(tag_or_uuid)` (lazy), `images.use(..., strict=True)`, and `images.oci(...)`
  to import from a registry.
- **Run**: `image.run(command|shell, args, env, cwd, hostname, stdin, stdout, stderr, tag, files,
  timeout, disposable=True, truncate_output_at, preserve_env)`. It returns a new image object with
  `stdout`, `stderr`, `exit_code`, `uuid`, and `elapsed`. `disposable=False` persists the
  resulting filesystem as a new image version, which is our snapshot.
- **Files**: `files=[...]` or `{dest: src}` on `run`; `apply_files(...)` bakes files into a new
  image. Upload works for files only, not directories.
- **Reading**: `image.ls(path)`, `image.read(path) -> bytes`, `image.download(path, local)`.
- **Branching**: Running different commands from the same image UUID yields independent child
  images (the SDK "branching workflows" page).
- **Beta limits**: at most 50 simultaneously running operations; checkpoint images retained for
  180 days. Access must be requested at tokenfactory.nebius.com/sandboxes/about.

**Decisions**:

1. **Repository in**: The server downloads the GitHub tarball (R6). The sandbox then runs
   `mkdir -p /workspace && tar -xzf /tmp/repo.tgz -C /workspace --strip-components=1`, with the
   tarball passed via `files={"/tmp/repo.tgz": local_path}`, `disposable=False`, and tag
   `fixproof/<run>/source`. This does not depend on in-sandbox network access to GitHub.
2. **Base image**: `python:3.12` (full Debian image; it includes `git`, which we need for
   baseline diffs). Override per task when `python_requires` demands it.
3. **Baseline and diffs**: After installation:
   `git init -q && git -c user.email=agent@fixproof.dev -c user.name=fixproof add -A && ... commit -qm baseline`.
   The patch comes from `git diff --no-color baseline` plus untracked files
   (`git ls-files --others --exclude-standard`); changed-line counts come from `git diff --numstat`.
4. **Disposability**: Read-only operations (`ls`, `read`, `grep`, test runs whose output we capture
   from stdout) use `disposable=True`. Mutations (install, file edits, new tests) use
   `disposable=False` and advance the attempt's current image. Key snapshots are tagged
   (`.../installed`, `.../baseline`, `.../repro`, `.../attempt-<k>`).
5. **Dependency install** needs outbound access to PyPI inside the sandbox. The docs' own
   "install-packages" flow runs `pip install` inside a sandbox, so egress is expected.
   **VERIFY-ON-ACCESS**. Fallback: pre-build and tag images (with dependencies installed) for the
   demo samples and benchmark tasks once, then start runs from those tags.
6. **Secrets** are never passed to `env=` or `files=` of any sandbox call (Constitution:
   Security).

- **VERIFY-ON-ACCESS** (live smoke test list):
  - Does the inference API key work for Sandboxes, or is a separate token needed?
  - Where does the project ID come from?
  - Is there egress to PyPI?
  - CPU, memory, and disk per sandbox.
  - Maximum `timeout`.
  - Sandbox pricing.
  - Whether `images.use("python:3.12")` resolves Docker Hub directly or needs `images.oci`.
  - Names of the preloaded SWE-bench images.
- **Alternatives considered**: `git clone` inside the sandbox (depends on unknown egress and leaks
  nothing extra, but is slower and less deterministic); the Contree MCP server (adds a protocol
  hop; we already own the tool loop).
- **Sources**: docs.tokenfactory.nebius.com/sandboxes/{overview, sdk, sdk/python_sdk/getting-started,
  running-commands, branching, reference/image, reference/image_fs, cli/tutorial/installation,
  mcp/prompts/install-packages, sdk/integrations/mini-swe-agent}.md;
  github.com/kreuzhofer/nebius-token-factory-sandbox-demos.

## R5. Developing before access arrives

- **Decision**: One `Executor` protocol with three implementations:
  - `ContreeExecutor`: the default, and the only one allowed in the demo and video.
  - `DockerExecutor`: **dev-only**, opt-in with `FIXPROOF_EXECUTOR=docker`. It prints a "DEV ONLY"
    banner, implements snapshots with `docker commit`, and runs containers with `--network none`
    except during dependency install.
  - `FakeExecutor`: an in-memory filesystem with scripted command results. It lives under
    `tests/` only (Constitution II: fakes belong in tests).

  For models, the base URL override is allowed for local development only (Constitution I). The
  official FAQ confirms that calling NVIDIA models through other providers does **not** satisfy the
  rules, so such an override is never a default and never used in the demo or video.
- **Rationale**: Docker 29.1.3 is installed on the dev machine (the daemon must be started). This
  lets the agent run on real repositories before Sandboxes access while keeping untrusted code off
  the host (Security: sandboxed execution).
- **Alternatives considered**: Running repository code with `subprocess` on the host (rejected:
  violates sandboxed execution); waiting for access (rejected: integration would land too late for
  the 2026-10-30 deadline).

## R6. Repository and task intake (GitHub)

- **Decision**: GitHub REST via `httpx`:
  - `GET /repos/{owner}/{repo}` for the `private` flag, `size` (KB), and `default_branch`.
  - `GET /repos/{owner}/{repo}/tarball/{ref}` for source (follow the redirect to codeload).
  - `GET /repos/{owner}/{repo}/issues/{n}` for the issue title, body, and labels.

  An optional server-side `GITHUB_TOKEN` (read-only) raises the 60 requests/hour unauthenticated
  limit. It never enters a sandbox. Pull requests are opened only from the CLI, with the
  **user's own** `GITHUB_TOKEN`, after explicit confirmation (FR-016).
- **Validation**: Accept `https://github.com/<owner>/<repo>` (optional `/tree/<ref>`) only; reject
  private repositories and repositories above the size limit (demo default 50 MB) before any
  sandbox work (FR-018).
- **Alternatives considered**: `git clone` (needs git and network server-side and is slower for
  large histories); the GraphQL API (unnecessary).
- **Sources**: docs.github.com REST reference (repos, contents/download a repository archive,
  issues, rate limits).

## R7. Test execution and result parsing

- **Decision**:
  - Run `python -m pytest -rA -q -p no:cacheprovider --junitxml=/tmp/fixproof-junit.xml <selector>`
    with `PYTHONDONTWRITEBYTECODE=1`, inside one shell command that prints the JUnit XML and the
    tail of the console output between unique markers.
  - Add `--continue-on-collection-errors` (2026-10-14): when one test module cannot be imported,
    pytest otherwise runs nothing at all, which leaves no baseline to compare against. Task
    validation found this in real repositories (Requests).
  - Parse the XML with the standard library (`xml.etree.ElementTree`) into per-test outcomes.
  - Re-run baseline failures once to detect flakes.
  - The reproduction test must pass on **3 consecutive** runs to count (FR-007).
- **Rationale**: `--junitxml` is built into pytest (no plugin to install in the target
  environment), and stdout capture works with disposable runs.
- **Alternatives considered**: the `pytest-json-report` plugin (requires installing into the target
  environment); parsing console output with regular expressions (fragile).

## R8. Verification and labeling policy

- **Decision**: The harness computes the label. The model never sets it.
  - **Verified**: the reproduction test passes 3× consecutively, AND every baseline-passing test
    passes, AND no existing test file was modified or deleted.
  - **Needs review**: the tests pass, but existing test files changed, OR the repository had no
    test suite (the only evidence is the new reproduction test).
  - **Not verified**: anything else.

  The stop reason is recorded separately: completed, step, time, or cost budget, user stop, setup
  failed, not reproducible, or service unavailable. Test files are detected with the patterns
  `tests/**`, `test_*.py`, `*_test.py`, and `conftest.py`.
- **Rationale**: This puts Constitution II ("MUST NOT report success without evidence") and FR-007
  and FR-008 into the harness, so they cannot be talked around by model output.
- **Alternatives considered**: Letting the model judge success (rejected: unverifiable); requiring
  the entire suite to pass (rejected: penalizes pre-existing failures, per spec scenario 1.3).

## R9. Parallel hypotheses (Story 3)

- **Decision**:
  - The planner returns up to `N` hypotheses (default 3, maximum 3 in the demo) as structured JSON.
  - Each one runs the same worker loop from the `repro` snapshot in its own sandbox branch,
    concurrently, using `asyncio` with a semaphore. The per-branch budget is the run budget
    divided by `N`.
  - When the first branch verifies, the others are cancelled (unless `--exhaustive` is set). The
    winner is the smallest verified change (fewest changed lines, FR-014).
  - The report includes a hypothesis comparison table.
- **Rationale**: This is the documented branching use case ("try multiple patches or strategies in
  parallel from the same checkpoint, then keep only the winning branch"). It is one agent loop
  executed on several branches, not multi-agent orchestration (Constitution III).
- **Alternatives considered**: Sequential hypotheses (slower, no branching story); tree search
  such as MCTS (over-engineered for the deadline).

## R10. Live streaming and interfaces

- **Decision**: An in-process `EventBus` per run fans out to three subscribers:
  1. the trace writer (JSONL);
  2. the CLI renderer (Rich);
  3. web subscribers through Server-Sent Events, implemented with Starlette `StreamingResponse`
     (`text/event-stream`, no extra dependency).

  The web UI is a single static `index.html`, `app.js`, and `style.css` with no frontend
  framework.
- **Rationale**: The same events drive the CLI, the web UI, the trace, and replay, so the record
  and the display cannot diverge (FR-010, SC-005).
- **Alternatives considered**: WebSockets (bidirectional, which we don't need); a React frontend
  (build tooling and a second ecosystem); `sse-starlette` (an extra dependency for no real gain).

## R11. Demo hosting and judge access

- **Decision**: Ship a `Dockerfile` and deploy the web service to **Hugging Face Spaces (Docker
  SDK, free CPU tier)**. The official FAQ confirms that only the model call must go through
  Token Factory; the rest of the app may be hosted elsewhere. If Nebius access permits, Nebius
  hosting can replace it and is a bonus "other Nebius service" (an ADR records the switch).
- **Guardrails** (FR-017, FR-018; all configurable):
  - at most 2 concurrent live runs, with a FIFO queue;
  - 3 runs per visitor (IP) per day;
  - a $2 per day global cost cap and a $0.60 per-run cap;
  - public GitHub repositories of 50 MB or less;
  - 3 one-click curated samples (FR-019).

  When a cap is reached, the UI offers a **labeled replay** of recorded real runs.
- **Credits**: The Nebius promo email states that codes must be applied by 2026-12-31 and "won't
  expire" once applied, which covers judging through 2026-12-15. **VERIFY-ON-ACCESS** in the
  billing console.
- **Alternatives considered**: Render or Koyeb free tiers (more sleep and RAM limits); Fly.io
  (requires a card); a Nebius AI Cloud VM (blocked by the same billing-country issue today).
  Free Spaces sleep when idle. The README tells judges that the first load can take about a
  minute.

## R12. Optional web search (Tavily)

- **Decision**: The `web_search` tool is registered only when `FIXPROOF_WEB_SEARCH=1` and
  `TAVILY_API_KEY` is set. It calls `POST https://api.tavily.com/search` with
  `Authorization: Bearer <key>` and body `{"query": <≤200 chars>, "max_results": 5,
  "search_depth": "basic"}` (1 credit). It returns titles, URLs, and snippets only. It never sends
  file contents (FR-022).
- **Source**: docs.tavily.com/documentation/api-reference/endpoint/search.

## R13. Tooling and dependencies

- **Decision**: Python 3.12 (3.12.6 is installed locally), `uv` (0.9.5) for environments and a
  lockfile.
  - **Runtime dependencies**: `openai`, `contree-sdk`, `httpx`, `pydantic`, `pydantic-settings`,
    `fastapi`, `uvicorn`, `typer`, `rich`. Benchmark tasks use `tomllib` from the standard
    library, so there is no YAML dependency.
  - **Dev dependencies**: `pytest`, `pytest-asyncio`, `ruff`, `mypy`.
  - **CI**: GitHub Actions running `uv sync --frozen`, `ruff check`, `ruff format --check`,
    `mypy src`, and `pytest` (offline).
- **Rationale**: Each dependency has one clear job (Constitution III); everything is pinned via
  `uv.lock` (Constitution VI).

## R14. Benchmark

- **Decision**: `bench/tasks.toml` lists at least 10 real, already-fixed bugs from public Python
  repositories. It prefers easy SWE-bench Verified instances from small repositories (with their
  official FAIL_TO_PASS and PASS_TO_PASS tests as **hidden** reference checks) plus a few small
  libraries with fast suites.
  - `fixproof bench run` runs every task and reports:
    - the verified rate (SC-001);
    - the independent re-run result for each verified run (SC-002);
    - agreement with the hidden official tests, as an extra credibility metric;
    - single-path versus parallel results (SC-007).
  - The agent never sees the reference fix or the hidden tests.
- **VERIFY-ON-ACCESS**: names of the preloaded SWE-bench images in Sandboxes. Fallback: build the
  images ourselves from the task's base commit.

## R15. Risks and mitigations (top 3)

1. **No Token Factory or Sandboxes access** (Pakistan billing gap; a Discord case was opened on
   2026-10-10). Mitigations:
   - offline development with fakes plus the Docker dev executor;
   - a teammate-owned account (team invitations are supported);
   - the labeled-replay fallback cannot substitute for real runs in the video, so access is a
     hard prerequisite for submission.
2. **Weak tool calling or long-horizon drift.** Mitigations: strict schemas, a lenient parser,
   short focused worker contexts, planner re-diagnosis after each failed verification, and early
   live smoke tests.
3. **Sandbox egress or limits differ from assumptions.** Mitigation: pre-built tagged images for
   the demo samples and benchmark tasks.
