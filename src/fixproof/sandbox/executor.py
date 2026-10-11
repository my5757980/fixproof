"""The ``Executor`` protocol: the only place repository code runs (FR-002, research R4/R5).

Implementations:

- ``ContreeExecutor``: Token Factory Sandboxes, the default and the only one allowed for the
  demo and video.
- ``DockerExecutor``: dev-only.
- ``FakeExecutor``: lives in ``tests/`` only.

Every command runs in ``REPO_ROOT`` inside the isolated environment. Executors never accept
credential environment variables.

This module also holds the git commands and parsers used to compute a patch against the
baseline commit, made right after the dependency install.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from fixproof.models import FileChange, FileStatus, Patch, Snapshot

REPO_ROOT = "/workspace/repo"
BASELINE_TAG = "fixproof-baseline"
PATCH_MARKERS = ("===FIXPROOF-DIFF===", "===FIXPROOF-NUMSTAT===", "===FIXPROOF-NAME-STATUS===")
GIT_IDENTITY = "-c user.email=agent@fixproof.dev -c user.name=fixproof"

_TEST_FILE_PATTERNS = (
    "tests/*",
    "*/tests/*",
    "test_*.py",
    "*/test_*.py",
    "*_test.py",
    "conftest.py",
    "*/conftest.py",
)


class ExecutorError(RuntimeError):
    """Raised when the isolated environment cannot perform an operation."""


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one command run inside the isolated environment."""

    stdout: str
    stderr: str = ""
    exit_code: int = 0
    elapsed_s: float = 0.0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """Whether the command exited with code 0 before its timeout."""
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class DirEntry:
    """One file or directory in a listing, with a path relative to ``REPO_ROOT``."""

    path: str
    type: Literal["file", "dir"]
    size: int = 0


class Executor(Protocol):
    """Isolated execution environment with snapshots (sandbox image versions)."""

    name: str

    async def prepare_repo(self, tarball_path: Path, base_image: str) -> Snapshot:
        """Extract a repository tarball into ``REPO_ROOT`` and return the resulting snapshot."""
        ...

    async def run(
        self, snapshot: Snapshot, command: str, *, timeout_s: int, mutate: bool
    ) -> tuple[CommandResult, Snapshot]:
        """Run a shell command in ``REPO_ROOT``.

        With ``mutate=False`` the environment is discarded afterwards and the input snapshot is
        returned. With ``mutate=True`` the resulting filesystem becomes a new snapshot.
        """
        ...

    async def read_file(self, snapshot: Snapshot, path: str) -> bytes:
        """Read a file (relative to ``REPO_ROOT``) from a snapshot."""
        ...

    async def list_dir(self, snapshot: Snapshot, path: str = ".", depth: int = 2) -> list[DirEntry]:
        """List files and directories under ``path`` up to ``depth`` levels."""
        ...

    async def write_files(self, snapshot: Snapshot, files: Mapping[str, bytes]) -> Snapshot:
        """Write files (paths relative to ``REPO_ROOT``) and return the new snapshot."""
        ...

    async def tag(self, snapshot: Snapshot, label: str) -> Snapshot:
        """Tag a snapshot so it can be found and branched from later."""
        ...

    async def cancel_all(self) -> None:
        """Cancel every operation still running (used to stop a run within 10 s)."""
        ...

    async def close(self) -> None:
        """Release resources held by the executor."""
        ...


def git_baseline_command() -> str:
    """Return the command that records the current tree as the baseline commit."""
    return (
        "git init -q && git add -A && "
        f"git {GIT_IDENTITY} commit -q --no-verify --allow-empty -m 'fixproof baseline' && "
        f"git tag -f {BASELINE_TAG}"
    )


def git_diff_command() -> str:
    """Return the command printing the unified diff against the baseline, new files included."""
    return f"git add -A && git diff --cached --no-color --no-ext-diff {BASELINE_TAG}"


def git_numstat_command() -> str:
    """Return the command printing ``added<TAB>removed<TAB>path`` per changed file."""
    return f"git add -A && git diff --cached --numstat {BASELINE_TAG}"


def git_name_status_command() -> str:
    """Return the command printing ``A``/``M``/``D`` plus the path per changed file."""
    return f"git add -A && git diff --cached --name-status --no-renames {BASELINE_TAG}"


def git_untracked_command() -> str:
    """Return the command listing untracked files that are not ignored."""
    return "git ls-files --others --exclude-standard"


def is_test_path(path: str) -> bool:
    """Return whether ``path`` is a test file.

    Test files are ``tests/**``, ``test_*.py``, ``*_test.py``, and ``conftest.py`` (data-model.md).
    """
    normalized = path.replace("\\", "/").lstrip("./")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in _TEST_FILE_PATTERNS)


def parse_patch(unified_diff: str, numstat: str, name_status: str) -> Patch:
    """Build a ``Patch`` from the output of the three git diff commands.

    Args:
        unified_diff: Output of ``git_diff_command``.
        numstat: Output of ``git_numstat_command``.
        name_status: Output of ``git_name_status_command``.

    Returns:
        The patch, with one ``FileChange`` per changed file. Binary files count 0 lines.
    """
    statuses: dict[str, FileStatus] = {}
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            code = parts[0][0]
            status = {"A": FileStatus.ADDED, "D": FileStatus.DELETED}.get(code, FileStatus.MODIFIED)
            statuses[parts[-1]] = status
    changes: list[FileChange] = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        changes.append(
            FileChange(
                path=path,
                status=statuses.get(path, FileStatus.MODIFIED),
                added=int(added) if added.isdigit() else 0,
                removed=int(removed) if removed.isdigit() else 0,
                is_test_file=is_test_path(path),
            )
        )
    return Patch(unified_diff=unified_diff, files=tuple(changes))


def git_patch_command() -> str:
    """Return one command printing the diff, numstat, and name-status sections.

    Each section starts with a marker on its own line. Diff body lines always start with a
    prefix (``+``, ``-``, a space, ``@@``, ``diff``...), so file content cannot forge a marker.
    """
    return (
        f"git add -A && echo '{PATCH_MARKERS[0]}' && "
        f"git diff --cached --no-color --no-ext-diff {BASELINE_TAG} && "
        f"echo '{PATCH_MARKERS[1]}' && git diff --cached --numstat {BASELINE_TAG} && "
        f"echo '{PATCH_MARKERS[2]}' && "
        f"git diff --cached --name-status --no-renames {BASELINE_TAG}"
    )


def parse_patch_output(stdout: str) -> Patch:
    """Parse the output of ``git_patch_command``.

    Raises:
        ValueError: If a section marker is missing.
    """
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in stdout.split("\n"):
        if line.rstrip("\r") in PATCH_MARKERS:
            current = sections.setdefault(line.rstrip("\r"), [])
        elif current is not None:
            current.append(line)
    if set(sections) != set(PATCH_MARKERS):
        raise ValueError("the patch output is missing a section")
    diff, numstat, name_status = ("\n".join(sections[m]).strip("\n") for m in PATCH_MARKERS)
    return parse_patch(diff + "\n" if diff else "", numstat, name_status)


async def compute_patch(executor: Executor, snapshot: Snapshot, *, timeout_s: int = 120) -> Patch:
    """Return the patch of ``snapshot`` against the baseline commit.

    One disposable command prints every git section, so the snapshot never changes and each
    patch costs a single sandbox operation.

    Args:
        executor: The isolated environment holding the snapshot.
        snapshot: The state to diff (it must descend from the baseline commit).
        timeout_s: Timeout of the git command.

    Returns:
        The patch, including new files.

    Raises:
        ExecutorError: If git fails.
    """
    result, _ = await executor.run(snapshot, git_patch_command(), timeout_s=timeout_s, mutate=False)
    if not result.ok:
        raise ExecutorError(
            f"git failed while computing the patch (exit {result.exit_code}): "
            f"{result.stderr[-500:]}"
        )
    try:
        return parse_patch_output(result.stdout)
    except ValueError as exc:
        raise ExecutorError(f"Unexpected git output while computing the patch: {exc}") from exc
