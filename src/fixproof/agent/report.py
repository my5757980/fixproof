"""Run reports: label, evidence, patch, cited root cause, flags, and cost (FR-009, SC-005).

The label is always the harness result; the model only contributes the summary and the
root-cause explanation, and its citations are checked against the final snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from fixproof.agent.verify import find_regressions, repro_passes
from fixproof.models import (
    Citation,
    Evidence,
    OutcomeLabel,
    Patch,
    Report,
    Run,
    Snapshot,
    StopReason,
    TestRun,
)
from fixproof.sandbox.executor import Executor

LABEL_TEXT = {
    OutcomeLabel.VERIFIED: "Verified",
    OutcomeLabel.NEEDS_REVIEW: "Needs review",
    OutcomeLabel.NOT_VERIFIED: "Not verified",
}
STOP_TEXT = {
    StopReason.COMPLETED: "completed",
    StopReason.BUDGET_STEPS: "step budget reached",
    StopReason.BUDGET_TIME: "time budget reached",
    StopReason.BUDGET_COST: "cost budget reached",
    StopReason.USER_STOP: "stopped by the user",
    StopReason.SETUP_FAILED: "setup failed",
    StopReason.NOT_REPRODUCIBLE: "the bug could not be reproduced",
    StopReason.SERVICE_UNAVAILABLE: "a model or sandbox service was unavailable",
    StopReason.INVALID_TOOL_CALLS: "too many invalid tool calls",
    StopReason.INTERNAL_ERROR: "internal error",
}
_DEFAULT_SUMMARIES = {
    StopReason.SETUP_FAILED: "The project could not be installed in the sandbox, so no fix was "
    "attempted.",
    StopReason.NOT_REPRODUCIBLE: "The agent could not write a test that fails before the fix, so "
    "no fix was attempted.",
    StopReason.USER_STOP: "The run was stopped before a fix was verified.",
    StopReason.SERVICE_UNAVAILABLE: "A model or sandbox service was unavailable, so the run ended "
    "early.",
    StopReason.INVALID_TOOL_CALLS: "The model made too many invalid tool calls in a row, so the "
    "run ended.",
    StopReason.INTERNAL_ERROR: "The run ended because of an internal error.",
}


def preexisting_failures(evidence: Evidence | None) -> list[str]:
    """Return tests that already failed at baseline (not flaky, not the reproduction test)."""
    if evidence is None:
        return []
    excluded = set(evidence.baseline_flaky) | {evidence.repro_test_id}
    return sorted(evidence.baseline.failed_ids - excluded)


def default_summary(stop_reason: StopReason, label: OutcomeLabel) -> str:
    """Return a factual summary for runs where no model summary is available."""
    if stop_reason in _DEFAULT_SUMMARIES:
        return _DEFAULT_SUMMARIES[stop_reason]
    if stop_reason in (StopReason.BUDGET_STEPS, StopReason.BUDGET_TIME, StopReason.BUDGET_COST):
        return f"The run reached its budget ({STOP_TEXT[stop_reason]}) before a fix was verified."
    return f"The run finished with the label {LABEL_TEXT[label]}."


async def validate_citations(
    executor: Executor, snapshot: Snapshot | None, citations: Sequence[Citation]
) -> tuple[list[Citation], list[str]]:
    """Keep citations whose file exists in ``snapshot`` and whose lines are in range.

    Args:
        executor: The isolated environment.
        snapshot: The final snapshot; with ``None`` every citation is dropped.
        citations: Citations proposed by the model.

    Returns:
        The valid citations (deduplicated) and one flag per dropped citation.
    """
    valid: list[Citation] = []
    flags: list[str] = []
    line_counts: dict[str, int | None] = {}
    for citation in citations:
        path = citation.path.strip().replace("\\", "/").removeprefix("./")
        where = f"{path}:{citation.start_line}-{citation.end_line}"
        if snapshot is None or not _is_relative(path):
            flags.append(f"citation dropped: {where} (not a file in the repository)")
            continue
        if path not in line_counts:
            line_counts[path] = await _line_count(executor, snapshot, path)
        total = line_counts[path]
        if total is None:
            flags.append(f"citation dropped: {where} (file not found)")
        elif citation.end_line > total:
            flags.append(f"citation dropped: {where} (the file has {total} lines)")
        else:
            cleaned = Citation(
                path=path, start_line=citation.start_line, end_line=citation.end_line
            )
            if cleaned not in valid:
                valid.append(cleaned)
    return valid, flags


def _is_relative(path: str) -> bool:
    pure = PurePosixPath(path)
    return bool(path) and not pure.is_absolute() and ".." not in pure.parts and ":" not in path


async def _line_count(executor: Executor, snapshot: Snapshot, path: str) -> int | None:
    try:
        data = await executor.read_file(snapshot, path)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return None
    return len(data.decode("utf-8", errors="replace").splitlines())


def build_report(
    *,
    run_id: str,
    label: OutcomeLabel,
    stop_reason: StopReason,
    summary: str,
    root_cause_md: str,
    citations: Sequence[Citation],
    patch: Patch | None,
    evidence: Evidence | None,
    flags: Sequence[str] = (),
    cost_usd: float = 0.0,
    tokens: Mapping[str, int] | None = None,
    duration_s: float = 0.0,
    models: Mapping[str, str] | None = None,
) -> Report:
    """Assemble the report. ``label`` must come from the harness (``verify.compute_label``).

    Modified existing test files and missing citations are added as flags, and the root cause
    always names its cited code (FR-009).
    """
    all_flags = [
        f"existing test file modified: {p}"
        for p in (evidence.modified_test_files if evidence else [])
    ]
    all_flags.extend(flag for flag in flags if flag not in all_flags)
    if label is not OutcomeLabel.NOT_VERIFIED and not citations:
        all_flags.append("root cause has no valid citations")
    root_cause = root_cause_md.strip()
    missing = [c for c in citations if c.path not in root_cause]
    if citations and len(missing) == len(citations):
        cited = ", ".join(f"`{c.path}:{c.start_line}-{c.end_line}`" for c in citations)
        root_cause = f"{root_cause}\n\nCited code: {cited}".strip()
    return Report(
        run_id=run_id,
        label=label,
        stop_reason=stop_reason,
        summary=summary.strip() or default_summary(stop_reason, label),
        root_cause_md=root_cause,
        citations=list(citations),
        patch=patch,
        evidence=evidence,
        flags=all_flags,
        preexisting_failures=preexisting_failures(evidence),
        cost_usd=round(cost_usd, 6),
        tokens=dict(tokens or {}),
        duration_s=round(duration_s, 3),
        models=dict(models or {}),
    )


def report_event(report: Report) -> dict[str, Any]:
    """Return the data of the ``report`` trace event."""
    return {
        "label": report.label.value,
        "stop_reason": report.stop_reason.value,
        "summary": report.summary,
        "root_cause_md": report.root_cause_md,
        "citations": [c.model_dump() for c in report.citations],
        "changed_lines": report.patch.changed_lines if report.patch else 0,
        "flags": report.flags,
    }


def render_markdown(report: Report, run: Run | None = None) -> str:
    """Render the report as Markdown (``report.md``)."""
    label = LABEL_TEXT[report.label]
    lines = [f"# FixProof report: {label}", "", "| | |", "|---|---|", f"| Label | **{label}** |"]
    lines.append(
        f"| Stop reason | {STOP_TEXT[report.stop_reason]} (`{report.stop_reason.value}`) |"
    )
    if run is not None:
        revision = run.repo.resolved_sha[:12] if run.repo.resolved_sha else run.repo.ref
        lines.append(f"| Repository | {run.repo.url} @ `{revision or 'default branch'}` |")
        lines.append(f"| Task | {run.task.kind.value}: {_cell(run.task.value)} |")
    lines.append(f"| Run | `{report.run_id}` |")
    lines += ["", "## Summary", "", report.summary]
    lines += ["", "## Root cause", "", report.root_cause_md or "_No root cause was established._"]
    lines += ["", "## Evidence", "", *_evidence_table(report.evidence)]
    if report.preexisting_failures:
        lines += [
            "",
            "## Already failing before the fix",
            "",
            "These tests failed at baseline, before any change. They are listed for information "
            "and do not count against the result.",
            "",
            *(f"- `{node_id}`" for node_id in report.preexisting_failures),
        ]
    lines += ["", "## Patch", "", *_patch_section(report.patch)]
    lines += ["", "## Flags", "", *([f"- {flag}" for flag in report.flags] or ["_None._"])]
    lines += ["", "## Cost", "", *_cost_section(report)]
    return "\n".join(lines) + "\n"


def write_report_files(run_dir: Path, report: Report, markdown: str) -> None:
    """Write ``report.json``, ``report.md``, and (when there is a change) ``patch.diff``."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8", newline="\n"
    )
    (run_dir / "report.md").write_text(markdown, encoding="utf-8", newline="\n")
    if report.patch is not None and not report.patch.is_empty:
        diff = report.patch.unified_diff
        (run_dir / "patch.diff").write_text(
            diff if diff.endswith("\n") else diff + "\n", encoding="utf-8", newline="\n"
        )


def _cell(text: str) -> str:
    flat = " ".join(text.split()).replace("|", "\\|")
    return flat if len(flat) <= 160 else flat[:159] + "…"


def _counts(run: TestRun | None) -> str:
    if run is None:
        return "_not run_"
    c = run.counts
    text = (
        f"{c['passed']} passed, {c['failed']} failed, {c['error']} errors, {c['skipped']} skipped"
    )
    return text + (" (timed out)" if run.timed_out else "")


def _evidence_table(evidence: Evidence | None) -> list[str]:
    if evidence is None:
        return ["_No test evidence was collected._"]
    rows = [("Baseline (full suite before any change)", _counts(evidence.baseline))]
    if evidence.repro_test_id:
        origin = "written by the agent" if evidence.repro_created else "from the task"
        rows.append(("Reproduction test", f"`{evidence.repro_test_id}` ({origin})"))
        before = evidence.repro_before
        fails = before is not None and evidence.repro_test_id in before.failed_ids
        rows.append(("Fails before the fix", "yes" if fails else "_not shown_"))
    else:
        rows.append(("Reproduction test", "_none_"))
    passes = repro_passes(evidence)
    if passes:
        marks = ", ".join("pass" if ok else "fail" for ok in passes)
        rows.append(("Passes after the fix", f"{marks} ({sum(passes)} of 3 runs)"))
    rows.append(("Full suite after the fix", _counts(evidence.regression)))
    if evidence.regression is not None:
        regressions = find_regressions(evidence)
        rows.append(("Regressions", ", ".join(f"`{r}`" for r in regressions[:20]) or "none"))
    modified = ", ".join(f"`{p}`" for p in evidence.modified_test_files) or "none"
    rows.append(("Existing test files modified", modified))
    if evidence.baseline_flaky:
        flaky = ", ".join(f"`{p}`" for p in evidence.baseline_flaky[:20])
        rows.append(("Flaky tests (excluded)", flaky))
    return ["| Check | Result |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows)]


def _patch_section(patch: Patch | None) -> list[str]:
    if patch is None or patch.is_empty:
        return ["_No changes._"]
    files = ", ".join(f"`{f.path}` (+{f.added} -{f.removed})" for f in patch.files)
    return [
        f"{len(patch.files)} file(s), {patch.changed_lines} changed line(s): {files}",
        "",
        "```diff",
        patch.unified_diff.rstrip("\n"),
        "```",
    ]


def _cost_section(report: Report) -> list[str]:
    lines = [f"- Total: ${report.cost_usd:.4f} in {report.duration_s:.0f} s"]
    for role, model in sorted(report.models.items()):
        lines.append(f"- {role}: `{model}`")
    for model, tokens in sorted(report.tokens.items()):
        lines.append(f"- `{model}`: {tokens} tokens")
    return lines
