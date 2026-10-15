---
id: 0036
title: Fix Playwright MCP Connection
stage: general
date: 2026-10-15
surface: agent
model: claude-opus-5-5
feature: none
branch: 001-verified-fix-agent
user: Muhammad Yaseen
command: none
labels: ["tooling", "mcp", "playwright", "windows"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
 - C:\Users\ASFAR\.claude.json (local MCP entry for this project, via `claude mcp`)
 - C:\Users\ASFAR\.claude\settings.json (env.MCP_TIMEOUT)
tests:
 - claude mcp get playwright (Connected)
---

## Prompt

```text
yar tum mcp playwrite khud connect karooooo use karoooo saraaaa kuch khud karoooooo
```

## Response snapshot

Diagnosed why the Playwright MCP server never connects: the project's entry runs
`npx @playwright/mcp@latest`, and on this machine npx needs 125–157 seconds to start even with
the package cached, while Claude Code waits 30 seconds. `node` itself starts in about 2 seconds.

- Copied @playwright/mcp 0.0.83 from the npx cache to `C:\Users\ASFAR\.mcp-servers\playwright`
  and timed it: 14–25 seconds with `node` directly.
- Replaced the local MCP entry with `claude mcp remove/add` so it runs
  `node ...\@playwright\mcp\cli.js`; `claude mcp get playwright` reports Connected.
- Added `MCP_TIMEOUT=60000` to the user settings `env` block (all other settings kept, backup
  written), through the update-config skill.
- The running session still shows the old failed connection; the user needs to reconnect
  playwright once through `/mcp`. After that, Claude can open build.nvidia.com; any password must
  be typed by the user in the browser window.

## Outcome

- ✅ Impact: Playwright MCP can connect again on this slow machine.
- 🧪 Tests: `claude mcp get playwright` → Connected.
- 📁 Files: Claude Code configuration only (no repository files).
- 🔁 Next prompts: the user reconnects via `/mcp`; then Claude uses the browser to get the NVIDIA
  API key into `.env`.
- 🧠 Reflection: Measuring start-up time pinned the cause in minutes; the same fix applies to the
  other npx-based MCP servers.

## Evaluation notes (flywheel)

- Failure modes observed: npx start-up far beyond the MCP timeout on a low-memory machine.
- Graders run and results (PASS/FAIL): MCP health check PASS.
- Prompt variant (if applicable): none
- Next experiment (smallest change to try): none
