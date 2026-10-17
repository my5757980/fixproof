"""``DockerExecutor``: a DEV ONLY executor on the local Docker daemon (research R5).

It lets the agent run on real repositories before Token Factory Sandboxes access exists. It is
never allowed for the public demo or the video (``sandbox.factory.assert_demo_safe``).

A ``docker commit`` can take minutes on a slow machine whatever the size of the change (measured
on Docker Desktop with the containerd image store: 51 to 374 s per commit, research R5), so the
executor commits only when it has to:

- The repository tarball stays on the host until the first container extracts it.
- Written files stay in memory and are copied into every container started from the snapshot.
- Mutating runs (dependency install, the git baseline, ``git apply``) continue one after another
  in the same stopped container (a chain); it is committed once, when something else needs its
  newest state. An older state of a chain is rebuilt by running its commands again in a new
  container, so a snapshot never changes under its caller.
- Every container runs with ``--network none``, except chains, which only the harness starts,
  never the model.
- Timeouts kill the container. No host directory is ever mounted.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import itertools
import shlex
import shutil
import sys
import tarfile
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TextIO

from fixproof.events import EventType
from fixproof.models import Snapshot
from fixproof.sandbox.executor import REPO_ROOT, CommandResult, DirEntry, ExecutorError

BANNER = "DEV ONLY — not Token Factory Sandboxes"
OUTPUT_LIMIT = 65536
TIMEOUT_EXIT_CODE = 124
LIST_LIMIT = 1000
TARBALL_PATH = "/tmp/repo.tgz"
EXTRACT_COMMAND = (
    f"mkdir -p {REPO_ROOT} && tar -xzf {TARBALL_PATH} -C {REPO_ROOT} --strip-components=1 "
    f"&& rm -f {TARBALL_PATH}"
)
STEP_SCRIPT = "/tmp/fixproof-step.sh"  # a chain container runs this script on every start
DOCKER_TIMEOUT_S = 600
# A commit took up to 600 s and more under memory pressure (2026-10-17), and a killed commit
# loses the whole setup, so it gets much longer than other docker commands.
COMMIT_TIMEOUT_S = 1800

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


@dataclass(frozen=True)
class _Pending:
    """What a snapshot adds to a committed image without a commit.

    Attributes:
        image: The committed image.
        files: Written files, relative to ``REPO_ROOT`` (the latest write wins).
        tarball: The repository tarball, extracted into ``REPO_ROOT`` by the first container.
    """

    image: str
    files: Mapping[str, bytes]
    tarball: Path | None = None


@dataclass
class _Chain:
    """A stopped container holding mutating runs that are not committed yet.

    Attributes:
        container: The container. Each run copies its script in as ``STEP_SCRIPT`` and starts
            the container again, so the filesystem carries over from one run to the next.
        base: What the container was created from.
        steps: Every script started in it so far, with its timeout, in order (also the ones
            that failed or timed out, because they changed the filesystem too).
    """

    container: str
    base: _Pending
    steps: list[tuple[str, int]] = field(default_factory=list)


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
        self._pending: dict[str, _Pending] = {}  # snapshot ID -> what is not committed yet
        self._chains: dict[str, tuple[_Chain, int]] = {}  # snapshot ID -> (chain, its steps)
        self._chain_lock = asyncio.Lock()  # one chain change or commit at a time
        self._ids = itertools.count(1)
        self._workdir: Path | None = None  # copies of repository tarballs, removed on close
        print(BANNER, file=banner_stream or sys.stderr)

    async def prepare_repo(self, tarball_path: Path, base_image: str) -> Snapshot:
        """Keep a copy of the tarball as the source snapshot, without a container or commit.

        The first container started from the snapshot extracts it before its command runs.
        """
        if self._workdir is None:
            self._workdir = Path(tempfile.mkdtemp(prefix="fixproof-docker-"))
        number = next(self._ids)
        tarball = self._workdir / f"repo-{number}.tgz"
        shutil.copyfile(tarball_path, tarball)
        snapshot_id = f"{base_image}+repo{number}"
        self._pending[snapshot_id] = _Pending(base_image, {}, tarball)
        result = CommandResult(stdout="")
        self._publish("upload", base_image, snapshot_id, EXTRACT_COMMAND, result, disposable=False)
        return Snapshot(image_id=snapshot_id, label="source")

    async def run(
        self, snapshot: Snapshot, command: str, *, timeout_s: int, mutate: bool
    ) -> tuple[CommandResult, Snapshot]:
        """Run ``command`` in a container; only mutating runs get network access.

        A mutating run continues the snapshot's chain container when the snapshot is the
        chain's newest state, and starts a new chain otherwise; nothing is committed here.
        """
        if mutate:
            return await self._run_in_chain(snapshot, command, timeout_s)
        await self._settle(snapshot)
        started = time.monotonic()
        container = await self._container(snapshot, command)
        try:
            result = await self._start(container, timeout_s, started)
        finally:
            await self._remove(container)
        self._publish("run", snapshot.image_id, None, command, result, disposable=True)
        return result, snapshot

    async def read_file(self, snapshot: Snapshot, path: str) -> bytes:
        """Read a file of ``REPO_ROOT``; no command runs.

        A file written but not committed yet comes from memory, a file of a repository not
        extracted yet from its tarball, and any other file from the image with ``docker cp``.
        """
        await self._settle(snapshot)
        layers = self._layers(snapshot)
        relative = path.strip("/")
        if relative in layers.files:
            return layers.files[relative]
        if any(name.startswith(f"{relative}/") for name in layers.files):
            raise IsADirectoryError(path)
        if layers.tarball is not None:
            return _read_tarball(layers.tarball, relative)
        container = await self._create(layers.image, "true", network=False)
        try:
            code, stdout, _ = await self._call(
                ["docker", "cp", f"{container}:{REPO_ROOT}/{relative}", "-"], None, 60
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
        """Write files into ``REPO_ROOT`` as a new snapshot, without a Docker commit.

        The files stay in memory: every container started from the new snapshot gets them (as
        one tar stream) before its command runs, and a mutating run commits them with the rest.
        A repository that is still a tarball is extracted and committed first.
        """
        await self._settle(snapshot)
        if self._layers(snapshot).tarball is not None:
            result, extracted = await self._run_in_chain(snapshot, "true", 600)
            if not result.ok:
                raise ExecutorError(
                    f"Could not extract the repository (exit {result.exit_code}): "
                    f"{result.stderr[-500:]}"
                )
            await self._settle(extracted)
            self._pending[snapshot.image_id] = self._layers(extracted)
        layers = self._layers(snapshot)
        written = {path.strip("/"): content for path, content in files.items()}
        snapshot_id = f"{layers.image}+files{next(self._ids)}"
        self._pending[snapshot_id] = _Pending(layers.image, {**layers.files, **written})
        command = "write " + ", ".join(sorted(written))
        result = CommandResult(stdout="")
        self._publish("upload", snapshot.image_id, snapshot_id, command, result, disposable=False)
        return Snapshot(image_id=snapshot_id, parent_id=snapshot.image_id, label="write")

    async def tag(self, snapshot: Snapshot, label: str) -> Snapshot:
        """Tag the image as ``<label>:latest`` (Docker requires lowercase names).

        A snapshot with changes not committed yet has no image of its own: it only gets the
        label and stays usable through its ``image_id`` until the executor is closed.
        """
        layers = self._layers(snapshot)
        uncommitted = snapshot.image_id in self._chains or layers.files or layers.tarball
        if uncommitted:
            return snapshot.model_copy(update={"label": label.rsplit("/", 1)[-1]})
        name = f"{label.lower()}:latest"
        await self._docker("tag", layers.image, name)
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
        self._pending.clear()
        self._chains.clear()
        if self._workdir is not None:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None

    async def list_images(self, limit: int = 1) -> list[str]:
        """Return up to ``limit`` local image names (``doctor`` reachability check)."""
        stdout = await self._docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}")
        return stdout.split()[:limit]

    # -- chains of mutating runs -------------------------------------------------------------

    async def _run_in_chain(
        self, snapshot: Snapshot, command: str, timeout_s: int
    ) -> tuple[CommandResult, Snapshot]:
        started = time.monotonic()
        async with self._chain_lock:
            chain = await self._chain_for(snapshot)
            script = command
            if not chain.steps and chain.base.tarball is not None:
                script = f"{EXTRACT_COMMAND} && sh -c {shlex.quote(command)}"
            result = await self._step(chain, script, timeout_s, started)
            after = snapshot
            if not result.timed_out:
                after_id = f"{chain.container[:12]}+step{len(chain.steps)}"
                self._chains[after_id] = (chain, len(chain.steps))
                after = Snapshot(image_id=after_id, parent_id=snapshot.image_id, label="run")
        image_out = after.image_id if after is not snapshot else None
        self._publish("run", snapshot.image_id, image_out, command, result, disposable=False)
        return result, after

    async def _chain_for(self, snapshot: Snapshot) -> _Chain:
        """Return the chain to continue for ``snapshot``, rebuilding an older state."""
        entry = self._chains.get(snapshot.image_id)
        if entry is None:
            return await self._new_chain(self._layers(snapshot))
        chain, steps = entry
        if steps == len(chain.steps):
            return chain
        return await self._rebuild(snapshot.image_id, chain, steps)

    async def _new_chain(self, base: _Pending) -> _Chain:
        container = await self._create(base.image, f"sh {STEP_SCRIPT}", network=True)
        try:
            if base.tarball is not None:
                await self._docker("cp", str(base.tarball), f"{container}:{TARBALL_PATH}")
            if base.files:
                await self._copy_in(container, REPO_ROOT, base.files)
        except BaseException:
            await self._remove(container)
            raise
        return _Chain(container, base)

    async def _step(
        self, chain: _Chain, script: str, timeout_s: int, started: float
    ) -> CommandResult:
        name = PurePosixPath(STEP_SCRIPT)
        await self._copy_in(chain.container, str(name.parent), {name.name: script.encode()})
        chain.steps.append((script, timeout_s))
        return await self._start(chain.container, timeout_s, started)

    async def _rebuild(self, snapshot_id: str, chain: _Chain, steps: int) -> _Chain:
        """Rebuild an older state of ``chain`` by running its first ``steps`` scripts again."""
        fresh = await self._new_chain(chain.base)
        try:
            for script, timeout_s in chain.steps[:steps]:
                result = await self._step(fresh, script, timeout_s, time.monotonic())
                self._publish(
                    "run", snapshot_id, None, f"rebuild: {script}", result, disposable=False
                )
                if not result.ok:
                    raise ExecutorError(
                        f"Could not rebuild an earlier snapshot: a command that worked before "
                        f"failed (exit {result.exit_code}): {result.stderr[-300:]}"
                    )
        except BaseException:
            await self._remove(fresh.container)
            raise
        self._chains[snapshot_id] = (fresh, steps)
        return fresh

    async def _settle(self, snapshot: Snapshot) -> None:
        """Commit ``snapshot`` if it is a chain state, so other containers can start from it."""
        if snapshot.image_id not in self._chains:
            return
        async with self._chain_lock:
            entry = self._chains.get(snapshot.image_id)
            if entry is None:  # settled by a concurrent call while this one waited
                return
            chain, steps = entry
            if steps != len(chain.steps):
                chain = await self._rebuild(snapshot.image_id, chain, steps)
            image = await self._commit(chain.container)
            await self._remove(chain.container)
            del self._chains[snapshot.image_id]
            self._pending[snapshot.image_id] = _Pending(image, {})

    # -- helpers -----------------------------------------------------------------------------

    def _layers(self, snapshot: Snapshot) -> _Pending:
        """Return the committed image of ``snapshot`` and what is not committed on top of it."""
        return self._pending.get(snapshot.image_id) or _Pending(snapshot.image_id, {})

    async def _container(self, snapshot: Snapshot, command: str) -> str:
        """Create a disposable container (no network) of a snapshot that is not a chain state.

        A repository tarball is copied in and extracted by the container itself before
        ``command`` runs; written files are streamed into ``REPO_ROOT`` before it starts.
        """
        layers = self._layers(snapshot)
        if layers.tarball is not None:
            command = f"{EXTRACT_COMMAND} && sh -c {shlex.quote(command)}"
        container = await self._create(layers.image, command, network=False)
        try:
            if layers.tarball is not None:
                await self._docker("cp", str(layers.tarball), f"{container}:{TARBALL_PATH}")
            if layers.files:
                await self._copy_in(container, REPO_ROOT, layers.files)
        except BaseException:
            await self._remove(container)
            raise
        return container

    async def _copy_in(self, container: str, directory: str, files: Mapping[str, bytes]) -> None:
        """Stream ``files`` (paths relative to ``directory``) into a container as one tar."""
        code, _, stderr = await self._call(
            ["docker", "cp", "-", f"{container}:{directory}"], _tar(files), 120
        )
        if code != 0:
            raise ExecutorError(f"docker cp failed: {_text(stderr)[-500:]}")

    async def _start(self, container: str, timeout_s: int, started: float) -> CommandResult:
        """Start a created or stopped container and wait; a timeout kills it."""
        try:
            code, stdout, stderr = await self._runner(
                ["docker", "start", "-a", container], None, timeout_s
            )
        except TimeoutError:
            with contextlib.suppress(Exception):  # close() removes the container in any case
                await self._runner(["docker", "kill", container], None, 30)
            return CommandResult(
                stdout="",
                stderr=f"The command timed out after {timeout_s} s.",
                exit_code=TIMEOUT_EXIT_CODE,
                elapsed_s=time.monotonic() - started,
                timed_out=True,
            )
        return CommandResult(
            stdout=_text(stdout)[-OUTPUT_LIMIT:],
            stderr=_text(stderr)[-OUTPUT_LIMIT:],
            exit_code=code,
            elapsed_s=time.monotonic() - started,
        )

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
        image = (await self._docker("commit", container, timeout_s=COMMIT_TIMEOUT_S)).strip()
        self._images.append(image)
        return image

    async def _remove(self, container: str) -> None:
        self._containers.discard(container)
        with contextlib.suppress(Exception):
            await self._runner(["docker", "rm", "-f", container], None, 60)

    async def _docker(self, *args: str, timeout_s: int = DOCKER_TIMEOUT_S) -> str:
        code, stdout, stderr = await self._call(["docker", *args], None, timeout_s)
        if code != 0:
            raise ExecutorError(f"docker {args[0]} failed (exit {code}): {_text(stderr)[-500:]}")
        return _text(stdout)

    async def _call(
        self, args: Sequence[str], stdin: bytes | None, timeout_s: float
    ) -> tuple[int, bytes, bytes]:
        """Run one docker command; a timeout is an ``ExecutorError`` that names the command."""
        try:
            return await self._runner(args, stdin, timeout_s)
        except TimeoutError as exc:
            raise ExecutorError(
                f"docker {args[1]} did not finish within {timeout_s:.0f} s; Docker may be short "
                "of memory (close other programs or give Docker Desktop more memory)"
            ) from exc

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


def _tar(files: Mapping[str, bytes]) -> bytes:
    """Pack ``files`` (paths relative to the target folder) into one uncompressed tar archive."""
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for path, content in files.items():
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(content))
    return archive.getvalue()


def _read_tarball(tarball: Path, path: str) -> bytes:
    """Read ``path`` (relative to the repository root) from a GitHub tarball.

    The tarball has one top-level folder, which is stripped like ``--strip-components=1``.
    """
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive:
            name = member.name.split("/", 1)[1] if "/" in member.name else ""
            if name.rstrip("/") == path:
                if member.isdir():
                    raise IsADirectoryError(path)
                handle = archive.extractfile(member)
                if handle is None:
                    raise FileNotFoundError(path)
                return handle.read()
            if name.startswith(f"{path}/"):
                raise IsADirectoryError(path)
    raise FileNotFoundError(path)


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")
