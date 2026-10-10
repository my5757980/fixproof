# FixProof

> Working name. An autonomous coding agent that fixes bugs in real repositories **and proves each
> fix**, using NVIDIA Nemotron models on Nebius Token Factory and running every command in Token
> Factory Sandboxes.

**Status**: under construction for the Nebius x NVIDIA Global AI Hackathon (Coding and Agentic
Engineering track). Sections below are filled in as features land (tasks.md T083).

## What it does and who it is for

<!-- Audience, problem, and the four developer jobs (write, understand, debug, improve). -->

## Hackathon highlights

<!-- Nemotron roles (Ultra planner, Super worker, Nano fallback) with model IDs; where Token
Factory accelerated us (inference + Sandboxes branching); other Nebius services used. -->

## Architecture

<!-- Agent loop overview and diagram. -->

## Tools the agent can use

<!-- Tool table from specs/001-verified-fix-agent/contracts/agent-tools.md. -->

## Prerequisites and credentials

<!-- Python 3.12, uv, Nebius Token Factory API key, Sandboxes access request and project ID. -->

## Quickstart

<!-- One command to run, one command to test (from quickstart.md). -->

## Usage

<!-- Real sample output from a verified run. -->

## Benchmark results

<!-- Verified-fix rate, independent re-check, hidden-test agreement, single vs parallel. -->

## Judge demo

<!-- Demo URL, limits, labeled replay, cold-start note. -->

## Configuration reference

<!-- Every variable from .env.example. -->

## Running the tests

<!-- uv run pytest (offline); live tests with FIXPROOF_LIVE=1. -->

## Safety model

<!-- Sandboxed autonomy, approval at the boundary, secrets handling. -->

## Data that leaves your machine

<!-- Nebius Token Factory (inference, Sandboxes), GitHub (public repo metadata), optional Tavily. -->

## Known limitations

## License and model credits

MIT License (see [LICENSE](LICENSE)). NVIDIA Nemotron models are used under NVIDIA's license
terms for each model; links to each model card and its license will be listed here.
