"""CLI commands with fakes injected through ``cli.factories`` (contracts/cli.md)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click.testing import Result
from typer.testing import CliRunner

from fixproof import cli
from fixproof.cli import Factories, app, exit_code_for
from fixproof.config import DEFAULT_WORKER_MODEL, Settings
from fixproof.models import ModelRole, OutcomeLabel, Report, StopReason
from tests.fakes.calc_repo import CALC_FILES, ISSUE_URL, REPO_URL, calc_behavior
from tests.fakes.fake_executor import FakeExecutor
from tests.fakes.fake_github import FakeGitHub
from tests.fakes.fake_model import FakeModelClient, reply_bad_args, reply_json, reply_text
from tests.fakes.scenario import happy_planner, happy_worker, plan_reply
from tests.fakes.settings import make_settings

FIX = ["fix", "--repo", REPO_URL, "--issue", ISSUE_URL]
runner = CliRunner()

Install = Callable[..., FakeModelClient]


def invoke(*args: str) -> Result:
    return runner.invoke(app, list(args))


@pytest.fixture
def use_fakes(monkeypatch: pytest.MonkeyPatch) -> Install:
    def install(
        *,
        planner: list[Any] | None = None,
        worker: list[Any] | None = None,
        executor: FakeExecutor | None = None,
        settings: Settings | None = None,
        model: FakeModelClient | None = None,
    ) -> FakeModelClient:
        chosen_settings = settings or make_settings()
        fake_model = model or FakeModelClient()
        if model is None:
            fake_model.script(ModelRole.PLANNER, *(happy_planner() if planner is None else planner))
            fake_model.script(ModelRole.WORKER, *(happy_worker() if worker is None else worker))
        fake_executor = executor or FakeExecutor()
        fake_executor.test_behavior = fake_executor.test_behavior or calc_behavior
        github = FakeGitHub(CALC_FILES)
        monkeypatch.setattr(
            cli,
            "factories",
            Factories(
                settings=lambda: chosen_settings,
                model=lambda s: fake_model,
                executor=lambda s, on_event: fake_executor,
                repo_source=lambda s: github,
            ),
        )
        return fake_model

    return install


def test_fix_verified_exits_0_and_prints_the_plan_first(use_fakes: Install, tmp_path: Path) -> None:
    use_fakes()
    result = invoke(*FIX, "--out", str(tmp_path))
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert out.index("plan (initial)") < out.index("-> edit_file")
    assert "Result: verified (completed)" in out
    [run_dir] = list(tmp_path.iterdir())
    assert (run_dir / "report.md").is_file() and (run_dir / "patch.diff").is_file()


def test_fix_json_prints_the_report_on_stdout(use_fakes: Install, tmp_path: Path) -> None:
    use_fakes()
    result = invoke(*FIX, "--out", str(tmp_path), "--json")
    assert result.exit_code == 0, result.output
    report = Report.model_validate_json(result.stdout)
    assert report.label is OutcomeLabel.VERIFIED
    assert "plan (initial)" in result.stderr


def test_fix_not_verified_exits_20(use_fakes: Install, tmp_path: Path) -> None:
    use_fakes(
        planner=[plan_reply(), plan_reply()],
        worker=[reply_bad_args("read_file", "{"), reply_text("no tool"), reply_text("still none")],
    )
    result = invoke(*FIX, "--out", str(tmp_path))
    assert result.exit_code == 20, result.output
    assert "invalid_tool_calls" in result.stdout


def test_fix_setup_failed_exits_40(use_fakes: Install, tmp_path: Path) -> None:
    executor = FakeExecutor()
    executor.install_ok = False
    use_fakes(
        planner=[plan_reply()],
        worker=[reply_json({"command": "python -m pip install ."}, role=ModelRole.WORKER)],
        executor=executor,
    )
    result = invoke(*FIX, "--out", str(tmp_path))
    assert result.exit_code == 40, result.output


@pytest.mark.parametrize(
    "args",
    [
        ["fix", "--repo", REPO_URL],
        ["fix", "--repo", REPO_URL, "--issue", ISSUE_URL, "--bug", "add is wrong"],
        ["fix", "--repo", REPO_URL, "--test", "tests/t.py::a", "--bug", "add is wrong"],
        ["fix", "--repo", "https://gitlab.com/acme/calc", "--bug", "add is wrong"],
        ["fix", "--repo", REPO_URL, "--issue", "https://github.com/other/repo/issues/1"],
        ["fix", "--repo", REPO_URL, "--bug", "add is wrong", "--max-steps", "2"],
    ],
)
def test_invalid_input_exits_2(use_fakes: Install, tmp_path: Path, args: list[str]) -> None:
    model = use_fakes(planner=[], worker=[])
    result = invoke(*args, "--out", str(tmp_path))
    assert result.exit_code == 2, result.output
    assert "error:" in result.stderr
    assert model.requests == [] and list(tmp_path.iterdir()) == []


def test_missing_api_key_is_invalid_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = make_settings(nebius_api_key=None)
    monkeypatch.setattr(cli, "factories", Factories(settings=lambda: settings))
    result = invoke("fix", "--repo", REPO_URL, "--bug", "add is wrong", "--out", str(tmp_path))
    assert result.exit_code == 2
    assert "NEBIUS_API_KEY" in result.stderr


@pytest.mark.parametrize(
    ("label", "reason", "code"),
    [
        (OutcomeLabel.VERIFIED, StopReason.COMPLETED, 0),
        (OutcomeLabel.VERIFIED, StopReason.BUDGET_TIME, 0),
        (OutcomeLabel.NEEDS_REVIEW, StopReason.COMPLETED, 10),
        (OutcomeLabel.NOT_VERIFIED, StopReason.COMPLETED, 20),
        (OutcomeLabel.NOT_VERIFIED, StopReason.SERVICE_UNAVAILABLE, 20),
        (OutcomeLabel.NOT_VERIFIED, StopReason.USER_STOP, 30),
        (OutcomeLabel.NOT_VERIFIED, StopReason.BUDGET_COST, 30),
        (OutcomeLabel.NOT_VERIFIED, StopReason.SETUP_FAILED, 40),
        (OutcomeLabel.NOT_VERIFIED, StopReason.NOT_REPRODUCIBLE, 40),
        (OutcomeLabel.NOT_VERIFIED, StopReason.INTERNAL_ERROR, 1),
    ],
)
def test_exit_codes_follow_the_contract(label: OutcomeLabel, reason: StopReason, code: int) -> None:
    assert exit_code_for(label, reason) == code


def doctor_factories(settings: Settings, model: FakeModelClient | None = None) -> Factories:
    return Factories(
        settings=lambda: settings,
        model=lambda s: model or FakeModelClient(),
        executor=lambda s, on_event: FakeExecutor(),
    )


def test_doctor_names_the_missing_key_and_exits_6(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "factories", doctor_factories(make_settings(nebius_api_key=None)))
    result = invoke("doctor")
    assert result.exit_code == 6, result.output
    assert "FAIL NEBIUS_API_KEY: not set" in result.stdout
    assert "fix: Create a key at https://tokenfactory.nebius.com" in result.stdout


def test_doctor_passes_when_everything_is_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "factories", doctor_factories(make_settings()))
    result = invoke("doctor")
    assert result.exit_code == 0, result.output
    assert "FAIL" not in result.stdout


def test_doctor_flags_models_missing_from_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    only_worker = FakeModelClient(models=[DEFAULT_WORKER_MODEL.upper()])
    monkeypatch.setattr(cli, "factories", doctor_factories(make_settings(), only_worker))
    result = invoke("doctor", "--json")
    assert result.exit_code == 6
    checks = {c["name"]: c for c in json.loads(result.stdout)}
    assert checks["Model (worker)"]["ok"] is True  # IDs match case-insensitively
    assert checks["Model (planner)"]["ok"] is False
    assert "FIXPROOF_PLANNER_MODEL" in checks["Model (planner)"]["hint"]


def test_replay_labels_every_line(use_fakes: Install, tmp_path: Path) -> None:
    use_fakes()
    assert invoke(*FIX, "--out", str(tmp_path)).exit_code == 0
    [trace] = list(tmp_path.glob("*/trace.jsonl"))
    result = invoke("replay", str(trace), "--speed", "1000")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].startswith("REPLAY of a recorded run")
    assert any(line.startswith("[REPLAY] finished: verified") for line in lines)


def test_replay_of_a_missing_file_exits_2(tmp_path: Path) -> None:
    result = invoke("replay", str(tmp_path / "missing.jsonl"))
    assert result.exit_code == 2


def test_version() -> None:
    result = invoke("--version")
    assert result.exit_code == 0 and result.stdout.startswith("fixproof ")


def test_serve_refuses_dev_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = make_settings(executor="docker", state_dir=tmp_path)
    monkeypatch.setattr(cli, "factories", Factories(settings=lambda: settings))
    result = invoke("serve")
    assert result.exit_code == 2
    assert "FIXPROOF_EXECUTOR=docker" in result.stderr


def test_serve_starts_the_web_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import uvicorn

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    settings = make_settings(state_dir=tmp_path)
    monkeypatch.setattr(cli, "factories", Factories(settings=lambda: settings))
    result = invoke("serve", "--host", "127.0.0.1", "--port", "8123")
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "127.0.0.1", "port": 8123}]
