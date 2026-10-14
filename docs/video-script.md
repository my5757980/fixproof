# Demo video script (under 3 minutes)

A pitch: problem, solution, live run, parallel branches, evidence and patch, how Token Factory
and Nemotron are used, impact. Everything shown must be a real run on Nebius Token Factory and
Token Factory Sandboxes (Constitution I): no Docker executor, no `FIXPROOF_ALLOW_DEV`, no
replays presented as live.

Values in brackets come from the recorded run and the benchmark results.

## Script and shot list

| Time | Shot | Voice-over |
|---|---|---|
| 0:00–0:15 | Title card: "FixProof: bug fixes with proof". Then a GitHub issue with no test, next to an AI chat saying "Fixed!" | "AI coding agents say 'fixed' all the time. Maintainers can't trust that without proof, and checking every fix by hand is slow." |
| 0:15–0:30 | The web demo's start page (demo URL visible) | "FixProof is an autonomous agent that fixes bugs in real Python repositories and proves every fix by running tests in Nebius Token Factory Sandboxes, with NVIDIA Nemotron models." |
| 0:30–0:45 | Click a one-click sample ([sample name]); the plan appears within seconds | "I pick a real bug from [repository]. Nemotron 3 Ultra reads the issue and the file tree and shows a plan before anything runs." |
| 0:45–1:15 | The live event stream: setup and install in the sandbox, baseline test run, the reproduction test failing | "The repository is installed in a sandbox and its test suite runs. Then Nemotron 3 Super writes a test that reproduces the bug. It must fail first, or the run stops." |
| 1:15–1:40 | Edits, test runs, then the verification event: reproduction passes 3 of 3, no regressions; the label **Verified** | "The worker edits the code and runs the tests. Then the harness, not the model, verifies: the reproduction test passes three times in a row and nothing that passed before breaks." |
| 1:40–2:00 | The hypotheses table of a parallel run (`--parallel 3`) | "In parallel mode, the planner proposes three hypotheses, and each one runs on its own sandbox branch from the same snapshot. The smallest verified fix wins." |
| 2:00–2:20 | The report: root cause with file and line citations, evidence, patch download; then `fixproof pr` asking `[y/N]` and the draft pull request | "You get the root cause with citations, the evidence, and the patch. Applying it or opening a pull request always needs your approval." |
| 2:20–2:40 | Architecture slide: Ultra planner, Super worker, Nano fallback on Token Factory; Sandboxes snapshots and branches | "One Token Factory endpoint serves all three Nemotron models by role, with fallback. Sandboxes give us checkpoints and branches, so every attempt starts clean." |
| 2:40–2:55 | Benchmark table from the README | "On [N] real bugs from SWE-bench Verified, FixProof verified [X]. Every verified fix passed an independent re-check, and the hidden reference tests agreed [Y] of [Z] times." |
| 2:55–3:00 | End card: repository URL, demo URL | "FixProof: fixes you can trust. Try it at [demo URL]." |

## Recording checklist

- [ ] `/api/health` shows `executor: contree` and `live_runs_available: true` before recording.
- [ ] The run shown live is a real run (not a REPLAY); its run ID is noted for reference.
- [ ] Screen text is readable at 1080p; secrets never appear on screen (no `.env`, no console
      pages with keys).
- [ ] Final length is under 3:00; uploaded to YouTube as public; link added to the Devpost form
      and `docs/submission-checklist.md`.
