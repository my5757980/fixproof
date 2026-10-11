from __future__ import annotations

import pytest

from fixproof.models import FileStatus
from fixproof.sandbox.executor import (
    BASELINE_TAG,
    CommandResult,
    git_baseline_command,
    git_diff_command,
    is_test_path,
    parse_patch,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_a.py", True),
        ("pkg/tests/helpers.py", True),
        ("test_root.py", True),
        ("src/module_test.py", True),
        ("conftest.py", True),
        ("src/pkg/conftest.py", True),
        ("src/pkg/core.py", False),
        ("docs/testing.md", False),
        ("src/contest.py", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected


def test_parse_patch_statuses_and_counts() -> None:
    numstat = (
        "3\t1\tsrc/pkg/core.py\n12\t0\ttests/test_fixproof_repro.py\n"
        "0\t4\ttests/test_old.py\n-\t-\tlogo.png"
    )
    name_status = (
        "M\tsrc/pkg/core.py\nA\ttests/test_fixproof_repro.py\nM\ttests/test_old.py\nA\tlogo.png"
    )
    patch = parse_patch("diff --git ...", numstat, name_status)
    by_path = {f.path: f for f in patch.files}
    assert by_path["src/pkg/core.py"].status is FileStatus.MODIFIED
    assert by_path["tests/test_fixproof_repro.py"].status is FileStatus.ADDED
    assert by_path["tests/test_fixproof_repro.py"].is_test_file is True
    assert by_path["src/pkg/core.py"].is_test_file is False
    assert by_path["logo.png"].added == 0
    assert patch.changed_lines == 3 + 1 + 12 + 0 + 0 + 4
    assert patch.is_empty is False


def test_empty_patch() -> None:
    patch = parse_patch("", "", "")
    assert patch.is_empty and patch.changed_lines == 0


def test_git_commands_use_baseline_tag() -> None:
    assert BASELINE_TAG in git_baseline_command()
    assert "--no-verify" in git_baseline_command()
    assert git_diff_command().endswith(BASELINE_TAG)


def test_command_result_ok() -> None:
    assert CommandResult(stdout="", exit_code=0).ok
    assert not CommandResult(stdout="", exit_code=1).ok
    assert not CommandResult(stdout="", exit_code=0, timed_out=True).ok


def test_patch_command_output_round_trip() -> None:
    from fixproof.sandbox.executor import PATCH_MARKERS, git_patch_command, parse_patch_output

    diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b"
    stdout = (
        f"{PATCH_MARKERS[0]}\n{diff}\n{PATCH_MARKERS[1]}\n1\t1\tx.py\n{PATCH_MARKERS[2]}\nM\tx.py\n"
    )
    patch = parse_patch_output(stdout)
    assert patch.unified_diff == diff + "\n"
    assert [(f.path, f.added, f.removed) for f in patch.files] == [("x.py", 1, 1)]
    assert BASELINE_TAG in git_patch_command()
    empty = parse_patch_output("".join(f"{marker}\n" for marker in PATCH_MARKERS))
    assert empty.is_empty and empty.unified_diff == ""
    with pytest.raises(ValueError):
        parse_patch_output("no markers here")
