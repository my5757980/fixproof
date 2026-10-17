"""DockerExecutor (DEV ONLY) with a recorded fake ``docker`` CLI; no Docker daemon needed."""

from __future__ import annotations

import io
import itertools
import tarfile
import tempfile
from collections import deque
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

import pytest

from fixproof.models import Snapshot
from fixproof.sandbox.docker_dev import (
    BANNER,
    COMMIT_TIMEOUT_S,
    EXTRACT_COMMAND,
    STEP_SCRIPT,
    TARBALL_PATH,
    DockerExecutor,
)
from fixproof.sandbox.executor import REPO_ROOT, ExecutorError

STEP = PurePosixPath(STEP_SCRIPT)


class FakeDocker:
    """Records docker CLI calls and answers them like the real CLI would."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.stdin: list[bytes | None] = []
        self.timeouts: list[float | None] = []
        self.commit_timeout = False
        self.ids = itertools.count(1)
        self.start_result: tuple[int, bytes, bytes] = (0, b"out", b"")
        self.start_results: deque[tuple[int, bytes, bytes]] = deque()  # used first, in order
        self.start_timeout = False
        self.copy_in_result: tuple[int, bytes, bytes] = (0, b"", b"")
        self.files: dict[str, bytes] = {}

    async def __call__(
        self, args: Sequence[str], stdin: bytes | None = None, timeout: float | None = None
    ) -> tuple[int, bytes, bytes]:
        self.calls.append(list(args))
        self.stdin.append(stdin)
        self.timeouts.append(timeout)
        command = args[1]
        if command == "create":
            return 0, f"container-{next(self.ids)}\n".encode(), b""
        if command == "commit":
            if self.commit_timeout:
                raise TimeoutError
            return 0, f"sha256:image-{next(self.ids)}\n".encode(), b""
        if command == "start":
            if self.start_timeout:
                raise TimeoutError
            return self.start_results.popleft() if self.start_results else self.start_result
        if command == "cp" and args[2] == "-":
            return self.copy_in_result
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

    def copied_in(self, directory: str = REPO_ROOT) -> dict[str, bytes]:
        """Files streamed into ``directory`` of containers with ``docker cp -`` (later win)."""
        files: dict[str, bytes] = {}
        for call, payload in zip(self.calls, self.stdin, strict=True):
            if call[1] == "cp" and call[2] == "-" and call[3].endswith(f":{directory}"):
                assert payload is not None
                with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
                    for member in tar.getmembers():
                        handle = tar.extractfile(member)
                        assert handle is not None
                        files[member.name] = handle.read()
        return files

    def scripts(self) -> list[str]:
        """Every step script copied into a chain container, in order."""
        scripts = []
        for call, payload in zip(self.calls, self.stdin, strict=True):
            if call[1] == "cp" and call[2] == "-" and call[3].endswith(f":{STEP.parent}"):
                assert payload is not None
                with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
                    handle = tar.extractfile(STEP.name)
                    assert handle is not None
                    scripts.append(handle.read().decode())
        return scripts


SNAPSHOT = Snapshot(image_id="sha256:base", label="installed")


def make() -> tuple[DockerExecutor, FakeDocker]:
    docker = FakeDocker()
    return DockerExecutor(runner=docker, banner_stream=io.StringIO()), docker


def make_tarball(path: Path, files: dict[str, bytes]) -> Path:
    """Write a GitHub-style tarball: every path sits under one top-level folder."""
    with tarfile.open(path, "w:gz") as tar:
        top = tarfile.TarInfo("owner-repo-abc123")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        for name, content in files.items():
            info = tarfile.TarInfo(f"owner-repo-abc123/{name}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return path


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


# -- chains of mutating runs -----------------------------------------------------------------


async def test_mutating_runs_have_network_and_commit_only_when_needed() -> None:
    executor, docker = make()
    _, after = await executor.run(SNAPSHOT, "pip install -e .", timeout_s=600, mutate=True)
    [create] = docker.commands("create")
    assert "--network" not in create and create[-1] == f"sh {STEP_SCRIPT}"
    assert docker.scripts() == ["pip install -e ."]
    assert docker.commands("commit") == [] and after.parent_id == SNAPSHOT.image_id
    await executor.run(after, "python -m pytest", timeout_s=60, mutate=False)
    [commit] = docker.commands("commit")
    disposable = docker.commands("create")[-1]
    assert disposable[-4].startswith("sha256:image-") and "--network" in disposable


async def test_mutating_runs_continue_in_one_container_and_commit_once() -> None:
    executor, docker = make()
    snapshot = SNAPSHOT
    for command in ("pip install -r requirements.txt", "pip install -e .", "git init"):
        result, snapshot = await executor.run(snapshot, command, timeout_s=600, mutate=True)
        assert result.ok
    assert len(docker.commands("create")) == 1 and len(docker.commands("start")) == 3
    assert docker.scripts() == ["pip install -r requirements.txt", "pip install -e .", "git init"]
    assert docker.commands("commit") == []
    docker.files[f"{REPO_ROOT}/setup.py"] = b"setup()\n"
    assert await executor.read_file(snapshot, "setup.py") == b"setup()\n"
    await executor.run(snapshot, "python -m pytest", timeout_s=60, mutate=False)
    assert len(docker.commands("commit")) == 1


async def test_a_retry_after_a_failed_step_starts_from_a_rebuilt_container() -> None:
    executor, docker = make()
    _, first = await executor.run(SNAPSHOT, "step 1", timeout_s=600, mutate=True)
    docker.start_results.append((1, b"", b"boom"))
    failed, _ = await executor.run(first, "step 2", timeout_s=600, mutate=True)
    assert not failed.ok
    retried, after = await executor.run(first, "step 2b", timeout_s=600, mutate=True)
    assert retried.ok and after.parent_id == first.image_id
    creates = docker.commands("create")
    assert len(creates) == 2 and creates[1][-4] == SNAPSHOT.image_id
    assert docker.scripts() == ["step 1", "step 2", "step 1", "step 2b"]
    assert docker.commands("commit") == []


async def test_an_older_state_of_a_chain_is_rebuilt_before_it_is_used() -> None:
    executor, docker = make()
    _, first = await executor.run(SNAPSHOT, "step 1", timeout_s=600, mutate=True)
    await executor.run(first, "step 2", timeout_s=600, mutate=True)
    await executor.run(first, "python -m pytest", timeout_s=60, mutate=False)
    assert docker.scripts() == ["step 1", "step 2", "step 1"]
    assert len(docker.commands("commit")) == 1 and len(docker.commands("create")) == 3


async def test_a_failed_rebuild_is_an_executor_error() -> None:
    executor, docker = make()
    _, first = await executor.run(SNAPSHOT, "step 1", timeout_s=600, mutate=True)
    await executor.run(first, "step 2", timeout_s=600, mutate=True)
    docker.start_results.append((1, b"", b"network down"))
    with pytest.raises(ExecutorError, match="rebuild"):
        await executor.run(first, "python -m pytest", timeout_s=60, mutate=False)


async def test_commits_get_a_long_timeout_and_a_clear_error() -> None:
    executor, docker = make()
    _, installed = await executor.run(SNAPSHOT, "pip install -e .", timeout_s=600, mutate=True)
    docker.commit_timeout = True
    with pytest.raises(ExecutorError, match=r"docker commit did not finish within 1800 s"):
        await executor.run(installed, "python -m pytest", timeout_s=60, mutate=False)
    commit_index = docker.calls.index(docker.commands("commit")[0])
    assert docker.timeouts[commit_index] == COMMIT_TIMEOUT_S
    docker.commit_timeout = False
    result, _ = await executor.run(installed, "python -m pytest", timeout_s=60, mutate=False)
    assert result.ok  # the chain is still there, so the next use commits it


async def test_timeouts_kill_the_container_and_keep_the_snapshot() -> None:
    executor, docker = make()
    docker.start_timeout = True
    result, same = await executor.run(SNAPSHOT, "sleep 999", timeout_s=5, mutate=True)
    assert result.timed_out and not result.ok and same == SNAPSHOT
    assert docker.commands("kill")
    assert docker.commands("commit") == []


async def test_a_timed_out_step_leaves_its_input_to_be_rebuilt() -> None:
    executor, docker = make()
    _, first = await executor.run(SNAPSHOT, "step 1", timeout_s=600, mutate=True)
    docker.start_timeout = True
    timed_out, same = await executor.run(first, "sleep 999", timeout_s=5, mutate=True)
    assert timed_out.timed_out and same == first
    docker.start_timeout = False
    await executor.run(first, "step 2", timeout_s=600, mutate=True)
    assert docker.scripts() == ["step 1", "sleep 999", "step 1", "step 2"]


# -- files and reads -------------------------------------------------------------------------


async def test_read_file_uses_docker_cp() -> None:
    executor, docker = make()
    docker.files[f"{REPO_ROOT}/pkg/a.py"] = b"x = 1\n"
    assert await executor.read_file(SNAPSHOT, "pkg/a.py") == b"x = 1\n"
    with pytest.raises(FileNotFoundError):
        await executor.read_file(SNAPSHOT, "missing.py")


async def test_write_files_needs_no_container_and_no_commit() -> None:
    executor, docker = make()
    after = await executor.write_files(SNAPSHOT, {"pkg/a.py": b"y = 2\n"})
    assert docker.calls == []
    assert after.parent_id == SNAPSHOT.image_id and after.image_id != SNAPSHOT.image_id


async def test_runs_get_the_written_files_streamed_into_a_container_of_the_image() -> None:
    executor, docker = make()
    after = await executor.write_files(SNAPSHOT, {"pkg/a.py": b"y = 2\n"})
    await executor.run(after, "python -m pytest", timeout_s=60, mutate=False)
    [create] = docker.commands("create")
    assert create[-4] == SNAPSHOT.image_id
    [cp] = docker.commands("cp")
    assert cp[2] == "-" and cp[3].endswith(f":{REPO_ROOT}")
    assert docker.calls.index(cp) < docker.calls.index(docker.commands("start")[0])
    assert docker.copied_in() == {"pkg/a.py": b"y = 2\n"}
    assert docker.commands("commit") == []


async def test_reads_see_written_files_and_the_latest_write_wins() -> None:
    executor, docker = make()
    first = await executor.write_files(SNAPSHOT, {"pkg/a.py": b"1\n", "pkg/b.py": b"b\n"})
    second = await executor.write_files(first, {"pkg/a.py": b"2\n"})
    assert await executor.read_file(second, "pkg/a.py") == b"2\n"
    assert await executor.read_file(first, "pkg/a.py") == b"1\n"  # earlier snapshots keep theirs
    assert await executor.read_file(second, "pkg/b.py") == b"b\n"
    with pytest.raises(IsADirectoryError):
        await executor.read_file(second, "pkg")
    assert docker.calls == []
    docker.files[f"{REPO_ROOT}/setup.py"] = b"base\n"
    assert await executor.read_file(second, "setup.py") == b"base\n"
    [create] = docker.commands("create")
    assert create[-4] == SNAPSHOT.image_id
    await executor.run(second, "true", timeout_s=5, mutate=False)
    assert docker.copied_in() == {"pkg/a.py": b"2\n", "pkg/b.py": b"b\n"}


async def test_a_mutating_run_on_written_files_commits_them_once_when_needed() -> None:
    executor, docker = make()
    written = await executor.write_files(SNAPSHOT, {"fix.patch": b"diff\n"})
    _, applied = await executor.run(written, "git apply fix.patch", timeout_s=60, mutate=True)
    assert docker.copied_in() == {"fix.patch": b"diff\n"} and docker.commands("commit") == []
    assert applied.parent_id == written.image_id
    await executor.run(applied, "python -m pytest", timeout_s=60, mutate=False)
    assert len(docker.commands("commit")) == 1
    assert len(docker.commands("cp")) == 2  # the patch and the step script, nothing for pytest


async def test_a_failed_copy_removes_the_container_before_anything_runs() -> None:
    executor, docker = make()
    written = await executor.write_files(SNAPSHOT, {"a.py": b"x\n"})
    docker.copy_in_result = (1, b"", b"no space left on device")
    with pytest.raises(ExecutorError, match="no space left"):
        await executor.run(written, "true", timeout_s=5, mutate=False)
    assert docker.commands("rm") and docker.commands("start") == []


async def test_snapshots_not_committed_yet_are_labelled_but_not_tagged() -> None:
    executor, docker = make()
    written = await executor.write_files(SNAPSHOT, {"tests/test_x.py": b"x\n"})
    tagged = await executor.tag(written, "fixproof/run-20261015-000000-abcdef/repro")
    assert tagged.image_id == written.image_id and tagged.label == "repro"
    _, installed = await executor.run(SNAPSHOT, "git init", timeout_s=60, mutate=True)
    chain = await executor.tag(installed, "fixproof/run-20261015-000000-abcdef/installed")
    assert chain.label == "installed" and tagged.tag is None and chain.tag is None
    assert docker.commands("tag") == []


async def test_list_dir_parses_find_output() -> None:
    executor, docker = make()
    docker.start_result = (0, b"f\t6\t./a.py\nd\t4096\t./pkg\nf\t3\t./pkg/b.py\n", b"")
    entries = await executor.list_dir(SNAPSHOT, ".", depth=2)
    assert [(e.path, e.type, e.size) for e in entries] == [
        ("a.py", "file", 6),
        ("pkg", "dir", 0),
        ("pkg/b.py", "file", 3),
    ]


# -- the repository tarball ------------------------------------------------------------------


async def test_prepare_repo_keeps_the_tarball_without_a_container(tmp_path: Path) -> None:
    executor, docker = make()
    tarball = make_tarball(tmp_path / "repo.tgz", {"setup.py": b"setup()\n"})
    source = await executor.prepare_repo(tarball, "python:3.12")
    tarball.unlink()  # the caller's temporary folder is gone after prepare_repo returns
    assert docker.calls == [] and source.label == "source"
    assert await executor.read_file(source, "setup.py") == b"setup()\n"


async def test_the_first_mutating_run_extracts_the_repository(tmp_path: Path) -> None:
    executor, docker = make()
    tarball = make_tarball(tmp_path / "repo.tgz", {"setup.py": b"setup()\n"})
    source = await executor.prepare_repo(tarball, "python:3.12")
    _, installed = await executor.run(source, "pip install -e .", timeout_s=600, mutate=True)
    [create] = docker.commands("create")
    assert create[-4] == "python:3.12" and "--network" not in create
    [copy, _script] = docker.commands("cp")
    assert copy[3].endswith(f":{TARBALL_PATH}")
    assert docker.calls.index(copy) < docker.calls.index(docker.commands("start")[0])
    assert docker.scripts() == [f"{EXTRACT_COMMAND} && sh -c 'pip install -e .'"]
    assert docker.commands("commit") == [] and installed.parent_id == source.image_id
    await executor.run(installed, "python -m pytest", timeout_s=60, mutate=False)
    assert len(docker.commands("commit")) == 1
    assert docker.commands("create")[-1][-1] == "python -m pytest"


async def test_disposable_runs_on_the_tarball_extract_it_first(tmp_path: Path) -> None:
    executor, docker = make()
    tarball = make_tarball(tmp_path / "repo.tgz", {"setup.py": b"setup()\n"})
    source = await executor.prepare_repo(tarball, "python:3.12")
    await executor.run(source, "ls", timeout_s=60, mutate=False)
    [create] = docker.commands("create")
    assert create[-1] == f"{EXTRACT_COMMAND} && sh -c ls" and "--network" in create
    assert docker.commands("commit") == []


async def test_reads_of_a_repository_not_extracted_yet_come_from_its_tarball(
    tmp_path: Path,
) -> None:
    executor, docker = make()
    tarball = make_tarball(tmp_path / "repo.tgz", {"pkg/a.py": b"x = 1\n"})
    source = await executor.prepare_repo(tarball, "python:3.12")
    assert await executor.read_file(source, "pkg/a.py") == b"x = 1\n"
    with pytest.raises(IsADirectoryError):
        await executor.read_file(source, "pkg")
    with pytest.raises(FileNotFoundError):
        await executor.read_file(source, "missing.py")
    assert docker.calls == []


async def test_writing_to_a_repository_not_extracted_yet_commits_it_first(
    tmp_path: Path,
) -> None:
    executor, docker = make()
    tarball = make_tarball(tmp_path / "repo.tgz", {"pkg/a.py": b"x = 1\n"})
    source = await executor.prepare_repo(tarball, "python:3.12")
    written = await executor.write_files(source, {"pkg/a.py": b"x = 2\n"})
    assert len(docker.commands("commit")) == 1
    assert await executor.read_file(written, "pkg/a.py") == b"x = 2\n"
    docker.calls.clear()
    docker.stdin.clear()
    await executor.run(written, "true", timeout_s=5, mutate=False)
    [create] = docker.commands("create")
    assert create[-4].startswith("sha256:image-") and create[-1] == "true"
    assert docker.copied_in() == {"pkg/a.py": b"x = 2\n"}


# -- cleanup ---------------------------------------------------------------------------------


async def test_close_removes_the_tarball_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    executor, _ = make()
    tarball = make_tarball(tmp_path / "repo.tgz", {"setup.py": b"setup()\n"})
    await executor.prepare_repo(tarball, "python:3.12")
    assert any(scratch.iterdir())
    await executor.close()
    assert not any(scratch.iterdir())


async def test_close_removes_the_containers_snapshots_and_tags_it_created() -> None:
    executor, docker = make()
    _, installed = await executor.run(SNAPSHOT, "pip install -e .", timeout_s=600, mutate=True)
    await executor.run(installed, "true", timeout_s=5, mutate=False)  # commits the chain
    tagged = await executor.tag(installed, "fixproof/run-20261011-000000-abcdef/installed")
    assert tagged.tag == "fixproof/run-20261011-000000-abcdef/installed"
    await executor.run(SNAPSHOT, "pip install x", timeout_s=600, mutate=True)  # left open
    removed_before = len(docker.commands("rm"))
    await executor.close()
    assert len(docker.commands("rm")) == removed_before + 1  # the open chain's container
    removed = [call[3] for call in docker.commands("rmi")]
    assert removed[0] == "fixproof/run-20261011-000000-abcdef/installed:latest"
    assert len(removed) == 2 and removed[1].startswith("sha256:image-")
    assert SNAPSHOT.image_id not in removed  # the base image is never removed
