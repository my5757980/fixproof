# Submission checklist

Records of the pre-submission checks (tasks.md T087–T091, constitution pre-submission gate).
Each entry is dated and states what was actually run.

## Fresh-clone reproducibility (T087)

| Date | Step | Result |
|---|---|---|
| 2026-10-14 | `git clone` of commit `a276462` into an empty folder | OK |
| 2026-10-14 | `uv sync --frozen` | OK (all packages from `uv.lock`) |
| 2026-10-14 | `uv run pytest` | 385 passed, 10 skipped (opt-in live and Docker tests) |
| 2026-10-14 | `uv run ruff check .` and `uv run mypy` | Clean (41 source files) |
| pending | `.env` from `.env.example`, `uv run fixproof doctor` | Needs Token Factory and Sandboxes access |
| pending | One real `uv run fixproof fix` on a sample task, following only the README Quickstart | Needs Token Factory and Sandboxes access |

## Judge access (T088)

Pending deployment: the demo URL from a logged-out browser on another network, a sample run in
under 10 minutes, the labeled replay when the daily cap is forced, and credits and keys valid
through 2026-12-15.

## Pre-submission gate (T090)

Pending: every MUST in `.specify/memory/constitution.md`, the 8 gate items, the final lint,
format, type, and test runs, a last check of the Devpost rules and updates pages, and the
`v0.1.0` tag.

## Submission (T091)

Pending: the public YouTube video (under 3 minutes), the Devpost submission (target
2026-10-29), and the final video, demo, and repository links.
