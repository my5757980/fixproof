"""Opt-in live smoke tests against Nebius Token Factory and Token Factory Sandboxes.

Run with ``FIXPROOF_LIVE=1 uv run pytest -m live`` (credentials come from the environment or
``.env``). They cost a few cents and answer the VERIFY-ON-ACCESS questions in research.md R4:
key and project, upload, persistent snapshots, reads, branching, and PyPI egress.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from fixproof.agent import prompts
from fixproof.config import Settings, load_settings
from fixproof.llm.client import TokenFactoryClient
from fixproof.models import ModelRole, Snapshot
from fixproof.sandbox.contree import ContreeExecutor
from fixproof.sandbox.executor import git_baseline_command
from fixproof.tools.handlers import ToolPhase
from fixproof.tools.registry import build_registry
from tests.fakes.fake_executor import make_tarball

LIVE = os.environ.get("FIXPROOF_LIVE", "").lower() in ("1", "true", "yes")
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not LIVE, reason="live tests run only with FIXPROOF_LIVE=1"),
]


@pytest.fixture(scope="module")
def settings() -> Settings:
    return load_settings()


async def test_models_endpoint_lists_the_configured_models(settings: Settings) -> None:
    available = {m.lower() for m in await TokenFactoryClient(settings).list_models()}
    for model in settings.models_by_role().values():
        assert model.lower() in available, f"{model} is not served by {settings.nebius_base_url}"


@pytest.mark.parametrize("role", [ModelRole.WORKER, ModelRole.PLANNER])
async def test_each_role_makes_a_valid_tool_call(settings: Settings, role: ModelRole) -> None:
    tools = build_registry().openai_tools(ToolPhase.FIX)
    messages = [
        {"role": "system", "content": prompts.worker_system_prompt()},
        {"role": "user", "content": "Read calc/core.py starting at line 1. Call one tool."},
    ]
    reply = await TokenFactoryClient(settings).complete(role, messages, tools)
    assert reply.tool_calls, reply.content
    call = reply.tool_calls[0]
    assert call.name == "read_file" and call.args.get("path") == "calc/core.py", call
    assert reply.prompt_tokens > 0 and reply.cost_usd > 0


@pytest.fixture
async def sandbox(settings: Settings) -> AsyncIterator[ContreeExecutor]:
    executor = ContreeExecutor.from_settings(settings)
    yield executor
    await executor.close()


@pytest.fixture
async def source(sandbox: ContreeExecutor, settings: Settings, tmp_path: Path) -> Snapshot:
    tarball = make_tarball(
        tmp_path / "repo.tgz", {"hello.py": "print('hi')\n", "pkg/data.txt": "x\n"}
    )
    return await sandbox.prepare_repo(tarball, settings.base_image)


async def test_sandbox_runs_reads_and_branches(sandbox: ContreeExecutor, source: Snapshot) -> None:
    result, same = await sandbox.run(
        source, "echo hello && python --version", timeout_s=60, mutate=False
    )
    assert result.ok and "hello" in result.stdout and same == source
    assert await sandbox.read_file(source, "hello.py") == b"print('hi')\n"

    _, left = await sandbox.run(source, "echo left > branch.txt", timeout_s=60, mutate=True)
    _, right = await sandbox.run(source, "echo right > branch.txt", timeout_s=60, mutate=True)
    assert await sandbox.read_file(left, "branch.txt") == b"left\n"
    assert await sandbox.read_file(right, "branch.txt") == b"right\n"

    written = await sandbox.write_files(left, {"new.py": b"x = 1\n"})
    assert await sandbox.read_file(written, "new.py") == b"x = 1\n"
    names = {entry.path for entry in await sandbox.list_dir(written, ".", 2)}
    assert {"hello.py", "new.py", "pkg", "pkg/data.txt"} <= names


async def test_sandbox_has_git_for_baselines(sandbox: ContreeExecutor, source: Snapshot) -> None:
    result, _ = await sandbox.run(source, git_baseline_command(), timeout_s=120, mutate=True)
    assert result.ok, result.stderr


async def test_sandbox_can_reach_pypi(sandbox: ContreeExecutor, source: Snapshot) -> None:
    command = "python -m pip download --no-deps --quiet -d /tmp/dl pytest && ls /tmp/dl"
    result, _ = await sandbox.run(source, command, timeout_s=300, mutate=False)
    assert result.ok and "pytest" in result.stdout, result.stderr


async def test_sandbox_command_timeout_is_reported(
    sandbox: ContreeExecutor, source: Snapshot
) -> None:
    result, _ = await sandbox.run(source, "sleep 30", timeout_s=5, mutate=False)
    assert result.timed_out and not result.ok
