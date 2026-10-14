"""Applying a run's patch to a local checkout safely (FR-016, constitution workspace scope).

Every path in the patch must be relative to the checkout, must not contain ``..`` or point into
``.git``, and must not pass through a symbolic link that exists in the target. Only then does
``git apply`` run, and only after the user approved the exact diff. Nothing here runs repository
code: ``git apply`` only writes files.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

_HEADER_PREFIXES = ("--- ", "+++ ")
_RENAME_PREFIXES = ("rename from ", "rename to ", "copy from ", "copy to ")
_DRIVE = re.compile(r"^[A-Za-z]:")


def patch_paths(diff: str) -> list[str]:
    """Return every path named in the headers of a unified diff, as written there."""
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            rest = line[len("diff --git ") :]
            old, separator, new = rest.partition(" b/")
            paths.extend([old, f"b/{new}"] if separator else [rest])
        elif line.startswith(_HEADER_PREFIXES):
            path = line[4:].split("\t", 1)[0]
            if path != "/dev/null":
                paths.append(path)
        elif line.startswith(_RENAME_PREFIXES):
            paths.append("b/" + line.split(" ", 2)[2])
    return paths


def validate_patch(diff: str, target: Path) -> list[str]:
    """Return one problem per unsafe path in ``diff`` for a checkout at ``target``.

    A patch is safe when every path is ``a/<relative path>`` or ``b/<relative path>``, has no
    ``..``, does not touch ``.git``, and passes through no symbolic link inside ``target``.
    """
    problems: list[str] = []
    if not patch_paths(diff):
        return ["the patch names no files"]
    for raw in patch_paths(diff):
        if not raw.startswith(("a/", "b/")):
            problems.append(f"{raw}: not a path relative to the repository")
            continue
        relative = raw[2:]
        pure = PurePosixPath(relative)
        if (
            not relative
            or pure.is_absolute()
            or _DRIVE.match(relative)
            or "\\" in relative
            or ".." in pure.parts
        ):
            problems.append(f"{relative}: absolute paths and '..' are not allowed")
            continue
        if pure.parts[0] == ".git":
            problems.append(f"{relative}: files inside .git cannot be changed")
            continue
        current = target
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                problems.append(f"{relative}: goes through the symbolic link {part}")
                break
    return list(dict.fromkeys(problems))


def git_apply(
    patch_file: Path, target: Path, *, check: bool, keep_line_endings: bool = False
) -> tuple[bool, str]:
    """Run ``git apply`` (or only ``--check``) for ``patch_file`` in ``target``.

    Args:
        patch_file: The unified diff.
        target: The folder to apply it in.
        check: Only check that the patch applies.
        keep_line_endings: Write bytes exactly as patched, ignoring ``core.autocrlf`` (used for
            files that go back to GitHub, which would otherwise get Windows line endings).

    Returns:
        Whether it succeeded, and git's message.
    """
    command = ["git"]
    if keep_line_endings:
        command += ["-c", "core.autocrlf=false"]
    command += ["apply", "--whitespace=nowarn"]
    if check:
        command.append("--check")
    command.append(str(patch_file.resolve()))
    try:
        result = subprocess.run(
            command, cwd=target, capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run git: {exc}"
    return result.returncode == 0, (result.stderr or result.stdout).strip()
