"""``git apply`` for the ``FakeExecutor``, done by real git on a temporary copy of a snapshot."""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from pathlib import Path

from fixproof.sandbox.executor import CommandResult
from tests.fakes.fake_executor import Files


def git_apply(command: str, fs: Files) -> tuple[CommandResult, Files]:
    """Simulate ``git apply [options] FILE && rm -f FILE`` on the files of a snapshot."""
    patch_name = shlex.split(command.split("&&", 1)[0])[-1]
    with tempfile.TemporaryDirectory(prefix="fake-git-apply-") as tmp:
        root = Path(tmp)
        for path, content in fs.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", patch_name],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return CommandResult(stdout="", stderr=result.stderr, exit_code=result.returncode), fs
        updated = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
    updated.pop(patch_name, None)
    return CommandResult(stdout=""), updated
