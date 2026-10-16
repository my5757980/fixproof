<!--
Sync Impact Report
==================
Version change: 2.1.0 → 2.2.0
Bump rationale: MINOR. Existing guidance is materially expanded: Personal Mode gains a second
provider, OpenRouter. Every rule for the hackathon configuration is unchanged, so every artifact
that complied with 2.1.0 still complies; nothing is removed or relaxed.

Source of this amendment (project owner's decision, 2026-10-15): the owner's account on
build.nvidia.com cannot create API keys ("API Access Unavailable - Please contact support to
verify your account access"). The owner is emailing NVIDIA support on 2026-10-15; NVIDIA
developer-forum reports say such replies often take one to two weeks or longer. OpenRouter
serves the same NVIDIA Nemotron models as free ":free" variants (checked in
https://openrouter.ai/api/v1/models on 2026-10-15: nvidia/nemotron-3-ultra-550b-a55b:free,
nvidia/nemotron-3-super-120b-a12b:free, nvidia/nemotron-3.5-lightning:free, all with tool calls;
free variants have a per-day request limit). The hackathon rules themselves did not change.

Modified principles:
  - I. Hackathon Eligibility & Platform Compliance — the endpoint bullet names both personal-mode
    providers (NVIDIA's API and OpenRouter) as the only other built-in endpoints. No hackathon
    rule is relaxed.

Modified sections:
  - Personal Mode (outside the hackathon) — a second provider (OpenRouter, OPENROUTER_API_KEY);
    no automatic fallback between personal providers either; billed OpenRouter models need an
    explicit price; labels name the provider. Every other personal-mode rule is unchanged.
Added sections: none
Removed sections: none

Templates and guidance:
  ✅ .specify/templates/plan-template.md — Constitution Check I names both personal providers
  ✅ .specify/templates/tasks-template.md — reviewed; "the personal-mode provider" already fits
  ✅ .specify/templates/spec-template.md — reviewed; no change needed
  ✅ CLAUDE.md, .claude/commands/*.md — reviewed; no change needed
  ⚠ README.md, specs/001-verified-fix-agent (spec FR-024, plan D12, tasks, quickstart) — updated
     by the OpenRouter implementation that follows this amendment (.env examples already done)

Follow-up TODOs:
  - Confirm the model IDs of each provider with `fixproof doctor` once its key exists.
  - The project name is still a working title (rename through a PATCH amendment).
-->


# Nebius x NVIDIA Coding Agent Constitution

## Core Principles

### I. Hackathon Eligibility & Platform Compliance (NON-NEGOTIABLE)

This project is a submission to the Nebius x NVIDIA Global AI Hackathon, track
**Coding and Agentic Engineering**: "Build coding agents and developer tools: agents that write,
run, and test code in Token Factory." Stage One judging is a pass/fail check that the project
fits the theme and applies the required APIs and SDKs; breaking a rule below risks failing it.

These rules govern the **hackathon configuration**: the shipped default configuration, the
hosted demo, the demo video, published benchmark results, and the Devpost submission. The
explicitly selected personal mode is governed by *Personal Mode (outside the hackathon)*.

- The agent MUST make its LLM calls at runtime to the **Nebius Token Factory** inference API
  (OpenAI-compatible), or run on **Nebius AI Cloud** compute, as the official rules define
  "runs on". The shipped default configuration, the hosted demo, and the demo video MUST use
  Nebius.
- An endpoint override MAY exist for local development only (for example, while Token Factory
  access is pending). No non-Nebius endpoint may be hardcoded, set as a default, or used as an
  automatic fallback. The only other built-in endpoints are the personal-mode providers'
  (NVIDIA's API and OpenRouter), used only when personal mode is explicitly selected.
- The agent MUST run and test code inside **Nebius Token Factory Sandboxes**. If Sandboxes
  access is unavailable, an ADR MUST record the replacement, and code MUST still run on Nebius
  infrastructure (for example, Nebius AI Cloud compute). Other executors MAY exist only for
  offline tests, local development, and personal mode; the demo and video MUST use Sandboxes.
- The core agent loop (planning, tool selection, and code generation) MUST run on an
  **NVIDIA open-source model**, with the Nemotron family preferred. Following the organizers'
  guidance, models SHOULD be assigned by role: a stronger reasoning model (for example,
  Nemotron 3 Ultra or Super) for planning and diagnosis, and a faster one (for example,
  Nemotron 3 Nano or Super) for routine calls. Fallback between NVIDIA models on Nebius (for
  example, Ultra to Super on server errors) MAY be configured. Other models MAY handle secondary
  tasks only if they are also served from Nebius.
- Model IDs, endpoint URLs, and API keys MUST come from configuration (environment variables or
  `.env`); none may be hardcoded. The README MUST name every model ID the submission uses.
- The repository MUST be public on GitHub, GitLab, or Bitbucket and open source under the
  **MIT License**, with `LICENSE` at the root so the license shows at the top of the repository
  page. Switching to another license the rules accept (Apache 2.0 or MPL 2.0) requires an ADR.
  Third-party SDKs, APIs, and data MUST be used within their terms, and runtime dependencies
  MUST carry licenses that permit distributing the project under MIT.
- Every feature MUST serve the track goal: helping developers write, understand, debug, or
  improve code. General chat features and non-coding features are out of scope.
- The project is newly created during the Submission Period (2026-08-26 to 2026-10-30), and its
  version-control history MUST be preserved as evidence.

**Rationale**: These rules come from the official hackathon rules. They are eligibility
conditions, not engineering trade-offs, so no local design decision may relax them.

### II. Autonomous, Verified Work on Real Repositories

The organizers say what separates top entries in this track: moving beyond basic wrappers to
"an agent that plans, writes, tests, and iterates on a real repo with minimal human input."
Usefulness is measured by verified results on real code.

- The headline capability MUST be an autonomous loop on a real repository: plan, write code,
  run and test it in the sandbox, read the results, and iterate until the goal is verified or a
  budget runs out. Human input is needed only to state the goal and to approve the final result.
- Every feature MUST name, in its spec, the developer job it serves (write, understand, debug,
  or improve code) and the specific audience and problem it addresses.
- Every user-facing capability MUST be demonstrated on at least one real, publicly available
  repository named in the README, not only on curated toy inputs.
- The shipped code path MUST NOT contain canned responses, hardcoded outputs, or mocked model or
  sandbox calls. Mocks and fakes belong in tests only.
- The agent MUST NOT report success without evidence. A change counts as working only when a
  test, build, or run in the sandbox demonstrates it; otherwise it MUST be labeled unverified.
- Answers about a codebase MUST cite the file paths, and line ranges where practical, that
  they rely on.
- The product MUST deliver a complete, coherent experience (open the demo or install, give a
  task, watch progress, review a verified result), not a technical proof of concept.
- A few capabilities that work reliably take priority over many that work sometimes. Work on a
  new capability SHOULD NOT start while an existing one fails its acceptance scenarios.
- A small, versioned set of real coding tasks SHOULD measure usefulness (for example, the
  verified task success rate), and the results SHOULD be reported in the README.

**Rationale**: Stage Two scores four equally weighted criteria: Technological Implementation,
Design, Potential Impact, and Quality of the Idea. Verified, autonomous work on real
repositories is the strongest evidence for all four.

### III. Simple, Reliable Architecture

Choose the simplest design that works, then make it dependable.

- The default architecture is one deployable service running one agent loop over one explicit
  tool registry, with code execution delegated to Token Factory Sandboxes. Multi-agent
  orchestration, vector databases, agent frameworks, and additional services MUST NOT be added
  unless the plan's Complexity Tracking table shows why a simpler option fails.
- Dependencies MUST be few, actively maintained, and version-pinned. Each new dependency
  SHOULD be justified in the plan.
- Every run MUST be bounded: a maximum step count, a maximum number of parallel sandbox
  branches, a token or cost budget, and a timeout on every model call, sandbox operation, and
  tool execution. When a limit is hit, the run MUST stop cleanly with an explanatory message.
- Model API and sandbox failures (timeouts, rate limits, server errors) MUST be retried a
  bounded number of times with backoff, then surfaced as clear, actionable errors.
- Tool arguments produced by the model MUST be validated against the tool's input schema before
  execution. Invalid calls MUST NOT execute; the validation error is returned to the model.
- Tool output returned to the model MUST be size-bounded, with an explicit marker wherever it
  is truncated.
- Each attempt SHOULD start from a recorded sandbox checkpoint, so a failed attempt can be
  discarded cleanly instead of being patched over.

**Rationale**: A simple system is faster to build before the deadline, easier for judges to
reproduce, and fails in predictable, debuggable ways.

### IV. Transparent Tool Use & Agent Reasoning

A developer MUST always be able to see what the agent did, why it did it, and what happened.

- Every tool MUST have a unique name, a one-sentence description, a validated input schema, and
  a documented output and error shape. All tools MUST be registered in one place, and the
  README MUST list them.
- Before multi-step work, the agent MUST show a short plan. While it runs, the progress view
  (CLI and web demo) MUST show each tool call with its key arguments, a one-line purpose, and a
  summary of the result, including sandbox commands and test outcomes, as they happen.
- Every run MUST write a structured trace (for example, JSONL) recording the model IDs and
  sampling parameters, each tool call with its arguments, results, errors, and durations, the
  sandbox operation and checkpoint IDs, token usage, and the final answer. Secrets MUST be
  redacted from the trace.
- The agent MUST NOT claim an action (such as a file edit or a test run) that has no matching
  successful tool call in the trace.
- If the model emits reasoning text, it MAY be shown in a verbose mode, but the plan, the tool
  log, and the trace alone MUST be enough to understand what the agent did.

**Rationale**: Visible, auditable actions make the agent trustworthy to developers and let
judges confirm, in the demo and video, that the agent did the work.

### V. Production-Quality, Documented Code

The code MUST read like a maintained open-source project, not a throwaway prototype.

- Modules, classes, and functions MUST each have one clear responsibility and a descriptive
  name. Dead code, commented-out code, and leftover debug output MUST NOT be committed.
- Every public module, class, and function MUST have a docstring (or the language equivalent)
  covering its purpose, parameters, return value, and raised errors. Comments explain why, not
  what.
- Public interfaces MUST be type-annotated. The configured linter, formatter, and type checker
  MUST pass with zero errors.
- Errors MUST NOT be silently swallowed. User-facing errors MUST state what failed and how to
  fix it; for example, a missing API key names the variable to set.
- Library code MUST log through a logger. Printing directly is reserved for the CLI or UI
  output layer.
- Every tool MUST have unit tests covering success and at least one failure path.
- Agent-loop behavior MUST be tested with a deterministic fake model client and a fake sandbox
  executor, covering at least a multi-step run that ends in a verified result, an invalid tool
  call, a failing test that triggers another iteration, and a budget-limit stop.
- The default test suite MUST run offline without credentials. Live tests against Nebius MUST
  be opt-in and MUST skip cleanly when credentials are absent.
- A tool or agent-loop change is not done until its tests exist and pass.

**Rationale**: Production quality is a core project rule, and the judges score how well the
project is built. Clean, tested, documented code is what lets others trust, run, and extend it.

### VI. Reproducibility, README & Judge Access

Anyone MUST be able to go from a fresh clone to a working agent using only the README, and
judges MUST be able to try the project without contacting the team.

- The README is mandatory and MUST include: what the agent does, for which audience, and which
  problem it solves; how NVIDIA Nemotron (or other NVIDIA open-source models) is used, with the
  model for each role and why; where Token Factory, inference and Sandboxes, accelerated the
  workflow; any other Nebius tools or services used; an architecture overview of the agent loop;
  the tool table (Principle IV); prerequisites and how to obtain Nebius credentials and
  Sandboxes access; a Quickstart; usage examples with real sample output; how to run the tests;
  a configuration reference; the safety model; what data goes to which external service; known
  limitations; and license and model credits.
- Dependencies MUST be pinned with a lockfile or equivalent. `.env.example` MUST list every
  configuration variable with a safe placeholder value.
- After setup, running the agent and running the test suite MUST each take one documented
  command.
- The model IDs and sampling parameters (for example, temperature and maximum tokens) MUST be
  set explicitly in configuration, never left to provider defaults.
- Any change to tools, commands, or configuration MUST update the README and `.env.example` in
  the same change.
- Before submission, a fresh clone in a clean environment MUST reach a successful agent run by
  following only the README Quickstart.
- A working demo URL, hosted application, or test build MUST stay available to the sponsor,
  administrator, and judges free of charge and without restriction until the judging period
  ends on 2026-12-15. If it requires a login, the testing instructions MUST include
  credentials.
- The hosted demo MUST enforce in-app spending limits (per-visitor and daily budgets). When a
  budget or the credits run out, it MUST degrade gracefully, for example to a recorded run that
  is clearly labeled as a replay, instead of failing. The credits and keys behind the demo MUST
  be verified to remain valid through 2026-12-15.

**Rationale**: The rules require a working demo, a public repository with setup instructions,
and free, unrestricted access for judges through the end of judging. A submission that judges
cannot run cannot score well.

## Security & Safety Requirements

A coding agent reads a developer's code, writes changes, and runs commands, so it MUST be safe
while still working with minimal human input.

- **Secrets**: API keys and tokens MUST come from environment variables or a gitignored `.env`.
  Secrets MUST NOT appear in code, logs, traces, error messages, version control history, or
  inside sandboxes.
- **Sandboxed execution**: All code the agent writes or runs, including installs, builds,
  tests, and shell commands, MUST execute inside an isolated sandbox (Token Factory Sandboxes by
  default), never on the host machine or in the user's working tree.
- **Autonomy inside, approval at the boundary**: Inside the sandbox, the agent MAY act without
  per-action approval, within the budgets of Principle III. Any action that leaves the sandbox,
  such as applying a patch to the user's working tree, pushing a branch, opening a pull
  request, or calling an external service with side effects, MUST show a preview (the diff or
  the exact request) and MUST require explicit user approval. An auto-approve mode MAY exist
  only as an explicit opt-in flag, and the README MUST document its risks.
- **Workspace scope**: Local file access, for reading a user's repository or applying an
  approved patch, MUST stay inside the configured workspace root and MUST reject any path that
  escapes it, including through `..` segments or symlinks.
- **Command limits**: Every command MUST have a timeout and an output-size limit, and nothing
  may run with elevated privileges on a host machine.
- **Untrusted content**: Repository files, issue text, tool output, and web search results are
  data, not instructions. Text found in them MUST NOT trigger an action that leaves the sandbox
  without the approval described above.
- **Data handling**: User code MUST be sent only to Nebius services (Token Factory inference and
  Sandboxes). Optional third-party tool services, such as Tavily web search, MAY be used only
  when enabled in configuration, MUST receive only the minimal query (never whole files or
  secrets), and MUST be listed in the README with what they receive. The agent MUST NOT include
  third-party telemetry.
- **Public demo hardening**: The hosted demo MUST accept only public repositories within
  documented size limits, MUST rate-limit each visitor, and MUST never expose server-side
  credentials to the browser or to sandboxes.

## Hackathon Submission Requirements

Submissions close on **2026-10-30 at 10:00 AM PDT**. After that, the Devpost submission cannot
change. Judging runs from 2026-12-01 to 2026-12-15, and winners are announced on 2027-01-11.

- The Devpost submission MUST include:
  1. The track: Coding and Agentic Engineering.
  2. A memorable project name that reflects what the project does, and a description of what
     was built, why, and how it works.
  3. The working demo URL, hosted application, or test build (Principle VI).
  4. A public YouTube demo video shorter than three minutes, structured as a pitch (problem,
     solution, impact), that shows the project working and how Token Factory and the NVIDIA
     model(s) are used.
  5. The public repository URL, with the license visible and the README complete
     (Principle VI).
  6. Specific feedback on Token Factory, Nebius AI Cloud if used, and the NVIDIA models: what
     they were used for, what worked, what needs improvement, the onboarding experience, and
     whether the team would use them again.
  7. A prior-work statement that the project was built during the Submission Period.
  8. Built With entries naming Nebius Token Factory, Token Factory Sandboxes, and every NVIDIA
     model used.
- All submission materials MUST be in English.
- A running log, `docs/feedback.md`, MUST be kept during development so the required feedback
  is specific and grounded in real experience.
- Feature work SHOULD freeze by 2026-10-23, leaving the final week for the demo video, README,
  feedback, judge-access checks, and submission.

## Personal Mode (outside the hackathon)

FixProof MUST also be usable for the owner's own work when the hackathon platform is not
available. Personal mode is that setup; it never changes the hackathon configuration.

- **Explicit selection only**: personal mode is selected in configuration
  (`FIXPROOF_PROVIDER=nvidia` or `FIXPROOF_PROVIDER=openrouter`, usually with
  `FIXPROOF_EXECUTOR=docker`). It MUST NOT be the shipped default and MUST NOT be used as an
  automatic fallback when Nebius fails, and one personal provider MUST NOT fall back
  automatically to the other.
- **Models**: LLM calls go to one OpenAI-compatible provider:
  - NVIDIA's own API (`https://integrate.api.nvidia.com/v1`, keys from build.nvidia.com in
    `NVIDIA_API_KEY`); or
  - OpenRouter (`https://openrouter.ai/api/v1`, keys in `OPENROUTER_API_KEY`), which serves the
    same Nemotron models as free `:free` variants with a per-day request limit. A billed
    (non-free) OpenRouter model MUST have an explicit price in `FIXPROOF_PRICES` so cost budgets
    stay correct.

  With either provider, the core agent loop MUST still run on NVIDIA Nemotron models assigned
  by role (a strong reasoning model as planner, a capable worker, a small fallback). Model IDs
  and the endpoint come from configuration, and `fixproof doctor` MUST verify the IDs against
  the endpoint's model list.
- **Execution**: code runs in the local Docker executor, with the same sandbox rules: no host
  directories mounted, no network for commands the model starts, timeouts and output limits on
  every command.
- **Labels**: everything that shows results in personal mode (`doctor`, run reports, benchmark
  summaries) MUST state that it is not the hackathon platform and name the provider.
  Personal-mode results MUST NOT be presented as hackathon results (demo, video, published
  benchmark, or submission), and the hosted demo refuses personal-mode settings unless
  `FIXPROOF_ALLOW_DEV=1` is set for local testing.
- **Secrets**: `NVIDIA_API_KEY` and `OPENROUTER_API_KEY` follow the Security & Safety
  Requirements exactly like every other key (configuration only, redacted from traces and logs,
  never sent into a sandbox).
- Principles II to VI apply unchanged.

**Rationale**: Nebius Token Factory billing is unavailable in some countries, including the
owner's, and NVIDIA's API can require a manual account verification first. Personal mode keeps
the agent useful without weakening a single hackathon rule.

## Development Workflow & Quality Gates

- **Spec-driven flow**: Every feature MUST go through `/sp.specify` → `/sp.plan` → `/sp.tasks`
  → `/sp.implement`, using `/sp.clarify` whenever the spec has open questions and `/sp.analyze`
  before implementation. Artifacts live in `specs/<feature>/`.
- **Constitution Check**: Every `plan.md` MUST pass the Constitution Check gate before Phase 0
  research and again after Phase 1 design. Each violation MUST be fixed or justified in the
  plan's Complexity Tracking table.
- **Small increments**: Each task MUST produce a small, testable change, and the agent MUST
  remain runnable after every completed task.
- **Definition of Done** for every task:
  - relevant tests exist and the offline suite passes;
  - lint, format, and type checks pass;
  - the README and `.env.example` reflect any user-visible change;
  - no secrets appear in code, logs, or traces;
  - the Constitution Check still holds.
- **Records**: Every user prompt MUST produce a Prompt History Record under `history/prompts/`.
  Architecturally significant decisions MUST be suggested as ADRs and created under
  `history/adr/` only with the user's consent.
- **Pre-submission gate**, where every item MUST pass:
  1. A fresh clone reaches a successful agent run on Token Factory, with an NVIDIA model and
     Sandboxes, by following only the README Quickstart.
  2. The offline test suite passes from that fresh clone.
  3. No non-Nebius inference endpoint is hardcoded or set as a default anywhere.
  4. The MIT `LICENSE` is visible at the top of the repository page, and dependency licenses
     are compatible.
  5. The README is complete per Principle VI, and every demo scenario runs on a real public
     repository.
  6. Judge access works: the demo URL or test build runs as documented, and the budgets and
     credits behind it cover the judging period.
  7. Every Devpost item in Hackathon Submission Requirements is complete.
  8. Every MUST in this constitution has been reviewed and is satisfied.

## Governance

- This constitution supersedes conflicting project practices, templates, and guidance files.
  `CLAUDE.md` holds runtime guidance for AI agents and MUST NOT contradict this document; when a
  conflict appears, the conflicting artifact is corrected.
- **Amendments** MUST be made through `/sp.constitution` and MUST include an updated Sync Impact
  Report, a version bump, an updated Last Amended date, propagation to dependent templates, and
  a PHR under `history/prompts/constitution/`. The hackathon rules in Principle I and the
  Hackathon Submission Requirements change only when the official hackathon rules or organizer
  guidance change, and such an amendment MUST cite the source. The project owner MAY add or
  change modes outside the hackathon configuration (such as Personal Mode) as long as they never
  relax it; such an amendment MUST record the owner's decision and its date. Hackathon facts
  here were checked against the official pages on 2026-10-03 and MUST be rechecked before
  submission.
- **Versioning** follows semantic versioning:
  - MAJOR: removing or redefining a principle, or any backward-incompatible governance change.
  - MINOR: adding a principle or section, or materially expanding existing guidance.
  - PATCH: clarifications, wording, and typo fixes that do not change meaning.
- **Compliance review**: `/sp.plan` enforces the Constitution Check gate, `/sp.analyze` treats
  every constitution violation as CRITICAL, and the pre-submission gate verifies every MUST.
  Deviations MUST be justified in the plan's Complexity Tracking table, and architecturally
  significant ones MUST be proposed as ADRs.

**Version**: 2.2.0 | **Ratified**: 2026-09-28 | **Last Amended**: 2026-10-15
