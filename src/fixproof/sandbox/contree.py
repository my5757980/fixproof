"""``ContreeExecutor``: Nebius Token Factory Sandboxes through contree-sdk (research R4).

This is the default executor, and the only one allowed for the public demo and the video.

- A snapshot is a sandbox image version. Read-only work runs with ``disposable=True``; mutations
  (dependency install, the git baseline) run with ``disposable=False`` and yield a new image.
- The repository arrives as a tarball uploaded together with its extraction command, so the
  sandbox needs no network access to GitHub.
- Transient API errors (timeouts, 429, 5xx, connection errors) are retried 3 times with
  exponential backoff (1 s, 2 s, 4 s); anything else fails with a clear ``ExecutorError``
  (Constitution III).
- No credential is ever sent as an environment variable, a file, or inside a command (FR-020).

Verified against contree-sdk 0.3.6. The open questions in research.md R4 (egress to PyPI,
limits, tag syntax) are checked by the live smoke tests.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from contree_sdk import Contree
from contree_sdk.auth import IAMAuth
from contree_sdk.config import ContreeConfig
from contree_sdk.sdk.exceptions import (
    ApiStatusCodeError,
    ApiTimeoutError,
    ContreeError,
    ContreeTransportError,
    FailedOperationError,
    NotFoundError,
    OperationTimedOutError,
)
from contree_sdk.sdk.exceptions.api import TooManyRequestsError

from fixproof.config import Settings
from fixproof.events import EventType
from fixproof.models import Snapshot
from fixproof.sandbox.executor import REPO_ROOT, CommandResult, DirEntry, ExecutorError

TARBALL_PATH = "/tmp/repo.tgz"
OUTPUT_LIMIT = 65536
TIMEOUT_EXIT_CODE = 124
EXTRACT_TIMEOUT_S = 600
LIST_LIMIT = 1000
_SKIPPED_DIRS = frozenset({".", "..", ".git", "__pycache__"})

EventCallback = Callable[[EventType, dict[str, Any]], None]
_T = TypeVar("_T")


def is_transient(error: BaseException) -> bool:
    """Return whether a contree-sdk error is worth retrying (timeouts, 429, 5xx, transport)."""
    if isinstance(error, TooManyRequestsError | ApiTimeoutError | ContreeTransportError):
        return True
    if isinstance(error, ApiStatusCodeError):
        return error.status is not None and error.status >= 500
    return False


def _describe(error: ContreeError) -> str:
    status = getattr(error, "status", None)
    detail = getattr(error, "error", None)
    text = type(error).__name__ + (f" (HTTP {status})" if status else "")
    return text + (f": {detail}" if detail else "")


class ContreeExecutor:
    """Executor backed by Token Factory Sandboxes.

    Args:
        client: A contree-sdk ``Contree`` client (a stub in unit tests).
        secrets: Credential values that must never reach the sandbox.
        on_event: Receives one ``sandbox_op`` event per sandbox operation.
        retry_delays: Backoff before each retry of a transient error.
        sleep: Awaitable sleep, injectable for tests.
        output_limit: Bytes of stdout and stderr kept per command.
    """

    name = "contree"
    DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)

    def __init__(
        self,
        client: Any,
        *,
        secrets: Sequence[str] = (),
        on_event: EventCallback | None = None,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        output_limit: int = OUTPUT_LIMIT,
    ) -> None:
        self._client = client
        self._secrets = [s for s in secrets if len(s) >= 4]
        self._on_event = on_event
        self._retry_delays = tuple(retry_delays)
        self._sleep = sleep
        self._output_limit = output_limit
        self._inflight: set[asyncio.Future[Any]] = set()

    @classmethod
    def from_settings(
        cls, settings: Settings, *, on_event: EventCallback | None = None
    ) -> ContreeExecutor:
        """Create an executor for the configured Sandboxes endpoint and project.

        Raises:
            ConfigError: If the sandbox token or project is missing.
        """
        auth = IAMAuth(
            token=settings.sandbox_token(),
            project_id=settings.require_sandbox_project(),
            base_url=settings.contree_url,
        )
        client = Contree(config=ContreeConfig(auth=auth))
        return cls(client, secrets=settings.secret_values(), on_event=on_event)

    # -- Executor protocol -----------------------------------------------------------------

    async def prepare_repo(self, tarball_path: Path, base_image: str) -> Snapshot:
        """Upload the tarball into ``base_image``, extract it into ``REPO_ROOT``, and persist it."""
        base = await self._call("image", lambda: self._client.images.oci(base_image))
        command = (
            f"mkdir -p {REPO_ROOT} && tar -xzf {TARBALL_PATH} -C {REPO_ROOT} "
            f"--strip-components=1 && rm -f {TARBALL_PATH}"
        )
        started = time.monotonic()
        image = await self._call(
            "upload",
            lambda: base.run(
                shell=command,
                files={TARBALL_PATH: tarball_path},
                cwd="/",
                timeout=EXTRACT_TIMEOUT_S,
                disposable=False,
                truncate_output_at=self._output_limit,
            ),
        )
        result = _result(image, time.monotonic() - started)
        self._publish("upload", str(base.uuid), str(image.uuid), command, result, disposable=False)
        if not result.ok or image.uuid is None:
            raise ExecutorError(
                f"Could not extract the repository in the sandbox (exit {result.exit_code}): "
                f"{result.stderr[-500:]}"
            )
        return Snapshot(image_id=str(image.uuid), label="source")

    async def run(
        self, snapshot: Snapshot, command: str, *, timeout_s: int, mutate: bool
    ) -> tuple[CommandResult, Snapshot]:
        """Run ``command`` in ``REPO_ROOT``; a timeout is a result, not an error."""
        self._guard(command)
        image = await self._image(snapshot)
        started = time.monotonic()
        try:
            done = await self._call(
                "run",
                lambda: image.run(
                    shell=command,
                    cwd=REPO_ROOT,
                    timeout=timeout_s,
                    disposable=not mutate,
                    truncate_output_at=self._output_limit,
                ),
                passthrough=(OperationTimedOutError, FailedOperationError),
            )
        except (OperationTimedOutError, FailedOperationError) as exc:
            if isinstance(exc, FailedOperationError) and "time" not in exc.error.lower():
                raise ExecutorError(f"Token Factory Sandboxes run failed: {exc.error}") from exc
            result = CommandResult(
                stdout="",
                stderr=f"The command timed out after {timeout_s} s.",
                exit_code=TIMEOUT_EXIT_CODE,
                elapsed_s=time.monotonic() - started,
                timed_out=True,
            )
            self._publish("run", snapshot.image_id, None, command, result, disposable=not mutate)
            return result, snapshot
        result = _result(done, time.monotonic() - started)
        after = snapshot
        if mutate:
            if done.uuid is None:
                raise ExecutorError("The sandbox returned no image for a persistent run.")
            after = Snapshot(image_id=str(done.uuid), parent_id=snapshot.image_id, label="run")
        image_out = after.image_id if mutate else None
        self._publish("run", snapshot.image_id, image_out, command, result, disposable=not mutate)
        return result, after

    async def read_file(self, snapshot: Snapshot, path: str) -> bytes:
        """Read a file of ``REPO_ROOT`` from a snapshot without starting a sandbox."""
        image = await self._image(snapshot)
        started = time.monotonic()
        try:
            data: bytes = await self._call(
                "read",
                lambda: image.read(f"{REPO_ROOT}/{path.strip('/')}"),
                passthrough=(ApiStatusCodeError,),
            )
        except ApiStatusCodeError as exc:
            if exc.status in (401, 403):
                raise ExecutorError(
                    f"Token Factory Sandboxes read failed: {_describe(exc)}"
                ) from exc
            raise FileNotFoundError(path) from exc
        self._publish(
            "read",
            snapshot.image_id,
            None,
            f"read {path}",
            CommandResult(stdout="", elapsed_s=time.monotonic() - started),
            disposable=True,
        )
        return data

    async def list_dir(self, snapshot: Snapshot, path: str = ".", depth: int = 2) -> list[DirEntry]:
        """List ``path`` up to ``depth`` levels with the inspect API (``.git`` is skipped)."""
        image = await self._image(snapshot)
        relative = "" if path.strip("/") in ("", ".") else path.strip("/")
        started = time.monotonic()
        entries: list[DirEntry] = []
        level = [(f"{REPO_ROOT}/{relative}".rstrip("/"), f"{relative}/" if relative else "")]
        for current in range(depth):
            listings = await asyncio.gather(
                *(self._ls(image, absolute, required=current == 0) for absolute, _ in level)
            )
            next_level: list[tuple[str, str]] = []
            for (absolute, prefix), items in zip(level, listings, strict=True):
                for item in items:
                    name = PurePosixPath(str(item.path)).name
                    if name in _SKIPPED_DIRS:
                        continue
                    if item.is_dir:
                        entries.append(DirEntry(f"{prefix}{name}", "dir", 0))
                        next_level.append((f"{absolute}/{name}", f"{prefix}{name}/"))
                    else:
                        entries.append(DirEntry(f"{prefix}{name}", "file", int(item.size or 0)))
            level = next_level
            if not level or len(entries) >= LIST_LIMIT:
                break
        self._publish(
            "ls",
            snapshot.image_id,
            None,
            f"ls {path} (depth {depth})",
            CommandResult(stdout="", elapsed_s=time.monotonic() - started),
            disposable=True,
        )
        return sorted(entries, key=lambda e: e.path)[:LIST_LIMIT]

    async def write_files(self, snapshot: Snapshot, files: Mapping[str, bytes]) -> Snapshot:
        """Write files into ``REPO_ROOT`` as a new image version."""
        for content in files.values():
            self._guard_bytes(content)
        image = await self._image(snapshot)
        payload = {f"{REPO_ROOT}/{path.strip('/')}": content for path, content in files.items()}
        started = time.monotonic()
        new_image = await self._call("upload", lambda: image.apply_files(payload))
        after = Snapshot(image_id=str(new_image.uuid), parent_id=snapshot.image_id, label="write")
        self._publish(
            "upload",
            snapshot.image_id,
            after.image_id,
            "write " + ", ".join(sorted(files)),
            CommandResult(stdout="", elapsed_s=time.monotonic() - started),
            disposable=False,
        )
        return after

    async def tag(self, snapshot: Snapshot, label: str) -> Snapshot:
        """Tag the image so it can be found and branched from later."""
        image = await self._image(snapshot)
        await self._call("tag", lambda: image.tag_as(label))
        return snapshot.model_copy(update={"tag": label, "label": label.rsplit("/", 1)[-1]})

    async def cancel_all(self) -> None:
        """Cancel every in-flight operation (contree-sdk then cancels it on the server)."""
        pending = [task for task in self._inflight if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5)

    async def close(self) -> None:
        """Cancel in-flight work; the SDK's HTTP clients are released with the client."""
        await self.cancel_all()

    async def list_images(self, limit: int = 1) -> list[str]:
        """Return up to ``limit`` image names (``doctor`` uses this as a reachability check)."""
        images = await self._call("list", lambda: self._client.images(number=limit))
        return [str(image.tag or image.uuid) for image in images]

    # -- helpers -----------------------------------------------------------------------------

    async def _image(self, snapshot: Snapshot) -> Any:
        return await self._call("image", lambda: self._client.images.use(snapshot.image_id))

    async def _ls(self, image: Any, absolute: str, *, required: bool) -> list[Any]:
        try:
            items: list[Any] = await self._call(
                "ls", lambda: image.ls(absolute), passthrough=(NotFoundError,)
            )
        except NotFoundError as exc:
            if required:
                raise FileNotFoundError(absolute.removeprefix(f"{REPO_ROOT}/")) from exc
            return []
        return items

    async def _call(
        self,
        op: str,
        factory: Callable[[], Awaitable[_T]],
        *,
        passthrough: tuple[type[BaseException], ...] = (),
    ) -> _T:
        """Run one SDK operation, retrying transient errors with exponential backoff."""
        attempts = len(self._retry_delays) + 1
        for attempt in range(attempts):
            task: asyncio.Future[_T] = asyncio.ensure_future(factory())
            self._inflight.add(task)
            try:
                return await task
            except ContreeError as exc:
                if not is_transient(exc):
                    if isinstance(exc, passthrough):
                        raise
                    raise ExecutorError(
                        f"Token Factory Sandboxes {op} failed: {_describe(exc)}"
                    ) from exc
                if attempt == attempts - 1:
                    raise ExecutorError(
                        f"Token Factory Sandboxes {op} failed after {attempts} attempts: "
                        f"{_describe(exc)}"
                    ) from exc
                await self._sleep(self._retry_delays[attempt])
            finally:
                self._inflight.discard(task)
        raise AssertionError("unreachable")  # pragma: no cover

    def _guard(self, text: str) -> None:
        if any(secret in text for secret in self._secrets):
            raise ExecutorError("Refusing to send a credential into the sandbox (FR-020).")

    def _guard_bytes(self, content: bytes) -> None:
        if any(secret.encode() in content for secret in self._secrets):
            raise ExecutorError("Refusing to send a credential into the sandbox (FR-020).")

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


def _result(image: Any, wall_s: float) -> CommandResult:
    """Convert a finished SDK image into a ``CommandResult``."""
    elapsed = getattr(image, "elapsed", None)
    seconds = elapsed.total_seconds() if isinstance(elapsed, timedelta) else wall_s
    return CommandResult(
        stdout=_text(image.stdout),
        stderr=_text(image.stderr),
        exit_code=int(image.exit_code),
        elapsed_s=seconds,
        timed_out=_timed_out(image),
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _timed_out(image: Any) -> bool:
    """Read the process ``timed_out`` flag from the SDK's raw result, when present."""
    raw = getattr(getattr(image, "result", None), "_raw", None)
    state = getattr(getattr(raw, "result", None), "state", None)
    return bool(getattr(state, "timed_out", False))
