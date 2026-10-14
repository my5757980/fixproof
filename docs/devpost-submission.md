# Devpost submission (draft)

Text for the Devpost form. Values in brackets are filled in after the live runs and the deploy.
All submission materials are in English.

## Name

**FixProof** (working name; the final choice among FixProof, ForkFix, and ReproFix is open).

## Track

Coding and Agentic Engineering.

## Tagline

An autonomous agent that fixes bugs in real Python repositories and proves every fix with tests
in Nebius Token Factory Sandboxes.

## Description

### What we built

FixProof takes a public GitHub repository and a bug (an issue URL, a failing test, or a
description) and works on its own. It plans, installs the repository in a Token Factory
Sandbox, runs the test suite, writes a test that reproduces the bug, fixes the code, and
verifies the fix. The label (Verified, Needs review, or Not verified) comes from the harness's
own test runs, never from the model: a fix is Verified only when the reproduction test passes
three times in a row and no test that passed before fails. The result is a report with the root
cause (with file and line citations), the evidence, and a patch, which the developer can apply
or turn into a draft pull request, always after an explicit approval.

### Why

AI coding agents often claim success without proof, and maintainers cannot trust a fix they did
not verify themselves. FixProof makes verification part of the agent: every claim comes with
evidence that anyone can re-run.

### How it works

- **NVIDIA Nemotron on Nebius Token Factory, by role**: Nemotron 3 Ultra
  (`nvidia/Nemotron-3-Ultra-550b-a55b`) plans, proposes hypotheses, re-diagnoses failed
  verifications, and explains the root cause. Nemotron 3 Super
  (`nvidia/nemotron-3-super-120b-a12b`) runs the tool loop. Nemotron 3 Nano
  (`nvidia/nvidia-nemotron-3-nano-30b-a3b`) is the fallback when a model is unavailable.
- **Token Factory Sandboxes**: every install, test, and command runs in a sandbox. Snapshots
  (source, installed, reproduction) let each attempt start clean, and parallel mode tries up to
  three hypotheses on sandbox branches from the same snapshot; the smallest verified fix wins.
- **Transparency**: the plan appears first, every tool call streams with its purpose, and every
  run writes a JSONL trace with secrets redacted.
- **Safety**: autonomy inside the sandbox, approval at the boundary (apply and pull request),
  budgets on steps, time, and cost, and secrets never enter a sandbox.
- **Measured**: a benchmark of real, already-fixed bugs from SWE-bench Verified re-checks every
  verified fix in a fresh sandbox and compares the label with the official hidden tests.
  Results: [X of N verified, 0 re-check failures, hidden-test agreement Y of Z].

## Links

- Demo: [demo URL] (the first load can take about a minute while the Space wakes up)
- Video: [YouTube URL]
- Repository: [repository URL] (MIT License)

## Built With

Nebius Token Factory, Token Factory Sandboxes, NVIDIA Nemotron 3 Ultra, NVIDIA Nemotron 3
Super, NVIDIA Nemotron 3 Nano, Python, FastAPI, Typer, Pydantic, uv.

## Prior work

FixProof was created during the Submission Period (2026-08-26 to 2026-10-30). The repository's
version-control history shows its development from the first commit.

## Feedback on Token Factory and Nemotron

Summary of `docs/feedback.md`, to be completed after the live runs:

- **Used for**: Nemotron 3 Ultra, Super, and Nano through the Token Factory inference API;
  Token Factory Sandboxes for every command the agent runs.
- **What worked**: [from the live runs]. The model catalog with prices and context sizes made
  role-based model selection easy to plan; the `contree-sdk` design (awaiting a run returns the
  next image, cancellation reaches the server) fits an agent loop well.
- **What needs improvement**: billing countries (Pakistan is not in the list, so a participant
  cannot redeem the hackathon credits without card billing from a supported country); model ID
  casing differs between pages; the Sandboxes docs do not match `contree-sdk` 0.3.6 and do not
  document network access, limits, or pricing; the SDK has no type information.
- **Onboarding**: [from the live runs].
- **Would we use them again**: [answer after the live runs].
