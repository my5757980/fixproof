"""Sanity checks that the test fakes behave like the real components they stand in for."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from fixproof.llm.client import ModelUnavailableError
from fixproof.models import ModelRole, TestCaseResult, TestOutcome
from fixproof.sandbox.executor import (
    git_baseline_command,
    git_diff_command,
    git_name_status_command,
    git_numstat_command,
    parse_patch,
)
from fixproof.sandbox.pytest_results import build_pytest_command, parse_test_output
from tests.fakes.fake_executor import FakeExecutor, make_tarball, outcome
from tests.fakes.fake_model import FakeModelClient, reply_text, reply_tool, unavailable


async def test_fake_executor_round_trip(tmp_path: Path) -> None:
    tarball = make_tarball(
        tmp_path / "repo.tgz",
        {"pkg/core.py": "def f():\n    return 1\n", "tests/test_core.py": "x"},
    )
    ex = FakeExecutor()
    source = await ex.prepare_repo(tarball, "python:3.12")
    assert ex.files(source)["pkg/core.py"].startswith(b"def f")

    def behavior(fs: Mapping[str, bytes], selector: str | None) -> list[TestCaseResult]:
        ok = b"return 2" in fs["pkg/core.py"]
        return [
            outcome(
                "tests/test_core.py::test_f",
                "passed" if ok else "failed",
                None if ok else "assert 1 == 2",
            )
        ]

    ex.test_behavior = behavior

    _, installed = await ex.run(source, git_baseline_command(), timeout_s=60, mutate=True)
    result, same = await ex.run(installed, build_pytest_command(None), timeout_s=60, mutate=False)
    assert same == installed
    run = parse_test_output(
        result.stdout,
        result.exit_code,
        result.timed_out,
        installed.image_id,
        None,
        test_run_id="tr-1",
    )
    assert run.outcome_of("tests/test_core.py::test_f") is TestOutcome.FAILED

    fixed = await ex.write_files(
        installed, {"pkg/core.py": b"def f():\n    return 2\n", "tests/test_repro.py": b"new"}
    )
    result, _ = await ex.run(
        fixed, build_pytest_command("tests/test_core.py"), timeout_s=60, mutate=False
    )
    run = parse_test_output(
        result.stdout,
        result.exit_code,
        False,
        fixed.image_id,
        "tests/test_core.py",
        test_run_id="tr-2",
    )
    assert run.outcome_of("tests/test_core.py::test_f") is TestOutcome.PASSED

    diff, _ = await ex.run(fixed, git_diff_command(), timeout_s=60, mutate=False)
    numstat, _ = await ex.run(fixed, git_numstat_command(), timeout_s=60, mutate=False)
    names, _ = await ex.run(fixed, git_name_status_command(), timeout_s=60, mutate=False)
    patch = parse_patch(diff.stdout, numstat.stdout, names.stdout)
    assert {f.path for f in patch.files} == {"pkg/core.py", "tests/test_repro.py"}
    assert "+    return 2" in patch.unified_diff


async def test_fake_executor_install_switch_and_unknown_command() -> None:
    ex = FakeExecutor({"a.py": "x"})
    snap = await ex.prepare_repo(Path("missing.tgz"), "python:3.12")
    ex.install_failures_remaining = 1
    first, _ = await ex.run(snap, "python -m pip install pytest", timeout_s=60, mutate=True)
    second, _ = await ex.run(snap, "python -m pip install pytest", timeout_s=60, mutate=True)
    assert not first.ok and second.ok
    unknown, _ = await ex.run(snap, "frobnicate", timeout_s=5, mutate=False)
    assert unknown.exit_code == 127


async def test_fake_model_scripts_records_and_raises() -> None:
    fake = FakeModelClient().script(
        ModelRole.WORKER, reply_tool("read_file", path="a.py"), unavailable()
    )
    first = await fake.complete(
        ModelRole.WORKER, [{"role": "user", "content": "fix it"}], tools=[{"type": "function"}]
    )
    assert first.tool_calls[0].name == "read_file"
    assert fake.requests[0].text() == "fix it"
    with pytest.raises(ModelUnavailableError):
        await fake.complete(ModelRole.WORKER, [])
    with pytest.raises(AssertionError):
        await FakeModelClient().complete(ModelRole.PLANNER, [])
    assert reply_text("done").tool_calls == []
