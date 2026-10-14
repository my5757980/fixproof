# Nebius and NVIDIA Feedback Log

A running log of our real experience with Nebius Token Factory, Token Factory Sandboxes, and the
NVIDIA Nemotron models. The hackathon requires specific feedback with every submission. This log
keeps it grounded in what actually happened, so each entry is dated.

Entry format: **date**, what we used it for, what worked, what needs improvement.

## Onboarding and billing

- **2026-10-04**: Signing in to Token Factory with Google worked instantly. However, every useful
  page (Playground, API keys, Sandboxes) redirects to a mandatory "Billing details" form, and
  **Pakistan is not in the "Country of residence" list**. The list goes from Oman straight to
  Poland. Without billing we cannot create an API key or apply the $25 promo code, so the
  promotional credits cannot be used at all from an unsupported country.
  - *Improvement*: Let participants redeem hackathon or Builder Program credits without card
    billing (or with a verified hackathon registration), and show the supported-country list
    before sign-up so participants know early.
- **2026-10-10**: Rechecked. Pakistan is still missing. Opened a case in the Nebius Discord forum
  `#token-factory-support`, as the hackathon FAQ directs ("being handled case by case").
  A staff reply in a similar thread (Philippines) says unsupported countries are under internal
  review, with no timeline.
  - *Improvement*: A published timeline, or an official interim route for participants from
    unsupported countries, would remove a lot of uncertainty in a 2-month hackathon.
- **2026-10-14**: Still no staff reply in our Discord thread or by email. Since 2026-10-10, other
  participants have posted the same blocker in the thread, in `#token-factory-support`, and in
  `#devpost-global-ai-hackathon`: more people from Pakistan, and others from Ukraine and Senegal,
  plus students without a payment card. None of those posts had a staff reply either.
  - *Improvement*: One pinned answer for unsupported countries and card-less students would
    help every affected participant at once, instead of many unanswered threads.
- **2026-10-03**: The promo code email is clear, and it states the code must be applied by
  2026-12-31 and does not expire once applied. That is helpful for keeping a judge demo funded
  through the judging period.

## Token Factory inference

- **2026-10-10**: The public model catalog lists the Nemotron 3 family (Nano, Super, Ultra,
  3.5 Lightning) with prices and context sizes, which made role-based model selection easy to
  plan.
  - *Improvement*: Model ID casing differs between pages. For example,
    `nvidia/Nemotron-3-Ultra-550b-a55b`, `nvidia/nemotron-3-super-120b-a12b`, and both
    `nvidia/nvidia-nemotron-3-nano-30b-a3b` and `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` appear. A
    single canonical ID per model would avoid configuration errors.
  - *Improvement*: Both a global base URL (`https://api.tokenfactory.nebius.com/v1/`) and a
    regional one (`https://api.tokenfactory.us-central1.nebius.com/v1/`) are published. A short
    note on when to use which would help.
  - *Improvement*: Reasoning controls for Nemotron 3 Ultra are listed as "Available" but not
    documented (no parameter or system-prompt flag is shown).

## Token Factory Sandboxes

- **2026-10-10**: The SDK docs (`contree-sdk`) clearly cover running commands with timeouts,
  `disposable=False` snapshots, `apply_files`, file reads, and branching from an image. Branching
  is exactly what our "parallel hypotheses" feature needs.
  - *Improvement*: Outbound network access (for example `pip install` from PyPI), CPU, memory,
    disk limits, maximum timeout, and pricing are not documented on the pages we found.
  - *Improvement*: The mini-swe-agent integration page currently shows a stub that raises a
    `RuntimeError`, and the preloaded SWE-bench image names are not listed.
- **2026-10-11**: Built our executor on the installed `contree-sdk` 0.3.6. The SDK itself is
  pleasant: awaiting `image.run(...)` returns a result image, `disposable=False` gives a new
  snapshot, and cancelling the awaiting task also cancels the operation on the server.
  - *Improvement*: The docs we followed describe `ContreeAsyncClient(token, base_url=...)` from
    `contree_client.httpx`, wrapped by `Contree(api_client)`. Version 0.3.6 has no such class; the
    client is `Contree(config=ContreeConfig(auth=IAMAuth(token=..., project_id=..., base_url=...)))`,
    and the project comes from `NEBIUS_PROJECT_ID`, not the `CONTREE_PROJECT` used in the CLI
    docs. One consistent, versioned getting-started page would save a lot of guesswork.
  - *Improvement*: `IAMAuth` treats any field value that matches an environment variable name as
    the name of that variable, which is surprising when passing literal values.
  - *Improvement*: The package ships no type information (`py.typed`), so strict type checkers
    cannot check calls into it.

## Nemotron models

<!-- Add entries once live access is available: tool-calling quality, reasoning, latency. -->
