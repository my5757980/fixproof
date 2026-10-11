# ADR-0008: Judge Demo Hosting and Access Control

> **Scope**: Document decision clusters, not individual technology choices. Group related decisions that work together (e.g., "Frontend Stack" not separate ADRs for framework, styling, deployment).

- **Status:** Accepted
- **Date:** 2026-10-11
- **Feature:** 001-verified-fix-agent
- **Context:** Judges must be able to use a working demo free of charge, without contacting the
  team, until judging ends on 2026-12-15 (FR-017). The demo is public, so it must bound abuse and
  spending (FR-018) and must never run on dev settings (Constitution I). Our Nebius account is
  blocked by the billing-country issue, so Nebius hosting cannot be assumed; the FAQ confirms that
  only the model call must go through Token Factory. Credits are limited (about $50). Status:
  planned for Phase 4; the demo-safety guard already exists (`src/fixproof/sandbox/factory.py`).

## Decision

- **Hosting**: a `Dockerfile` deployed to Hugging Face Spaces (Docker SDK, free CPU tier,
  port 7860). Model calls still go to Token Factory and code runs in Token Factory Sandboxes. If
  Nebius access permits later, Nebius hosting may replace Spaces (recorded in a superseding ADR).
- **Demo-safety guard**: the server refuses to start with the Docker executor or a non-Nebius
  model endpoint unless `FIXPROOF_ALLOW_DEV=1`, which is for local UI testing only and is never
  set for the public demo or the video.
- **Guardrails (configurable)**: at most 2 concurrent live runs with a FIFO queue; 3 runs per
  visitor (hashed IP) per day; a $2 daily cap that includes estimated sandbox cost; a $0.60
  per-run cap (30 steps, 10 minutes); public GitHub repositories of 50 MB or less; 3 curated
  one-click samples.
- **Fallback**: when a cap is reached or funding runs out, the page offers a labeled replay of a
  recorded real run (ADR-0007).
- **Control**: stopping a run requires a per-run control token returned at creation; only its
  SHA-256 hash is stored. The demo never offers apply or pull-request actions (FR-016).
- **State**: the daily budget lives in `FIXPROOF_STATE_DIR` (default `runs/`). Free Spaces have
  ephemeral disks, so the cap is set conservatively and the state dir can point at persistent
  storage when available.

## Consequences

### Positive

- Free, no-contact access for judges while every model call and every sandbox stays on Nebius.
- Spending and abuse are bounded per visitor, per run, and per day.
- A stopped or exhausted demo still shows real, labeled evidence instead of an error page.
- The same orchestrator and event stream as the CLI, so behavior matches.

### Negative

- Free Spaces sleep when idle: the first visit can take about a minute (documented in the README).
- An ephemeral disk resets the daily budget on restart; IP-based limits are coarse (shared IPs,
  VPNs).
- Hosting on a non-Nebius platform misses a possible bonus for using other Nebius services.
- More moving parts to keep healthy until mid-December (queue, tokens, daily check, uptime job).

## Alternatives Considered

- **Nebius AI Cloud VM**: preferred for the bonus, but blocked by the same billing-country issue
  today. Deferred, not rejected.
- **Render or Koyeb free tiers**: tighter sleep and memory limits. Rejected.
- **Fly.io**: requires a card. Rejected.
- **Judge accounts or logins**: friction that conflicts with "usable without contacting the team".
  Rejected in favor of per-visitor limits.
- **No stop control in the demo**: wastes budget on abandoned runs; an unauthenticated stop would
  let anyone stop anyone's run. Rejected in favor of per-run control tokens.

## References

- Feature Spec: [spec.md](../../specs/001-verified-fix-agent/spec.md) (User Story 2, FR-016–FR-019,
  SC-008)
- Implementation Plan: [plan.md](../../specs/001-verified-fix-agent/plan.md) (D8, D11); research
  R11; [contracts/openapi.yaml](../../specs/001-verified-fix-agent/contracts/openapi.yaml)
- Related ADRs: ADR-0001 (endpoint rule), ADR-0003 (executor guard), ADR-0007 (SSE and replay)
- Evaluator Evidence: `tests/unit/test_factory.py` (demo-safety guard); Phase 4 tests in tasks.md
