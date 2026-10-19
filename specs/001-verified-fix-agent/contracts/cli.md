# Contract: Command-Line Interface

**Feature**: `001-verified-fix-agent` | Entry point: `fixproof` (`[project.scripts]` in
`pyproject.toml`). Run it with `uv run fixproof ...`.

Configuration comes from environment variables or `.env` (see `.env.example`). Command-line flags
override configuration for a single run. Output is human-readable (Rich), with `--json` for
machine-readable output where noted.

| Command | Purpose | Key options | Exit codes |
|---------|---------|-------------|------------|
| `fixproof fix` | Run the agent on one task (Stories 1 and 3) | `--repo URL` (required); exactly one of `--issue URL` / `--test NODEID` / `--bug TEXT`; `--ref REF`; `--parallel N` (1–3, default 1); `--max-steps N`; `--max-minutes N`; `--max-cost USD`; `--out DIR` (default `runs/`); `--verbose` (show reasoning); `--json` (print the final report JSON) | `0` verified, `10` needs review, `20` not verified, `30` stopped or budget, `40` setup failed or not reproducible, `2` invalid input, `1` internal error |
| `fixproof replay` | Re-play a recorded trace in the terminal, labeled REPLAY | `TRACE_PATH`; `--speed X` (default 4) | `0`, `2` |
| `fixproof apply` | Apply a run's patch to a local checkout after confirmation (Story 4) | `RUN_DIR`; `--to PATH` (default `.`); `--yes` is **not** supported. Confirmation is always interactive. | `0` applied, `3` declined, `4` patch does not apply, `2` |
| `fixproof pr` | Open a pull request with the user's own `GITHUB_TOKEN` after confirmation (Story 4) | `RUN_DIR`; `--title TEXT`; `--draft` (default on) | `0` opened, `3` declined, `5` GitHub error, `2` |
| `fixproof bench run` | Run the benchmark (FR-023) | `--tasks bench/tasks.toml`; `--only ID[,ID]`; `--parallel N`; `--out bench/results/<date>`; `--compare-single` (also run single-path for SC-007) | `0` finished (results file written), `1` |
| `fixproof bench report` | Summarize results into a Markdown table for the README | `RESULTS_DIR`; `--json` | `0`, `2` |
| `fixproof doctor` | Check configuration and access: keys present, `/v1/models` contains the configured IDs, sandbox reachable (lists one image), executor type | `--json` | `0` all good, `6` problems found (each with a fix hint) |
| `fixproof serve` | Start the web demo (Story 2) | `--host 0.0.0.0`; `--port 7860` | `0` |
| `fixproof showcase` | Write a static showcase site: the web UI playing the labeled replays in the browser, with no server and no live runs | `OUT_DIR` (new or empty); `--replays DIR` (default `replays/`) | `0`, `2` |

## Behavior guarantees

- `fix` prints the plan before any edit and then streams one line per event (`trace-events.md`).
  Ctrl+C stops the run within 10 seconds, writes partial results, and exits `30`.
- Every run writes `runs/<run_id>/` with `trace.jsonl`, `report.md`, `report.json`, and
  `patch.diff` (if any).
- `apply` and `pr` show the full diff and the evidence summary, then ask `Apply this patch? [y/N]`.
  Anything other than `y` or `yes` declines.
- `apply` and `pr` refuse runs whose label is `not_verified` unless `--force-unverified` is given.
  Even then, they print a warning and still require confirmation.
- When `FIXPROOF_EXECUTOR=docker`, every command prints the banner
  `DEV ONLY — not Token Factory Sandboxes`.
- A base URL override that does not point at Nebius Token Factory prints a dev-only warning.
- `serve` refuses to start with either dev setting (Docker executor or non-Nebius endpoint) unless
  `FIXPROOF_ALLOW_DEV=1` is set, for local UI testing only. The README documents that
  `FIXPROOF_ALLOW_DEV` must never be set for the public demo or the video (Constitution I).
