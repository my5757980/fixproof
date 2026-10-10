"""Run pytest inside the sandbox and parse its JUnit XML (research.md R7).

The command prints the JUnit XML report and the tail of the console output between unique
markers, so results can be read from stdout of a disposable sandbox run. ``xunit1`` is used
because it includes the ``file`` attribute, which gives exact pytest node IDs.
"""

from __future__ import annotations

import shlex
import xml.etree.ElementTree as ET

from fixproof.models import TestCaseResult, TestOutcome, TestRun

JUNIT_PATH = "/tmp/fixproof-junit.xml"
OUT_PATH = "/tmp/fixproof-pytest-out.txt"
JUNIT_BEGIN = "===FIXPROOF-JUNIT-BEGIN==="
JUNIT_END = "===FIXPROOF-JUNIT-END==="
OUT_BEGIN = "===FIXPROOF-OUT-BEGIN==="
OUT_END = "===FIXPROOF-OUT-END==="

_MESSAGE_LIMIT = 2000
_OUTPUT_TAIL_LIMIT = 4000


def build_pytest_command(
    selector: str | None = None, *, output_tail_chars: int = _OUTPUT_TAIL_LIMIT
) -> str:
    """Build the shell command that runs pytest and prints machine-readable results.

    Each selector token is shell-quoted, so a selector cannot inject extra shell commands.

    Args:
        selector: Node IDs, paths, or pytest options (for example ``-k name``); ``None`` runs the
            whole suite.
        output_tail_chars: How many trailing characters of console output to include.

    Returns:
        A POSIX shell command; its exit code is pytest's exit code.

    Raises:
        ValueError: If the selector has unbalanced quotes.
    """
    target = ""
    if selector:
        try:
            tokens = shlex.split(selector)
        except ValueError as exc:
            raise ValueError(f"invalid test selector {selector!r}: {exc}") from exc
        target = " " + " ".join(shlex.quote(token) for token in tokens)
    pytest_cmd = (
        "PYTHONDONTWRITEBYTECODE=1 python -m pytest -rA -q --color=no -p no:cacheprovider "
        f"-o junit_family=xunit1 --junitxml={JUNIT_PATH}{target}"
    )
    return (
        f"rm -f {JUNIT_PATH} {OUT_PATH}; "
        f"{pytest_cmd} > {OUT_PATH} 2>&1; code=$?; "
        f"echo '{JUNIT_BEGIN}'; cat {JUNIT_PATH} 2>/dev/null; echo; echo '{JUNIT_END}'; "
        f"echo '{OUT_BEGIN}'; tail -c {output_tail_chars} {OUT_PATH} 2>/dev/null; echo; "
        f"echo '{OUT_END}'; exit $code"
    )


def parse_test_output(
    stdout: str,
    exit_code: int,
    timed_out: bool,
    snapshot_id: str,
    selector: str | None,
    *,
    test_run_id: str,
) -> TestRun:
    """Parse the output of ``build_pytest_command`` into a ``TestRun``.

    Missing or empty XML (for example a collection error, or a timeout) yields a ``TestRun``
    with no results; the console tail still explains what happened.

    Args:
        stdout: Combined stdout of the sandbox command.
        exit_code: Exit code of the command (pytest's exit code).
        timed_out: Whether the sandbox killed the command at its timeout.
        snapshot_id: Image the tests ran on.
        selector: The selector that was run, if any.
        test_run_id: ID to give this test run (for example ``tr-3``).

    Returns:
        The parsed test run.
    """
    xml_text = _between(stdout, JUNIT_BEGIN, JUNIT_END)
    console = _between(stdout, OUT_BEGIN, OUT_END)
    if console is None:
        console = stdout
    results: tuple[TestCaseResult, ...] = ()
    duration = 0.0
    if xml_text and xml_text.strip():
        try:
            results, duration = _parse_junit(xml_text)
        except ET.ParseError:
            results, duration = (), 0.0
    return TestRun(
        id=test_run_id,
        snapshot_id=snapshot_id,
        selector=selector,
        results=results,
        exit_code=exit_code,
        duration_s=duration,
        output_tail=console.strip()[-_OUTPUT_TAIL_LIMIT:],
        timed_out=timed_out,
    )


def _between(text: str, begin: str, end: str) -> str | None:
    start = text.find(begin)
    if start == -1:
        return None
    start += len(begin)
    stop = text.find(end, start)
    if stop == -1:
        return text[start:]
    return text[start:stop]


def _parse_junit(xml_text: str) -> tuple[tuple[TestCaseResult, ...], float]:
    root = ET.fromstring(xml_text.strip())
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    results: list[TestCaseResult] = []
    suite_time = 0.0
    for suite in suites:
        suite_time += _float(suite.get("time"))
        for case in suite.iter("testcase"):
            results.append(_parse_case(case))
    duration = suite_time or sum(r.duration_s for r in results)
    return tuple(results), duration


def _parse_case(case: ET.Element) -> TestCaseResult:
    outcome = TestOutcome.PASSED
    message: str | None = None
    for tag, value in (
        ("failure", TestOutcome.FAILED),
        ("error", TestOutcome.ERROR),
        ("skipped", TestOutcome.SKIPPED),
    ):
        child = case.find(tag)
        if child is not None:
            outcome = value
            parts = [child.get("message") or "", (child.text or "").strip()]
            message = "\n".join(p for p in parts if p)[:_MESSAGE_LIMIT] or None
            break
    return TestCaseResult(
        node_id=_node_id(case.get("classname") or "", case.get("name") or "", case.get("file")),
        outcome=outcome,
        duration_s=_float(case.get("time")),
        message=message,
    )


def _node_id(classname: str, name: str, file: str | None) -> str:
    """Build a pytest node ID from JUnit ``classname``, ``name``, and optional ``file``."""
    if not classname:
        return name
    parts = classname.split(".")
    if file:
        module_parts = file.replace("\\", "/").removesuffix(".py").split("/")
        classes = parts[len(module_parts) :] if parts[: len(module_parts)] == module_parts else []
        path = file.replace("\\", "/")
    else:
        split = next((i for i, part in enumerate(parts) if part[:1].isupper()), len(parts))
        path = "/".join(parts[:split]) + ".py"
        classes = parts[split:]
    return "::".join([path, *classes, name])


def _float(value: str | None) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0
