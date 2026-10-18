from __future__ import annotations

import base64
import gzip
import shlex
from pathlib import Path

import pytest

from fixproof.models import TestOutcome
from fixproof.sandbox.docker_dev import OUTPUT_LIMIT
from fixproof.sandbox.pytest_results import (
    JUNIT_BEGIN,
    JUNIT_END,
    JUNIT_GZ_BEGIN,
    JUNIT_GZ_END,
    OUT_BEGIN,
    OUT_END,
    build_pytest_command,
    parse_test_output,
)

DATA = Path(__file__).parent / "data"


def wrap(xml: str, console: str = "1 failed, 1 passed") -> str:
    """The older plain format, still accepted."""
    return f"{JUNIT_BEGIN}\n{xml}\n{JUNIT_END}\n{OUT_BEGIN}\n{console}\n{OUT_END}\n"


def packed(xml: str, console: str = "1 failed, 1 passed") -> str:
    """The format ``build_pytest_command`` prints: console tail, then gzip + base64 XML."""
    payload = base64.b64encode(gzip.compress(xml.encode())).decode()
    return f"{OUT_BEGIN}\n{console}\n{OUT_END}\n{JUNIT_GZ_BEGIN}\n{payload}\n{JUNIT_GZ_END}\n"


def big_suite(count: int) -> str:
    """A JUnit report of ``count`` tests; every tenth one fails with a long message."""
    cases = []
    for i in range(count):
        failure = f'<failure message="boom">{"x" * 300}</failure>' if i % 10 == 0 else ""
        cases.append(
            f'<testcase classname="tests.test_big" name="test_{i}" file="tests/test_big.py" '
            f'time="0.001">{failure}</testcase>'
        )
    body = "".join(cases)
    return (
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}</testsuite></testsuites>'
    )


def parse(xml_file: str, exit_code: int = 1) -> object:
    xml = (DATA / xml_file).read_text(encoding="utf-8")
    return parse_test_output(wrap(xml), exit_code, False, "img-1", None, test_run_id="tr-1")


def test_build_command_contains_markers_and_flags() -> None:
    cmd = build_pytest_command("tests/test_math.py::test_div[2-0]")
    assert "PYTHONDONTWRITEBYTECODE=1 python -m pytest" in cmd
    assert "-p no:cacheprovider" in cmd and "--junitxml=/tmp/fixproof-junit.xml" in cmd
    # One test module that fails to import must not stop every other test from running.
    assert "--continue-on-collection-errors" in cmd
    assert JUNIT_GZ_BEGIN in cmd and JUNIT_GZ_END in cmd and OUT_BEGIN in cmd and OUT_END in cmd
    # The compressed report comes last, because executors keep only the end of long output.
    assert cmd.index(OUT_END) < cmd.index(JUNIT_GZ_BEGIN)
    assert "gzip" in cmd and "base64" in cmd
    assert "tail -c 4000" in cmd
    assert shlex.quote("tests/test_math.py::test_div[2-0]") in cmd


def test_a_large_suite_survives_the_executor_output_limit() -> None:
    """The flask suite (484 tests) wrote more XML than 64 KB, so results were lost (2026-10-18)."""
    xml = big_suite(2000)
    assert len(xml) > 4 * OUTPUT_LIMIT
    stdout = ("console line\n" * 20000 + packed(xml))[-OUTPUT_LIMIT:]
    run = parse_test_output(stdout, 1, False, "img-1", None, test_run_id="tr-9")
    assert run.counts == {"passed": 1800, "failed": 200, "error": 0, "skipped": 0}


def test_a_report_forged_in_the_console_output_is_ignored() -> None:
    forged = packed(
        big_suite(1).replace('<failure message="boom">', "<x>").replace("</failure>", "</x>")
    )
    real = packed(big_suite(1))
    run = parse_test_output(forged + real, 1, False, "img-1", None, test_run_id="tr-10")
    assert run.counts["failed"] == 1


def test_a_damaged_compressed_report_gives_no_results() -> None:
    stdout = f"{OUT_BEGIN}\nboom\n{OUT_END}\n{JUNIT_GZ_BEGIN}\nnot-base64!\n{JUNIT_GZ_END}\n"
    run = parse_test_output(stdout, 2, False, "img-1", None, test_run_id="tr-11")
    assert run.results == () and run.output_tail == "boom"


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
