---
id: 0008
title: Review Token Factory Home And Catalog
stage: general
date: 2026-10-04
surface: agent
model: claude-opus-5-5
feature: none
branch: main
user: unknown
command: none (chat)
labels: ["token-factory", "model-catalog", "nemotron", "playwright", "roman-urdu"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - none
tests:
 - none
---

## Prompt

```text
https://tokenfactory.nebius.com/  is linik ko open karoo dekhooo
```

## Response snapshot

Opened the Token Factory home page with Playwright (logged-out view): sidebar with Explore, Model
catalog, Inference (Model endpoints, Playground, Prompt presets, Observability), Post-training,
Data Lab, and Sandboxes; a "Get API key" button; an OpenAI-compatible Python sample (base URL
https://api.tokenfactory.nebius.com/v1/, NEBIUS_API_KEY). Read the public Model catalog and listed
the NVIDIA models served publicly: Nemotron-3-Nano-30B-A3B (262K context), Nemotron-3-Nano-Omni,
Nemotron-3-Super-120b-a12b (256K), Nemotron-3-Ultra-550b-a55b (1,024K), Nemotron-3.5-Lightning
(30B, 1,024K), Nemotron-Nano-V2-12b (vision), Llama-3_1-Nemotron-Ultra-253B-v1. Explained that
browsing is public but use (API key, Playground, Sandboxes) still requires billing.

## Outcome

- ✅ Impact: Confirmed the Nemotron 3 family is live on Token Factory, which supports the
  planned planner/worker model roles.
- 🧪 Tests: none
- 📁 Files: none
- 🔁 Next prompts: Resolve access via Nebius Discord; /sp.specify.
- 🧠 Reflection: Catalog display names differ from API model IDs; /sp.plan must confirm the
  exact IDs through the API or docs.

## Evaluation notes (flywheel)

- Failure modes observed: The user was using the same browser at the same time (login tab), so
  agent navigation can collide with user actions.
- Graders run and results (PASS/FAIL): none
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): Open a separate tab for agent browsing.
