"""ContreeExecutor against a stub of the contree-sdk client (no network, no credentials)."""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from contree_sdk.sdk.exceptions import (
    ApiStatusCodeError,
    ApiTimeoutError,
    ContreeTransportError,
    ForbiddenError,
    NotFoundError,
    OperationTimedOutError,
    UnprocessableEntityError,
)
from contree_sdk.sdk.exceptions.api import TooManyRequestsError

from fixproof.events import EventType
from fixproof.models import Snapshot
from fixproof.sandbox.contree import ContreeExecutor
from fixproof.sandbox.executor import REPO_ROOT, ExecutorError

SECRET = "nk-SECRET-VALUE-0042"
HANG = "hang"


class StubEntry:
    def __init__(self, parent: str, name: str, size: int, is_dir: bool) -> None:
        self.path = name
        self.size = size
        self.is_dir = is_dir
        self.full_path = PurePosixPath(parent) / name


class StubImage:
    def __init__(
        self, client: StubClient, uuid: Any, tag: str | None = None, **result: Any
    ) -> None:
        self.client, self.uuid, self.tag = client, uuid, tag
        self.stdout = result.get("stdout", "")
        self.stderr = result.get("stderr", "")
        self.exit_code = result.get("exit_code", 0)
        self.elapsed = timedelta(seconds=0.25)
        state = SimpleNamespace(timed_out=result.get("timed_out", False))
        self.result = SimpleNamespace(_raw=SimpleNamespace(result=SimpleNamespace(state=state)))

    def run(self, command: str | None = None, **kwargs: Any) -> StubPending:
        return StubPending(self, {"command": command, **kwargs})

    async def read(self, path: str) -> bytes:
        try:
            return self.client.files[str(path)]
        except KeyError:
            raise NotFoundError() from None

    async def ls(self, path: str) -> list[StubEntry]:
        prefix = str(path).rstrip("/") + "/"
        names: dict[str, StubEntry] = {}
        for full, data in self.client.files.items():
            if full.startswith(prefix):
                head, _, rest = full[len(prefix) :].partition("/")
                names[head] = StubEntry(str(path), head, 0 if rest else len(data), bool(rest))
        if not names:
            raise NotFoundError()
        return list(names.values())

    async def apply_files(self, files: dict[str, bytes]) -> StubImage:
        self.client.applied.append(dict(files))
        return StubImage(self.client, uuid4())

    async def tag_as(self, tag: str) -> StubImage:
        self.client.tags.append((str(self.uuid), tag))
        return StubImage(self.client, self.uuid, tag)


class StubPending:
    def __init__(self, image: StubImage, kwargs: dict[str, Any]) -> None:
        self.image, self.kwargs = image, kwargs

    def __await__(self) -> Generator[Any, None, StubImage]:
        return self._execute().__await__()

    async def _execute(self) -> StubImage:
        client = self.image.client
        client.runs.append({"image": str(self.image.uuid), **self.kwargs})
        item = client.outcomes.popleft() if client.outcomes else {}
        if isinstance(item, Exception):
            raise item
        if item == HANG:
            client.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                client.cancelled += 1
                raise
        result = dict(item) if isinstance(item, dict) else {}
        uuid = None if self.kwargs.get("disposable", True) else uuid4()
        return StubImage(client, uuid, **result)


class StubImages:
    def __init__(self, client: StubClient) -> None:
        self.client = client

    async def use(self, ref: Any, strict: bool = False) -> StubImage:
        self.client.used.append(str(ref))
        return StubImage(self.client, ref)

    async def oci(self, ref: str, **kwargs: Any) -> StubImage:
        self.client.used.append(f"oci:{ref}")
        return StubImage(self.client, uuid4(), tag=ref)

    async def __call__(self, number: int = 100, **kwargs: Any) -> list[StubImage]:
        return [StubImage(self.client, uuid4(), tag="python:3.12")][:number]


class StubClient:
    def __init__(self, *outcomes: Any) -> None:
        self.images = StubImages(self)
        self.outcomes: deque[Any] = deque(outcomes)
        self.runs: list[dict[str, Any]] = []
        self.applied: list[dict[str, bytes]] = []
        self.tags: list[tuple[str, str]] = []
        self.used: list[str] = []
        self.files: dict[str, bytes] = {}
        self.started = asyncio.Event()
        self.cancelled = 0


class Recorder:
    def __init__(self) -> None:
        self.sleeps: list[float] = []
        self.events: list[tuple[EventType, dict[str, Any]]] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def on_event(self, event_type: EventType, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def make(*outcomes: Any) -> tuple[ContreeExecutor, StubClient, Recorder]:
    client = StubClient(*outcomes)
    recorder = Recorder()
    executor = ContreeExecutor(
        client, secrets=[SECRET], on_event=recorder.on_event, sleep=recorder.sleep
    )
    return executor, client, recorder


SNAPSHOT = Snapshot(image_id=str(uuid4()), label="installed")


async def test_transient_errors_are_retried_with_exponential_backoff() -> None:
    executor, client, rec = make(
        TooManyRequestsError(), ApiStatusCodeError(status=503), ApiTimeoutError(), {"stdout": "hi"}
    )
    result, _ = await executor.run(SNAPSHOT, "echo hi", timeout_s=30, mutate=False)
    assert result.ok and result.stdout == "hi"
    assert len(client.runs) == 4
    assert rec.sleeps == [1.0, 2.0, 4.0]


async def test_retries_are_bounded_then_a_clear_error_is_raised() -> None:
    executor, client, rec = make(*(ContreeTransportError(error="reset") for _ in range(4)))
    with pytest.raises(ExecutorError, match="after 4 attempts"):
        await executor.run(SNAPSHOT, "echo hi", timeout_s=30, mutate=False)
    assert len(client.runs) == 4
    assert rec.sleeps == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    "error",
    [ForbiddenError(), NotFoundError(), ApiStatusCodeError(status=400), UnprocessableEntityError()],
)
async def test_non_transient_errors_are_not_retried(error: Exception) -> None:
    executor, client, rec = make(error)
    with pytest.raises(ExecutorError):
        await executor.run(SNAPSHOT, "echo hi", timeout_s=30, mutate=False)
    assert len(client.runs) == 1 and rec.sleeps == []


async def test_mutate_maps_to_disposable() -> None:
    executor, client, _ = make()
    _, same = await executor.run(SNAPSHOT, "ls", timeout_s=30, mutate=False)
    assert same == SNAPSHOT
    assert client.runs[-1]["disposable"] is True
    assert client.runs[-1]["shell"] == "ls"
    assert client.runs[-1]["cwd"] == REPO_ROOT
    assert client.runs[-1]["timeout"] == 30
    assert client.runs[-1]["truncate_output_at"] == 65536
    _, changed = await executor.run(SNAPSHOT, "pip install -e .", timeout_s=600, mutate=True)
    assert client.runs[-1]["disposable"] is False
    assert changed.image_id != SNAPSHOT.image_id and changed.parent_id == SNAPSHOT.image_id


async def test_no_credential_ever_reaches_the_sandbox(tmp_path: Path) -> None:
    executor, client, _ = make()
    tarball = tmp_path / "repo.tgz"
    tarball.write_bytes(b"tar")
    snapshot = await executor.prepare_repo(tarball, "python:3.12")
    await executor.run(snapshot, "python -m pytest", timeout_s=30, mutate=False)
    await executor.write_files(snapshot, {"a.py": b"print('hello')\n"})
    for call in client.runs:
        assert not call.get("env"), call
        for source in (call.get("files") or {}).values():
            content = source.read_bytes() if isinstance(source, Path) else source
            assert SECRET.encode() not in content
    assert SECRET not in repr(client.runs) and SECRET not in repr(client.applied)

    with pytest.raises(ExecutorError, match="credential"):
        await executor.run(snapshot, f"echo {SECRET}", timeout_s=30, mutate=False)
    with pytest.raises(ExecutorError, match="credential"):
        await executor.write_files(snapshot, {"leak.py": f"KEY = '{SECRET}'".encode()})
    assert len(client.applied) == 1


async def test_prepare_repo_uploads_and_extracts_the_tarball(tmp_path: Path) -> None:
    executor, client, _ = make()
    tarball = tmp_path / "repo.tgz"
    tarball.write_bytes(b"tar")
    snapshot = await executor.prepare_repo(tarball, "python:3.12")
    assert client.used == ["oci:python:3.12"]
    [call] = client.runs
    assert call["files"] == {"/tmp/repo.tgz": tarball}
    assert "tar -xzf /tmp/repo.tgz" in call["shell"] and "--strip-components=1" in call["shell"]
    assert call["disposable"] is False
    assert snapshot.label == "source" and snapshot.image_id


async def test_prepare_repo_fails_clearly_when_extraction_fails(tmp_path: Path) -> None:
    executor, _, _ = make({"exit_code": 2, "stderr": "tar: invalid"})
    tarball = tmp_path / "repo.tgz"
    tarball.write_bytes(b"x")
    with pytest.raises(ExecutorError, match="extract"):
        await executor.prepare_repo(tarball, "python:3.12")


async def test_command_timeouts_are_results_not_errors() -> None:
    executor, _, _ = make(
        OperationTimedOutError(operation_uuid=uuid4()), {"timed_out": True, "exit_code": -1}
    )
    first, _ = await executor.run(SNAPSHOT, "sleep 999", timeout_s=5, mutate=False)
    second, _ = await executor.run(SNAPSHOT, "sleep 999", timeout_s=5, mutate=False)
    assert first.timed_out and not first.ok
    assert second.timed_out and not second.ok


async def test_cancel_all_cancels_in_flight_operations() -> None:
    executor, client, _ = make(HANG)
    task = asyncio.create_task(executor.run(SNAPSHOT, "sleep 300", timeout_s=300, mutate=False))
    await asyncio.wait_for(client.started.wait(), 5)
    await executor.cancel_all()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.cancelled == 1


async def test_sandbox_ops_are_published_with_image_ids() -> None:
    executor, _, rec = make({"exit_code": 0})
    _, changed = await executor.run(SNAPSHOT, "pip install .", timeout_s=60, mutate=True)
    [(event_type, data)] = rec.events
    assert event_type is EventType.SANDBOX_OP
    assert data == {
        "op": "run",
        "image_in": SNAPSHOT.image_id,
        "image_out": changed.image_id,
        "command": "pip install .",
        "exit_code": 0,
        "elapsed_s": 0.25,
        "disposable": False,
    }


async def test_read_file_and_missing_files() -> None:
    executor, client, rec = make()
    client.files[f"{REPO_ROOT}/pkg/a.py"] = b"x = 1\n"
    assert await executor.read_file(SNAPSHOT, "pkg/a.py") == b"x = 1\n"
    with pytest.raises(FileNotFoundError):
        await executor.read_file(SNAPSHOT, "pkg/missing.py")
    assert rec.events[0][1]["op"] == "read"


async def test_list_dir_walks_directories_up_to_depth() -> None:
    executor, client, _ = make()
    for path in ("a.py", "pkg/b.py", "pkg/sub/c.py", ".git/HEAD"):
        client.files[f"{REPO_ROOT}/{path}"] = b"x"
    entries = await executor.list_dir(SNAPSHOT, ".", depth=2)
    assert {(e.path, e.type) for e in entries} == {
        ("a.py", "file"),
        ("pkg", "dir"),
        ("pkg/b.py", "file"),
        ("pkg/sub", "dir"),
    }
    with pytest.raises(FileNotFoundError):
        await executor.list_dir(SNAPSHOT, "missing")


async def test_write_files_creates_a_new_snapshot() -> None:
    executor, client, _ = make()
    changed = await executor.write_files(SNAPSHOT, {"pkg/a.py": b"y = 2\n"})
    assert client.applied == [{f"{REPO_ROOT}/pkg/a.py": b"y = 2\n"}]
    assert changed.parent_id == SNAPSHOT.image_id and changed.image_id != SNAPSHOT.image_id


async def test_tag_names_the_snapshot() -> None:
    executor, client, _ = make()
    tagged = await executor.tag(SNAPSHOT, "fixproof/run-20261010-000000-abcdef/installed")
    assert client.tags == [(SNAPSHOT.image_id, "fixproof/run-20261010-000000-abcdef/installed")]
    assert tagged.tag == "fixproof/run-20261010-000000-abcdef/installed"
    assert tagged.label == "installed"


async def test_list_images_for_doctor() -> None:
    executor, _, _ = make()
    assert await executor.list_images(limit=1) == ["python:3.12"]


def test_retry_delays_are_exponential() -> None:
    delays = list(itertools.islice(ContreeExecutor.DEFAULT_RETRY_DELAYS, 3))
    assert delays == [1.0, 2.0, 4.0]
