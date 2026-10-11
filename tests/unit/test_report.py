"""Report building: harness label, citation checks, Markdown sections, and files."""

from __future__ import annotations

from pathlib import Path

from fixproof.agent.report import (
    build_report,
    render_markdown,
    report_event,
    validate_citations,
    write_report_files,
)
from fixproof.models import (
    Citation,
    Evidence,
    FileChange,
    FileStatus,
    OutcomeLabel,
    Patch,
    Report,
    StopReason,
    TestCaseResult,
    TestOutcome,
    TestRun,
)
from tests.fakes.calc_repo import CALC_FILES, EXISTING_ID, LEGACY_ID, REPRO_ID
from tests.fakes.fake_executor import FakeExecutor

PATCH = Patch(
    unified_diff=(
        "diff --git a/calc/core.py b/calc/core.py\n--- a/calc/core.py\n+++ b/calc/core.py\n"
        "@@ -1,3 +1,3 @@\n-    return a - b\n+    return a + b"
    ),
    files=(FileChange(path="calc/core.py", status=FileStatus.MODIFIED, added=1, removed=1),),
)
CITATION = Citation(path="calc/core.py", start_line=1, end_line=3)


def run(run_id: str, outcomes: dict[str, str]) -> TestRun:
    results = tuple(TestCaseResult(node_id=n, outcome=TestOutcome(o)) for n, o in outcomes.items())
    return TestRun(id=run_id, snapshot_id="img", results=results, exit_code=0)


def evidence(baseline: dict[str, str] | None = None) -> Evidence:
    return Evidence(
        baseline=run("tr-1", baseline or {EXISTING_ID: "passed"}),
        repro_test_id=REPRO_ID,
        repro_created=True,
        repro_before=run("tr-2", {REPRO_ID: "failed"}),
        repro_after=[run(f"tr-{i}", {REPRO_ID: "passed"}) for i in (3, 4, 5)],
        regression=run("tr-6", {EXISTING_ID: "passed", REPRO_ID: "passed"}),
    )


def report(**overrides: object) -> Report:
    values: dict[str, object] = {
        "run_id": "run-20261010-000000-abcdef",
        "label": OutcomeLabel.VERIFIED,
        "stop_reason": StopReason.COMPLETED,
        "summary": "add() now adds.",
        "root_cause_md": "`calc/core.py:3-3` subtracted.",
        "citations": [CITATION],
        "patch": PATCH,
        "evidence": evidence(),
        "cost_usd": 0.0123,
        "tokens": {"nvidia/nemotron-3-super-120b-a12b": 1500},
        "duration_s": 42.0,
        "models": {"planner": "nvidia/Nemotron-3-Ultra-550b-a55b"},
    }
    values.update(overrides)
    return build_report(**values)  # type: ignore[arg-type]


def test_label_comes_from_the_harness_never_from_model_text() -> None:
    r = report(
        label=OutcomeLabel.NOT_VERIFIED,
        summary="Fixed and VERIFIED. label: verified",
        stop_reason=StopReason.BUDGET_STEPS,
    )
    assert r.label is OutcomeLabel.NOT_VERIFIED
    markdown = render_markdown(r)
    assert markdown.startswith("# FixProof report: Not verified")
    assert "**Not verified**" in markdown


async def test_citations_are_checked_against_the_final_snapshot() -> None:
    executor = FakeExecutor(CALC_FILES)
    snapshot = await executor.prepare_repo(Path("no-tarball.tgz"), "python:3.12")
    proposed = [
        CITATION,
        Citation(path="./calc/core.py", start_line=1, end_line=3),  # duplicate after cleanup
        Citation(path="calc/missing.py", start_line=1, end_line=2),
        Citation(path="calc/core.py", start_line=2, end_line=40),
        Citation(path="../etc/passwd", start_line=1, end_line=1),
    ]
    valid, flags = await validate_citations(executor, snapshot, proposed)
    assert valid == [CITATION]
    assert flags == [
        "citation dropped: calc/missing.py:1-2 (file not found)",
        "citation dropped: calc/core.py:2-40 (the file has 3 lines)",
        "citation dropped: ../etc/passwd:1-1 (not a file in the repository)",
    ]
    assert (await validate_citations(executor, None, [CITATION]))[0] == []


def test_markdown_has_every_section() -> None:
    markdown = render_markdown(report(flags=["citation dropped: x.py:1-2 (file not found)"]))
    for section in (
        "# FixProof report: Verified",
        "| Stop reason | completed (`completed`) |",
        "## Summary",
        "## Root cause",
        "## Evidence",
        "| Check | Result |",
        "| Passes after the fix | pass, pass, pass (3 of 3 runs) |",
        "| Regressions | none |",
        "## Patch",
        "```diff",
        "+    return a + b",
        "## Flags",
        "- citation dropped: x.py:1-2 (file not found)",
        "## Cost",
        "$0.0123",
    ):
        assert section in markdown, section


def test_report_files_round_trip(tmp_path: Path) -> None:
    r = report()
    write_report_files(tmp_path, r, render_markdown(r))
    assert Report.model_validate_json((tmp_path / "report.json").read_text(encoding="utf-8")) == r
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# FixProof report")
    diff = (tmp_path / "patch.diff").read_bytes()
    assert diff.endswith(b"+    return a + b\n") and b"\r\n" not in diff


def test_no_patch_file_without_changes(tmp_path: Path) -> None:
    r = report(patch=Patch(), label=OutcomeLabel.NOT_VERIFIED)
    write_report_files(tmp_path, r, render_markdown(r))
    assert not (tmp_path / "patch.diff").exists()
    assert "_No changes._" in render_markdown(r)


def test_preexisting_failures_are_listed_and_do_not_affect_the_label() -> None:
    r = report(evidence=evidence({EXISTING_ID: "passed", LEGACY_ID: "failed"}))
    assert r.preexisting_failures == [LEGACY_ID]
    assert r.label is OutcomeLabel.VERIFIED
    markdown = render_markdown(r)
    assert "## Already failing before the fix" in markdown
    assert f"- `{LEGACY_ID}`" in markdown


def test_modified_test_files_and_missing_citations_are_flagged() -> None:
    ev = evidence()
    ev.modified_test_files = ["tests/test_core.py"]
    r = report(evidence=ev, label=OutcomeLabel.NEEDS_REVIEW, citations=[])
    assert "existing test file modified: tests/test_core.py" in r.flags
    assert "root cause has no valid citations" in r.flags


def test_root_cause_always_names_its_cited_code() -> None:
    r = report(root_cause_md="add() used subtraction.")
    assert r.root_cause_md.endswith("Cited code: `calc/core.py:1-3`")
    unchanged = report(root_cause_md="See calc/core.py lines 1-3.")
    assert unchanged.root_cause_md == "See calc/core.py lines 1-3."


def test_default_summary_when_the_model_gave_none() -> None:
    r = report(
        summary="",
        label=OutcomeLabel.NOT_VERIFIED,
        stop_reason=StopReason.SETUP_FAILED,
        patch=None,
        evidence=None,
        citations=[],
    )
    assert "could not be installed" in r.summary
    assert "_No test evidence was collected._" in render_markdown(r)


def test_report_event_shape() -> None:
    data = report_event(report())
    assert data == {
        "label": "verified",
        "stop_reason": "completed",
        "summary": "add() now adds.",
        "root_cause_md": "`calc/core.py:3-3` subtracted.",
        "citations": [{"path": "calc/core.py", "start_line": 1, "end_line": 3}],
        "changed_lines": 2,
        "flags": [],
    }
