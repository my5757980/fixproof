"""``DockerExecutor``: a DEV ONLY executor on the local Docker daemon (research R5).

It lets the agent run on real repositories before Token Factory Sandboxes access exists. It is
never allowed for the public demo or the video (``sandbox.factory.assert_demo_safe``).

- A snapshot is a local Docker image; ``docker commit`` creates new ones.
- Every container runs with ``--network none``, except mutating runs (dependency install and the
  git baseline, which only the harness starts, never the model).
- Timeouts kill the container. No host directory is ever mounted.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import shlex
import sys
import tarfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, TextIO

from fixproof.events import EventType
from fixproof.models import Snapshot
from fixproof.sandbox.executor import REPO_ROOT, CommandResult, DirEntry, ExecutorError

BANNER = "DEV ONLY — not Token Factory Sandboxes"
OUTPUT_LIMIT = 65536
TIMEOUT_EXIT_CODE = 124
LIST_LIMIT = 1000

Runner = Callable[[Sequence[str], bytes | None, float | None], Awaitable[tuple[int, bytes, bytes]]]
EventCallback = Callable[[EventType, dict[str, Any]], None]


async def run_docker(
    args: Sequence[str], stdin: bytes | None = None, timeout: float | None = None
) -> tuple[int, bytes, bytes]:
    """Run one ``docker`` CLI command; raise ``TimeoutError`` (after killing it) on timeout."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        raise
    return process.returncode or 0, stdout, stderr


class DockerExecutor:
    """Executor on the local Docker daemon, for development only.

    Args:
        runner: Runs one docker command (injectable for tests).
        on_event: Receives one ``sandbox_op`` event per operation.
        banner_stream: Where the DEV ONLY banner is printed.
    """

    name = "docker"

    def __init__(
        self,
        *,
        runner: Runner = run_docker,
        on_event: EventCallback | None = None,
        banner_stream: TextIO | None = None,
    ) -> None:
        self._runner = runner
        self._on_event = on_event
        self._containers: set[str] = set()
        self._images: list[str] = []  # committed snapshots and tags, removed on close
        print(BANNER, file=banner_stream or sys.stderr)

    async def prepare_repo(self, tarball_path: Path, base_image: str) -> Snapshot:
        """Copy the tarball into a container of ``base_image``, extract it, and commit."""
        command = (
            f"mkdir -p {REPO_ROOT} && tar -xzf /tmp/repo.tgz -C {REPO_ROOT} "
            "--strip-components=1 && rm -f /tmp/repo.tgz"
        )
        started = time.monotonic()
        container = await self._create(base_image, command, network=False, workdir="/")
        try:
            await self._docker("cp", str(tarball_path), f"{container}:/tmp/repo.tgz")
            code, _, stderr = await self._runner(["docker", "start", "-a", container], None, 600)
            if code != 0:
                raise ExecutorError(
                    f"Could not extract the repository (exit {code}): {_text(stderr)[-500:]}"
                )
            image = await self._commit(container)
        finally:
            await self._remove(container)
        result = CommandResult(stdout="", elapsed_s=time.monotonic() - started)
        self._publish("upload", base_image, image, command, result, disposable=False)
        return Snapshot(image_id=image, label="source")

    async def run(
        self, snapshot: Snapshot, command: str, *, timeout_s: int, mutate: bool
    ) -> tuple[CommandResult, Snapshot]:
        """Run ``command`` in a new container; only mutating runs get network access."""
        started = time.monotonic()
        container = await self._create(snapshot.image_id, command, network=mutate)
        try:
            try:
                code, stdout, stderr = await self._runner(
                    ["docker", "start", "-a", container], None, timeout_s
                )
                result = CommandResult(
                    stdout=_text(stdout)[-OUTPUT_LIMIT:],
                    stderr=_text(stderr)[-OUTPUT_LIMIT:],
                    exit_code=code,
                    elapsed_s=time.monotonic() - started,
                )
            except TimeoutError:
                await self._runner(["docker", "kill", container], None, 30)
                result = CommandResult(
                    stdout="",
                    stderr=f"The command timed out after {timeout_s} s.",
                    exit_code=TIMEOUT_EXIT_CODE,
                    elapsed_s=time.monotonic() - started,
                    timed_out=True,
                )
            after = snapshot
            if mutate and not result.timed_out:
                image = await self._commit(container)
                after = Snapshot(image_id=image, parent_id=snapshot.image_id, label="run")
        finally:
            await self._remove(container)
        image_out = after.image_id if after is not snapshot else None
        self._publish("run", snapshot.image_id, image_out, command, result, disposable=not mutate)
        return result, after

    async def read_file(self, snapshot: Snapshot, path: str) -> bytes:
        """Read a file of ``REPO_ROOT`` from the image with ``docker cp`` (no command runs)."""
        container = await self._create(snapshot.image_id, "true", network=False)
        try:
            code, stdout, _ = await self._runner(
                ["docker", "cp", f"{container}:{REPO_ROOT}/{path.strip('/')}", "-"], None, 60
            )
        finally:
            await self._remove(container)
        if code != 0:
            raise FileNotFoundError(path)
        with tarfile.open(fileobj=io.BytesIO(stdout)) as archive:
            for member in archive.getmembers():
                if member.isdir():
                    raise IsADirectoryError(path)
                handle = archive.extractfile(member)
                if handle is not None:
                    return handle.read()
        raise FileNotFoundError(path)

    async def list_dir(self, snapshot: Snapshot, path: str = ".", depth: int = 2) -> list[DirEntry]:
        """List ``path`` up to ``depth`` levels with ``find`` in a disposable container."""
        target = path.strip("/") or "."
        command = (
            f"find {shlex.quote(target)} -mindepth 1 -maxdepth {depth} "
            "\\( -name .git -o -name __pycache__ \\) -prune -o -printf '%y\\t%s\\t%p\\n'"
        )
        result, _ = await self.run(snapshot, command, timeout_s=60, mutate=False)
        if result.exit_code != 0 and not result.stdout:
            raise FileNotFoundError(path)
        entries = []
        for line in result.stdout.splitlines():
            kind, _, rest = line.partition("\t")
            size, _, found = rest.partition("\t")
            relative = found.removeprefix("./")
            if not relative or kind not in ("f", "d"):
                continue
            entry_type: Literal["file", "dir"] = "dir" if kind == "d" else "file"
            entries.append(DirEntry(relative, entry_type, int(size) if kind == "f" else 0))
        return sorted(entries, key=lambda e: e.path)[:LIST_LIMIT]

    async def write_files(self, snapshot: Snapshot, files: Mapping[str, bytes]) -> Snapshot:
        """Copy files into ``REPO_ROOT`` (as one tar stream) and commit a new image."""
        started = time.monotonic()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            for path, content in files.items():
                info = tarfile.TarInfo(name=path.strip("/"))
                info.size = len(content)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(content))
        container = await self._create(snapshot.image_id, "true", network=False)
        try:
            code, _, stderr = await self._runner(
                ["docker", "cp", "-", f"{container}:{REPO_ROOT}"], archive.getvalue(), 120
            )
            if code != 0:
                raise ExecutorError(f"docker cp failed: {_text(stderr)[-500:]}")
            image = await self._commit(container)
        finally:
            await self._remove(container)
        result = CommandResult(stdout="", elapsed_s=time.monotonic() - started)
        command = "write " + ", ".join(sorted(files))
        self._publish("upload", snapshot.image_id, image, command, result, disposable=False)
        return Snapshot(image_id=image, parent_id=snapshot.image_id, label="write")

    async def tag(self, snapshot: Snapshot, label: str) -> Snapshot:
        """Tag the image as ``<label>:latest`` (Docker requires lowercase names)."""
        name = f"{label.lower()}:latest"
        await self._docker("tag", snapshot.image_id, name)
        self._images.append(name)
        return snapshot.model_copy(update={"tag": label, "label": label.rsplit("/", 1)[-1]})

    async def cancel_all(self) -> None:
        """Kill every container this executor still has running."""
        for container in list(self._containers):
            with contextlib.suppress(Exception):
                await self._runner(["docker", "kill", container], None, 30)

    async def close(self) -> None:
        """Remove every container, snapshot image, and tag this executor created.

        The run's report and patch are already on disk by then; without this cleanup every run
        would leave its installed environments behind as local images.
        """
        for container in list(self._containers):
            await self._remove(container)
        for image in reversed(self._images):
            with contextlib.suppress(Exception):
                await self._runner(["docker", "rmi", "-f", image], None, 120)
        self._images.clear()

    async def list_images(self, limit: int = 1) -> list[str]:
        """Return up to ``limit`` local image names (``doctor`` reachability check)."""
        stdout = await self._docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}")
        return stdout.split()[:limit]

    # -- helpers -----------------------------------------------------------------------------

    async def _create(
        self, image: str, command: str, *, network: bool, workdir: str = REPO_ROOT
    ) -> str:
        args = ["docker", "create", "--security-opt", "no-new-privileges", "-w", workdir]
        if not network:
            args += ["--network", "none"]
        args += [image, "sh", "-c", command]
        container = (await self._docker(*args[1:])).strip()
        self._containers.add(container)
        return container

    async def _commit(self, container: str) -> str:
        image = (await self._docker("commit", container)).strip()
        self._images.append(image)
        return image

    async def _remove(self, container: str) -> None:
        self._containers.discard(container)
        with contextlib.suppress(Exception):
            await self._runner(["docker", "rm", "-f", container], None, 60)

    async def _docker(self, *args: str) -> str:
        code, stdout, stderr = await self._runner(["docker", *args], None, 600)
        if code != 0:
            raise ExecutorError(f"docker {args[0]} failed (exit {code}): {_text(stderr)[-500:]}")
        return _text(stdout)

    def _publish(
        self,
        op: str,
        image_in: str | None,
        image_out: str | None,
        command: str,
        result: CommandResult,
        *,
        disposable: bool,
    ) -> None:
        if self._on_event is not None:
            self._on_event(
                EventType.SANDBOX_OP,
                {
                    "op": op,
                    "image_in": image_in,
                    "image_out": image_out,
                    "command": command,
                    "exit_code": result.exit_code,
                    "elapsed_s": round(result.elapsed_s, 3),
                    "disposable": disposable,
                },
            )


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")
