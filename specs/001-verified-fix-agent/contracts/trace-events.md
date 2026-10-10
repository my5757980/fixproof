# Contract: Trace Events (JSONL) and Live Stream

**Feature**: `001-verified-fix-agent` | **Constitution**: Principle IV | **Spec**: FR-010, FR-011, SC-005

Every run writes `runs/<run_id>/trace.jsonl`, with one JSON object per line. The same objects are
published on the run's `EventBus`. The CLI renders them, the web demo streams them as SSE
(`event: <type>`, `id: <seq>`, `data: <json>`), and replay re-emits them with `"replay": true`.

## Envelope

```json
{
  "seq": 12,
  "ts": "2026-10-12T09:41:07.231Z",
  "run_id": "run-20261012-094100-a1b2c3",
  "attempt_id": "a1",
  "type": "tool_result",
  "replay": false,
  "data": { }
}
```

- `seq` is strictly increasing per run and starts at 1. `attempt_id` is `null` outside attempts.
- **Redaction**: Before any event is written or published, values of configured secrets
  (`NEBIUS_API_KEY`, `CONTREE_TOKEN`, `GITHUB_TOKEN`, `TAVILY_API_KEY`) and anything matching
  `(?i)(api[_-]?key|token|secret)\s*[:=]\s*\S+` are replaced with `[REDACTED]`.

## Event types

| `type` | When | `data` fields |
|--------|------|---------------|
| `run_started` | Run accepted | `repo_url`, `ref`, `task {kind, value}`, `mode`, `budget`, `models {planner, worker, condenser}`, `sampling {temperature, max_tokens, top_p}` (Constitution IV), `executor` |
| `phase_changed` | Every status transition | `from`, `to` |
| `repo_fetched` | Tarball downloaded | `resolved_sha`, `size_kb` |
| `sandbox_op` | Every sandbox operation | `op` (`upload`, `run`, `read`, `ls`), `image_in`, `image_out`, `command` (redacted), `exit_code`, `elapsed_s`, `disposable` |
| `snapshot` | Key snapshot tagged | `label`, `image_id`, `tag`, `parent_id` |
| `install_result` | After the dependency install | `command`, `exit_code`, `elapsed_s`, `output_tail` |
| `test_run` | Each test execution | `test_run_id`, `selector`, `counts`, `failed_ids` (≤ 50), `timed_out`, `elapsed_s` |
| `plan` | Planner produced a plan: `initial` within 30 s from the task and repository file tree, before install; `refined` after the baseline | `stage` (`initial` \| `refined`), `steps: [str]`, `understanding` |
| `hypotheses` | Parallel mode | `items: [{id, statement, suspected_files}]` |
| `model_call` | Every LLM request | `role`, `model`, `temperature`, `max_tokens`, `top_p` (effective values sent), `prompt_tokens`, `completion_tokens`, `cost_usd`, `elapsed_s`, `fallback_from` (nullable), `has_reasoning` |
| `reasoning` | Only when the model returns reasoning text; verbose view only | `role`, `text` (≤ 4,000 chars) |
| `tool_call` | Model requested a tool | `call_id`, `tool`, `args` (redacted), `purpose` |
| `tool_result` | Tool finished | `call_id`, `tool`, `ok`, `summary` (one line), `error` (nullable), `elapsed_s` |
| `repro_status` | Reproduction checked | `repro_test_id`, `created`, `fails_before: bool` |
| `verification` | Harness verification | `repro_passes: [bool, bool, bool]`, `regressions: [node_id]`, `modified_test_files: [path]`, `label` |
| `attempt_finished` | Attempt ends | `status`, `label`, `changed_lines` |
| `budget` | Every 5 steps and on a limit | `steps_used`, `seconds_elapsed`, `cost_usd`, `limit_hit` (nullable) |
| `error` | Recoverable or fatal error | `where`, `message`, `fatal: bool` |
| `report` | Report built | `label`, `stop_reason`, `summary`, `root_cause_md`, `citations`, `changed_lines`, `flags` |
| `run_finished` | Always last | `label`, `stop_reason`, `duration_s`, `cost_usd`, `patch_available: bool` |

## Guarantees

1. Every `tool_call` has exactly one matching `tool_result` (same `call_id`), unless the run is
   stopped. In that case the dangling call is closed with
   `tool_result {ok: false, error: "stopped"}`.
2. The report only cites actions (edits, commands, test runs) whose events exist in the same trace
   (SC-005). `tests/contract/test_trace_contract.py` enforces this.
3. `run_finished` is emitted for every run, including stops and failures (FR-012).
4. A trace replays deterministically: `fixproof replay <trace.jsonl>` and `/api/replays/...`
   re-emit the events in `seq` order with `replay: true`.
