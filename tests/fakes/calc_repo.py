"""A tiny ``calc`` repository whose ``add`` subtracts, with simulated pytest semantics.

Test outcomes are computed by executing the current ``calc/core.py`` of a fake sandbox snapshot,
so an edit really changes what the harness sees.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping
from typing import Any

from fixproof.models import TestCaseResult
from tests.fakes.fake_executor import outcome

REPO_URL = "https://github.com/acme/calc"
ISSUE_URL = "https://github.com/acme/calc/issues/7"

CALC_FILES: dict[str, str] = {
    "pyproject.toml": '[project]\nname = "calc"\nversion = "0.1.0"\n',
    "calc/__init__.py": "",
    "calc/core.py": 'def add(a, b):\n    """Return the sum of a and b."""\n    return a - b\n',
    "tests/__init__.py": "",
    "tests/test_core.py": (
        "from calc.core import add\n\n\ndef test_add_zero():\n    assert add(5, 0) == 5\n"
    ),
}
LEGACY_FILES = {
    **CALC_FILES,
    "tests/test_legacy.py": "def test_broken():\n    assert False, 'legacy behaviour'\n",
}

EXISTING_ID = "tests/test_core.py::test_add_zero"
LEGACY_ID = "tests/test_legacy.py::test_broken"
REPRO_PATH = "tests/test_fixproof_repro.py"
REPRO_ID = f"{REPRO_PATH}::test_add_two_numbers"
REPRO_TEST = (
    "from calc.core import add\n\n\ndef test_add_two_numbers():\n    assert add(2, 3) == 5\n"
)
PASSING_PATH = "tests/test_fixproof_other.py"
PASSING_ID = f"{PASSING_PATH}::test_add_zero_again"
PASSING_TEST = (
    "from calc.core import add\n\n\ndef test_add_zero_again():\n    assert add(1, 0) == 1\n"
)

Check = Callable[[Callable[[int, int], int]], bool]

# node ID -> (file that must exist, check on add(), failure message)
KNOWN_TESTS: dict[str, tuple[str, Check, str]] = {
    EXISTING_ID: ("tests/test_core.py", lambda add: add(5, 0) == 5, "assert add(5, 0) == 5"),
    REPRO_ID: (REPRO_PATH, lambda add: add(2, 3) == 5, "AssertionError: assert -1 == 5"),
    PASSING_ID: (PASSING_PATH, lambda add: add(1, 0) == 1, "assert add(1, 0) == 1"),
    LEGACY_ID: ("tests/test_legacy.py", lambda add: False, "AssertionError: legacy behaviour"),
}


def selected(node_id: str, selector: str | None) -> bool:
    """Return whether pytest would run ``node_id`` for ``selector``."""
    if not selector:
        return True
    for token in shlex.split(selector):
        if token.startswith("-"):
            continue
        prefix = token.rstrip("/")
        if node_id == token or node_id.startswith(prefix + "/") or node_id.startswith(token + "::"):
            return True
    return False


def calc_behavior(fs: Mapping[str, bytes], selector: str | None) -> list[TestCaseResult]:
    """Simulate pytest for the calc repository by executing ``calc/core.py``."""
    namespace: dict[str, Any] = {}
    error: str | None = None
    try:
        exec(fs["calc/core.py"].decode(), namespace)
    except Exception as exc:  # a broken edit makes every test error, as in real pytest
        error = f"{type(exc).__name__}: {exc}"
    results = []
    for node_id, (path, check, message) in KNOWN_TESTS.items():
        if path not in fs or not selected(node_id, selector):
            continue
        if error is not None:
            results.append(outcome(node_id, "error", error))
            continue
        try:
            ok = bool(check(namespace["add"]))
        except Exception as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        results.append(outcome(node_id, "passed" if ok else "failed", None if ok else message))
    return results
