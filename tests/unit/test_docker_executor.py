"""DockerExecutor (DEV ONLY) with a recorded fake ``docker`` CLI; no Docker daemon needed."""

from __future__ import annotations

import io
import itertools
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from fixproof.models import Snapshot
from fixproof.sandbox.docker_dev import BANNER, DockerExecutor
from fixproof.sandbox.executor import REPO_ROOT


class FakeDocker:
    """Records docker CLI calls and answers them like the real CLI would."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.stdin: list[bytes | None] = []
        self.ids = itertools.count(1)
        self.start_result: tuple[int, bytes, bytes] = (0, b"out", b"")
        self.start_timeout = False
        self.files: dict[str, bytes] = {}

    async def __call__(
        self, args: Sequence[str], stdin: bytes | None = None, timeout: float | None = None
    ) -> tuple[int, bytes, bytes]:
        self.calls.append(list(args))
        self.stdin.append(stdin)
        command = args[1]
        if command == "create":
            return 0, f"container-{next(self.ids)}\n".encode(), b""
        if command == "commit":
            return 0, f"sha256:image-{next(self.ids)}\n".encode(), b""
        if command == "start":
            if self.start_timeout:
                raise TimeoutError
            return self.start_result
        if command == "cp" and args[3] == "-":
            path = args[2].split(":", 1)[1]
            if path not in self.files:
                return 1, b"", b"Could not find the file"
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w") as tar:
                info = tarfile.TarInfo(Path(path).name)
                info.size = len(self.files[path])
                tar.addfile(info, io.BytesIO(self.files[path]))
            return 0, buffer.getvalue(), b""
        return 0, b"", b""

    def commands(self, name: str) -> list[list[str]]:
        return [call for call in self.calls if call[1] == name]


SNAPSHOT = Snapshot(image_id="sha256:base", label="installed")


def make() -> tuple[DockerExecutor, FakeDocker]:
    docker = FakeDocker()
    return DockerExecutor(runner=docker, banner_stream=io.StringIO()), docker


def test_banner_is_printed_on_construction(capsys: pytest.CaptureFixture[str]) -> None:
    DockerExecutor(runner=FakeDocker())
    assert BANNER in capsys.readouterr().err


async def test_disposable_runs_have_no_network_and_keep_the_snapshot() -> None:
    executor, docker = make()
    result, same = await executor.run(SNAPSHOT, "python -m pytest", timeout_s=60, mutate=False)
    assert result.ok and result.stdout == "out"
    assert same == SNAPSHOT
    [create] = docker.commands("create")
    assert create[create.index("--network") + 1] == "none"
    assert create[-3:] == ["sh", "-c", "python -m pytest"]
    assert docker.commands("commit") == []
    assert docker.commands("rm")


async def test_mutating_runs_have_network_and_commit_a_new_image() -> None:
    executor, docker = make()
    _, after = await executor.run(SNAPSHOT, "pip install -e .", timeout_s=600, mutate=True)
    [create] = docker.commands("create")
    assert "--network" not in create
    assert after.image_id.startswith("sha256:image-") and after.parent_id == SNAPSHOT.image_id


async def test_timeouts_kill_the_container() -> None:
    executor, docker = make()
    docker.start_timeout = True
    result, same = await executor.run(SNAPSHOT, "sleep 999", timeout_s=5, mutate=True)
    assert result.timed_out and not result.ok and same == SNAPSHOT
    assert docker.commands("kill")
    assert docker.commands("commit") == []


async def test_read_file_uses_docker_cp() -> None:
    executor, docker = make()
    docker.files[f"{REPO_ROOT}/pkg/a.py"] = b"x = 1\n"
    assert await executor.read_file(SNAPSHOT, "pkg/a.py") == b"x = 1\n"
    with pytest.raises(FileNotFoundError):
        await executor.read_file(SNAPSHOT, "missing.py")


async def test_write_files_streams_a_tar_and_commits() -> None:
    executor, docker = make()
    after = await executor.write_files(SNAPSHOT, {"pkg/a.py": b"y = 2\n"})
    [cp] = [c for c in docker.commands("cp") if c[2] == "-"]
    payload = docker.stdin[docker.calls.index(cp)]
    assert payload is not None
    with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
        member = tar.getmember("pkg/a.py")
        handle = tar.extractfile(member)
        assert handle is not None and handle.read() == b"y = 2\n"
    assert after.parent_id == SNAPSHOT.image_id


async def test_list_dir_parses_find_output() -> None:
    executor, docker = make()
    docker.start_result = (0, b"f\t6\t./a.py\nd\t4096\t./pkg\nf\t3\t./pkg/b.py\n", b"")
    entries = await executor.list_dir(SNAPSHOT, ".", depth=2)
    assert [(e.path, e.type, e.size) for e in entries] == [
        ("a.py", "file", 6),
        ("pkg", "dir", 0),
        ("pkg/b.py", "file", 3),
    ]


async def test_close_removes_the_snapshots_and_tags_it_created() -> None:
    executor, docker = make()
    _, after = await executor.run(SNAPSHOT, "pip install -e .", timeout_s=600, mutate=True)
    await executor.tag(after, "fixproof/run-20261011-000000-abcdef/installed")
    await executor.close()
    removed = [call[3] for call in docker.commands("rmi")]
    assert removed == ["fixproof/run-20261011-000000-abcdef/installed:latest", after.image_id]
    assert SNAPSHOT.image_id not in removed  # the base image is never removed
