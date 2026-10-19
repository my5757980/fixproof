"use strict";

// FixProof judge demo: talks to /api (contracts/openapi.yaml) and renders the live event stream.
// Everything that comes from repositories, issues, or models is shown with textContent only.

const EVENT_TYPES = [
  "run_started", "phase_changed", "repo_fetched", "sandbox_op", "snapshot", "install_result",
  "test_run", "plan", "hypotheses", "model_call", "reasoning", "tool_call", "tool_result",
  "repro_status", "verification", "attempt_finished", "budget", "error", "report", "run_finished",
];
const DETAIL_TYPES = new Set(["sandbox_op", "snapshot", "model_call", "reasoning"]);
const LABELS = { verified: "Verified", needs_review: "Needs review", not_verified: "Not verified" };
const REPO_PATTERN = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?$/;
const TASK_LABELS = {
  issue: ["Issue URL", "https://github.com/owner/repo/issues/123"],
  failing_test: ["Failing test ID", "tests/test_module.py::test_name"],
  description: ["Bug description", "What goes wrong, and what you expected instead"],
};

const $ = (id) => document.getElementById(id);
let source = null;
let run = null; // { id, replay, finished, evidence: Map }

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let body = null;
  try { body = await response.json(); } catch (_) { body = null; }
  return { status: response.status, body };
}

function setHidden(id, hidden) { $(id).hidden = hidden; }

// -- start panel ---------------------------------------------------------------------------

async function loadHealth() {
  const { status, body } = await api("/api/health");
  const health = $("health");
  if (status !== 200 || !body) { health.textContent = "The service is not reachable."; return; }
  const platform = $("platform");
  platform.textContent = body.platform_note || "";
  platform.hidden = !body.platform_note;
  health.textContent = body.live_runs_available
    ? `Live runs available. Budget left today: $${body.budget_remaining_usd.toFixed(2)}. ` +
      `Active runs: ${body.active_runs}, queued: ${body.queue_length}.`
    : `Live runs are paused: ${body.reason || "unavailable"} You can watch a recorded run below.`;
  health.className = body.live_runs_available ? "health ok" : "health paused";
}

async function loadSamples() {
  const { body } = await api("/api/samples");
  const box = $("samples");
  box.replaceChildren();
  for (const sample of body || []) {
    const button = el("button", sample.title, "sample");
    button.type = "button";
    const meta = el("span", `${sample.repo_url.replace("https://github.com/", "")} · up to ${sample.expected_minutes} min`, "sample-meta");
    button.append(meta);
    button.addEventListener("click", () => startRun({ sample_id: sample.id }));
    box.append(button);
  }
}

async function loadReplays(highlight) {
  const { body } = await api("/api/replays");
  const box = $("replays");
  box.replaceChildren();
  if (!body || body.length === 0) return;
  box.append(el("h3", "Recorded runs (REPLAY)"));
  for (const entry of body) {
    const button = el("button", `REPLAY: ${entry.title} (${LABELS[entry.label] || entry.label})`, "replay-button");
    button.type = "button";
    if (entry.name === highlight) button.classList.add("highlight");
    button.addEventListener("click", () => openReplay(entry));
    box.append(button);
  }
}

function showFormError(message) { $("form-error").textContent = message || ""; }

function showLimit(message, replaySuggestion) {
  const notice = $("limit-message");
  notice.textContent = message || "Live runs are not available right now.";
  notice.hidden = false;
  loadReplays(replaySuggestion);
}

async function startRun(payload) {
  showFormError("");
  setHidden("limit-message", true);
  const { status, body } = await api("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (status === 202 && body) {
    sessionStorage.setItem(`fixproof-token:${body.run_id}`, body.control_token);
    openRun(body.run_id, body.events_url, false);
    if (body.status === "queued") {
      notice(`Queued: ${body.queue_position} run(s) ahead of yours. It starts automatically.`);
    }
    return;
  }
  if (status === 429 || status === 503) { showLimit(body && body.message, body && body.replay_suggestion); return; }
  if (status === 422) { showFormError("Please check the repository URL and the task."); return; }
  showFormError((body && body.message) || "The request was rejected.");
}

function onTaskKindChange() {
  const [label, placeholder] = TASK_LABELS[$("task-kind").value];
  $("task-value-label").textContent = label;
  $("task-value").placeholder = placeholder;
}

function onSubmit(event) {
  event.preventDefault();
  const repoUrl = $("repo-url").value.trim();
  const kind = $("task-kind").value;
  const value = $("task-value").value.trim();
  if (!REPO_PATTERN.test(repoUrl)) { showFormError("Use a public repository URL like https://github.com/owner/repo."); $("repo-url").focus(); return; }
  if (!value) { showFormError("Describe the task."); $("task-value").focus(); return; }
  if (kind === "issue" && !value.startsWith(repoUrl.replace(/\/$/, "") + "/issues/")) {
    showFormError("The issue must belong to the same repository."); $("task-value").focus(); return;
  }
  startRun({ repo_url: repoUrl, task: { kind, value } });
}

// -- run panel -----------------------------------------------------------------------------

function resetRunPanel(replay) {
  if (source) source.close();
  run = { id: null, replay, finished: false, evidence: new Map() };
  for (const id of ["plan", "timeline", "evidence", "diff"]) $(id).replaceChildren();
  $("report").replaceChildren(el("p", "The report appears when the run ends.", "hint"));
  $("plan-note").textContent = "";
  $("budget").textContent = "No model calls yet.";
  $("run-meta").textContent = "";
  setHidden("run-notice", true);
  setHidden("patch-link", true);
  setHidden("replay-banner", !replay);
  setHidden("stop-button", replay);
  $("stop-button").disabled = false;
  setBadge(null);
  setHidden("start-panel", true);
  setHidden("run-panel", false);
  $("run-title").focus();
}

function openRun(runId, url, replay) {
  resetRunPanel(replay);
  run.id = runId;
  $("run-title").textContent = replay ? "Recorded run" : "Live run";
  $("run-meta").textContent = runId;
  source = new EventSource(url);
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (message) => handle(JSON.parse(message.data)));
  }
  source.onerror = () => { if (run && run.finished && source) source.close(); };
}

function openReplay(entry) {
  openRun(entry.name, `/api/replays/${encodeURIComponent(entry.name)}/events?speed=4`, true);
  $("run-meta").textContent = `${entry.title} · recorded ${new Date(entry.recorded_at).toLocaleString()}`;
}

function notice(text) {
  const node = $("run-notice");
  node.textContent = text;
  node.hidden = false;
}

function setBadge(label) {
  const badge = $("label-badge");
  badge.textContent = label ? LABELS[label] || label : run && run.replay ? "Replaying" : "Running";
  badge.className = `badge badge-${label || "running"}`;
}

function addLine(text, type, ok) {
  const item = el("li", text, `event event-${type}${ok === false ? " event-bad" : ""}`);
  if (DETAIL_TYPES.has(type)) item.classList.add("detail");
  item.hidden = DETAIL_TYPES.has(type) && !$("show-details").checked;
  $("timeline").append(item);
  item.scrollIntoView({ block: "nearest" });
}

function counts(c) { return `${c.passed} passed, ${c.failed} failed, ${c.error} errors`; }

function setEvidence(key, label, value) {
  run.evidence.set(key, [label, value]);
  const body = $("evidence");
  body.replaceChildren();
  for (const [name, text] of run.evidence.values()) {
    const row = el("tr");
    row.append(el("th", name), el("td", text));
    body.append(row);
  }
}

function handle(event) {
  const d = event.data;
  switch (event.type) {
    case "run_started":
      $("run-meta").textContent = `${run.replay ? "REPLAY · " : ""}${d.repo_url} · ${d.task.kind} · sandbox: ${d.executor} · ${event.run_id}`;
      addLine(`Run started on ${d.repo_url}`, event.type);
      break;
    case "phase_changed": addLine(`Phase: ${d.to.replace("_", " ")}`, event.type); break;
    case "repo_fetched": addLine(`Fetched commit ${String(d.resolved_sha).slice(0, 12)} (${d.size_kb} KB)`, event.type); break;
    case "install_result": addLine(`Install: ${d.command} → exit ${d.exit_code}`, event.type, d.exit_code === 0); break;
    case "test_run":
      addLine(`Tests ${d.test_run_id} [${d.selector || "full suite"}]: ${counts(d.counts)}${d.timed_out ? " (timed out)" : ""}`, event.type);
      if (!d.selector && !run.evidence.has("baseline")) setEvidence("baseline", "Baseline (before any change)", counts(d.counts));
      break;
    case "plan": renderPlan(d); addLine(`Plan (${d.stage}) published`, event.type); break;
    case "tool_call": addLine(`→ ${d.tool}: ${d.purpose}`, event.type); break;
    case "tool_result": addLine(`   ${d.ok ? "ok" : "error"}: ${d.summary}`, event.type, d.ok); break;
    case "repro_status":
      setEvidence("repro", "Reproduction test", d.repro_test_id ? `${d.repro_test_id} (${d.created ? "written by the agent" : "from the task"})` : "none");
      setEvidence("before", "Fails before the fix", d.fails_before ? "yes" : "no");
      addLine(`Reproduction: ${d.repro_test_id || "none"}, fails before the fix: ${d.fails_before}`, event.type, d.fails_before);
      break;
    case "verification":
      setEvidence("after", "Passes after the fix", d.repro_passes.map((p) => (p ? "pass" : "fail")).join(", "));
      setEvidence("regressions", "Regressions", d.regressions.length ? d.regressions.join(", ") : "none");
      setEvidence("modified", "Existing tests modified", d.modified_test_files.length ? d.modified_test_files.join(", ") : "none");
      addLine(`Verification by the harness: ${LABELS[d.label] || d.label}`, event.type, d.label === "verified");
      break;
    case "budget":
      $("budget").textContent = `${d.steps_used} model calls · ${Math.round(d.seconds_elapsed)} s · $${d.cost_usd.toFixed(4)}${d.limit_hit ? ` · limit reached: ${d.limit_hit}` : ""}`;
      break;
    case "error": addLine(`${d.fatal ? "Error" : "Warning"} (${d.where}): ${d.message}`, event.type, false); break;
    case "report": renderReport(d); break;
    case "run_finished": finish(d); break;
    case "model_call": addLine(`Model ${d.role}: ${d.model} (${d.prompt_tokens}+${d.completion_tokens} tokens)`, event.type); break;
    case "sandbox_op": addLine(`Sandbox ${d.op}: ${String(d.command).slice(0, 120)} → exit ${d.exit_code}`, event.type); break;
    case "reasoning": addLine(`Reasoning (${d.role}): ${String(d.text).slice(0, 300)}`, event.type); break;
    default: break;
  }
}

function renderPlan(d) {
  $("plan-note").textContent = `${d.stage === "initial" ? "Initial plan, from the task and the file list" : "Refined plan"}${d.understanding ? `: ${d.understanding}` : ""}`;
  const list = $("plan");
  list.replaceChildren(...d.steps.map((step) => el("li", step)));
}

function inlineCode(text) {
  // Render `code` spans; everything else stays plain text.
  const paragraph = el("p");
  String(text).split("`").forEach((part, index) => {
    paragraph.append(index % 2 === 1 ? el("code", part) : document.createTextNode(part));
  });
  return paragraph;
}

function renderReport(d) {
  const box = $("report");
  box.replaceChildren(
    el("p", `${LABELS[d.label] || d.label} · stop reason: ${d.stop_reason.replaceAll("_", " ")}`, "report-label"),
    el("h4", "Summary"),
    el("p", d.summary),
    el("h4", "Root cause"),
    ...String(d.root_cause_md || "Not established.").split(/\n{2,}/).map(inlineCode),
  );
  if (d.flags.length) {
    box.append(el("h4", "Flags"));
    const list = el("ul");
    for (const flag of d.flags) list.append(el("li", flag));
    box.append(list);
  }
}

async function finish(d) {
  run.finished = true;
  if (source) source.close();
  setBadge(d.label);
  setHidden("stop-button", true);
  addLine(`Finished: ${LABELS[d.label] || d.label} (${d.stop_reason.replaceAll("_", " ")}) in ${Math.round(d.duration_s)} s, $${d.cost_usd.toFixed(4)}`, "run_finished", d.label === "verified");
  if (!run.replay && d.patch_available) {
    const url = `/api/runs/${encodeURIComponent(run.id)}/patch`;
    const response = await fetch(url);
    if (response.ok) renderDiff(await response.text());
    else $("diff").replaceChildren(el("span", "Could not load the patch; try the download link.", "note"));
    const link = $("patch-link");
    link.href = url;
    link.hidden = false;
  } else {
    const note = run.replay
      ? "Replays show the timeline and the report; the patch file comes only with live runs."
      : "This run produced no patch.";
    $("diff").replaceChildren(el("span", note, "note"));
  }
  loadHealth();
}

function renderDiff(text) {
  const box = $("diff");
  box.replaceChildren();
  for (const line of text.split("\n")) {
    let kind = "";
    if (line.startsWith("+") && !line.startsWith("+++")) kind = "add";
    else if (line.startsWith("-") && !line.startsWith("---")) kind = "del";
    else if (line.startsWith("@@")) kind = "hunk";
    box.append(el("span", `${line}\n`, kind));
  }
}

async function stopRun() {
  const token = sessionStorage.getItem(`fixproof-token:${run.id}`);
  const button = $("stop-button");
  button.disabled = true;
  const { status, body } = await api(`/api/runs/${encodeURIComponent(run.id)}/stop`, {
    method: "POST",
    headers: token ? { "X-Run-Token": token } : {},
  });
  if (status === 202) notice("Stopping. Partial results will be shown within 10 seconds.");
  else { button.disabled = false; notice((body && body.message) || "Could not stop the run."); }
}

function backToStart() {
  if (source) source.close();
  setHidden("run-panel", true);
  setHidden("start-panel", false);
  loadHealth();
  loadReplays();
}

document.addEventListener("DOMContentLoaded", () => {
  $("run-form").addEventListener("submit", onSubmit);
  $("task-kind").addEventListener("change", onTaskKindChange);
  $("stop-button").addEventListener("click", stopRun);
  $("new-run").addEventListener("click", backToStart);
  $("show-details").addEventListener("change", (event) => {
    for (const item of document.querySelectorAll("#timeline .detail")) item.hidden = !event.target.checked;
  });
  onTaskKindChange();
  loadHealth();
  loadSamples();
  loadReplays();
});
