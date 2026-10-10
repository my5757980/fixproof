from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from fixproof.models import TestOutcome
from fixproof.sandbox.pytest_results import (
    JUNIT_BEGIN,
    JUNIT_END,
    OUT_BEGIN,
    OUT_END,
    build_pytest_command,
    parse_test_output,
)

DATA = Path(__file__).parent / "data"


def wrap(xml: str, console: str = "1 failed, 1 passed") -> str:
    return f"{JUNIT_BEGIN}\n{xml}\n{JUNIT_END}\n{OUT_BEGIN}\n{console}\n{OUT_END}\n"


def parse(xml_file: str, exit_code: int = 1) -> object:
    xml = (DATA / xml_file).read_text(encoding="utf-8")
    return parse_test_output(wrap(xml), exit_code, False, "img-1", None, test_run_id="tr-1")


def test_build_command_contains_markers_and_flags() -> None:
    cmd = build_pytest_command("tests/test_math.py::test_div[2-0]")
    assert "PYTHONDONTWRITEBYTECODE=1 python -m pytest" in cmd
    assert "-p no:cacheprovider" in cmd and "--junitxml=/tmp/fixproof-junit.xml" in cmd
    assert JUNIT_BEGIN in cmd and JUNIT_END in cmd and OUT_BEGIN in cmd and OUT_END in cmd
    assert "tail -c 4000" in cmd
    assert shlex.quote("tests/test_math.py::test_div[2-0]") in cmd


def test_build_command_quotes_selector_tokens() -> None:
    # A selector must never break out into a second shell command: the ';' stays inside a
    # quoted pytest argument, so "rm -rf /" can only ever be passed to pytest as arguments.
    cmd = build_pytest_command("tests/x.py; rm -rf /")
    target = cmd.split("--junitxml=/tmp/fixproof-junit.xml", 1)[1].split(" > ", 1)[0]
    assert "'tests/x.py;'" in target
    assert shlex.split(target) == ["tests/x.py;", "rm", "-rf", "/"]
    assert (
        "$(" not in build_pytest_command("$(whoami)").split("--junitxml")[1].split("'$(whoami)'")[0]
    )


def test_build_command_rejects_unbalanced_quotes() -> None:
    with pytest.raises(ValueError):
        build_pytest_command('tests/x.py "unterminated')


def test_parse_all_passed() -> None:
    run = parse("junit_pass.xml", exit_code=0)
    assert run.counts == {"passed": 2, "failed": 0, "error": 0, "skipped": 0}  # type: ignore[attr-defined]
    assert run.passed_ids == {"tests/test_math.py::test_add", "tests/test_math.py::test_sub"}  # type: ignore[attr-defined]
    assert run.duration_s == pytest.approx(0.031)  # type: ignore[attr-defined]


def test_parse_mixed_outcomes_and_parametrized_ids() -> None:
    run = parse("junit_mixed.xml")
    outcomes = {r.node_id: r.outcome for r in run.results}  # type: ignore[attr-defined]
    assert outcomes["tests/test_math.py::test_add"] is TestOutcome.PASSED
    assert outcomes["tests/test_math.py::test_div[2-0]"] is TestOutcome.FAILED
    assert outcomes["tests/test_math.py::test_skip"] is TestOutcome.SKIPPED
    assert outcomes["tests/test_math.py::test_xfail"] is TestOutcome.SKIPPED
    assert outcomes["tests/test_db.py::test_query"] is TestOutcome.ERROR
    assert run.failed_ids == {"tests/test_math.py::test_div[2-0]", "tests/test_db.py::test_query"}  # type: ignore[attr-defined]
    failure = next(r for r in run.results if r.outcome is TestOutcome.FAILED)  # type: ignore[attr-defined]
    assert failure.message is not None and "ZeroDivisionError" in failure.message


def test_parse_class_based_ids() -> None:
    run = parse("junit_classes.xml", exit_code=0)
    assert run.passed_ids == {  # type: ignore[attr-defined]
        "tests/models/test_user.py::TestUser::test_create",
        "tests/models/test_user.py::TestUser::TestNested::test_inner",
        "test_root.py::test_top",
    }


def test_collection_error_without_xml() -> None:
    stdout = (
        f"{JUNIT_BEGIN}\n\n{JUNIT_END}\n{OUT_BEGIN}\nERROR collecting tests/test_x.py\n{OUT_END}\n"
    )
    run = parse_test_output(stdout, 2, False, "img-1", None, test_run_id="tr-2")
    assert run.results == ()
    assert run.exit_code == 2
    assert "ERROR collecting" in run.output_tail


def test_timeout_flag_and_missing_markers() -> None:
    run = parse_test_output(
        "partial output, killed", -1, True, "img-1", "tests/x.py", test_run_id="tr-3"
    )
    assert run.timed_out is True
    assert run.results == ()
    assert run.selector == "tests/x.py"
    assert "killed" in run.output_tail


def test_long_messages_are_truncated() -> None:
    long_message = "x" * 5000
    xml = (
        '<testsuite><testcase classname="tests.t" name="test_a" file="tests/t.py" time="0.1">'
        f'<failure message="{long_message}">{long_message}</failure></testcase></testsuite>'
    )
    run = parse_test_output(wrap(xml), 1, False, "img-1", None, test_run_id="tr-4")
    assert len(run.results[0].message or "") <= 2000
