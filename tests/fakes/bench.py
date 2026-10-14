"""A benchmark task on the calc fake, with a hidden reference test (``add(3, 4) == 7``).

Only the benchmark's after-run check may add the hidden test, in a fresh environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fixproof.models import TestCaseResult
from tests.fakes.calc_repo import EXISTING_ID, REPO_URL, calc_behavior, selected
from tests.fakes.fake_executor import outcome
from tests.fakes.fake_github import DEFAULT_SHA

TASK_ID = "acme__calc-7"
HIDDEN_PATH = "tests/test_hidden.py"
HIDDEN_ID = f"{HIDDEN_PATH}::test_add_hidden"
HIDDEN_TEST = "from calc.core import add\n\n\ndef test_add_hidden():\n    assert add(3, 4) == 7\n"
HIDDEN_PATCH = (
    f"diff --git a/{HIDDEN_PATH} b/{HIDDEN_PATH}\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    f"+++ b/{HIDDEN_PATH}\n"
    "@@ -0,0 +1,5 @@\n" + "".join(f"+{line}\n" for line in HIDDEN_TEST.splitlines())
)
TASKS_TOML = f"""
[[tasks]]
id = "{TASK_ID}"
repo_url = "{REPO_URL}"
base_commit = "{DEFAULT_SHA}"
python = "3.12"
hidden_fail_to_pass = ["{HIDDEN_ID}"]
hidden_pass_to_pass = ["{EXISTING_ID}"]
hidden_test_patch = "hidden/{TASK_ID}.patch"

[tasks.task]
kind = "description"
value = "add() returns the wrong result: add(2, 3) returns -1 instead of 5."
"""


def write_tasks(folder: Path) -> Path:
    """Write the task file and its hidden test patch into ``folder``; return the task file."""
    (folder / "hidden").mkdir(parents=True, exist_ok=True)
    (folder / "hidden" / f"{TASK_ID}.patch").write_text(HIDDEN_PATCH, encoding="utf-8")
    tasks_file = folder / "tasks.toml"
    tasks_file.write_text(TASKS_TOML, encoding="utf-8")
    return tasks_file


def bench_behavior(fs: Mapping[str, bytes], selector: str | None) -> list[TestCaseResult]:
    """The calc tests plus the hidden reference test, when its file exists."""
    results = calc_behavior(fs, selector)
    if HIDDEN_PATH in fs and selected(HIDDEN_ID, selector):
        namespace: dict[str, Any] = {}
        exec(fs["calc/core.py"].decode(), namespace)
        ok = namespace["add"](3, 4) == 7
        results.append(outcome(HIDDEN_ID, "passed" if ok else "failed", None if ok else "-1"))
    return results
