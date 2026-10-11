from __future__ import annotations

import pytest

from fixproof.config import ConfigError, Settings
from fixproof.models import ModelRole

ENV_VARS = [
    "NEBIUS_API_KEY",
    "NEBIUS_BASE_URL",
    "FIXPROOF_PLANNER_MODEL",
    "FIXPROOF_WORKER_MODEL",
    "FIXPROOF_FALLBACK_MODEL",
    "FIXPROOF_TEMPERATURE",
    "FIXPROOF_TOP_P",
    "FIXPROOF_MAX_TOKENS",
    "FIXPROOF_PRICES",
    "CONTREE_URL",
    "CONTREE_PROJECT",
    "NEBIUS_PROJECT_ID",
    "CONTREE_TOKEN",
    "FIXPROOF_EXECUTOR",
    "FIXPROOF_BASE_IMAGE",
    "GITHUB_TOKEN",
    "TAVILY_API_KEY",
    "FIXPROOF_WEB_SEARCH",
    "FIXPROOF_ALLOW_DEV",
    "FIXPROOF_LIVE",
    "FIXPROOF_STATE_DIR",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def test_defaults_match_plan(clean_env: None) -> None:
    s = make()
    assert s.nebius_base_url == "https://api.tokenfactory.nebius.com/v1/"
    assert s.planner_model == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert s.worker_model == "nvidia/nemotron-3-super-120b-a12b"
    assert s.fallback_model == "nvidia/nvidia-nemotron-3-nano-30b-a3b"
    assert s.contree_url == "https://api.tokenfactory.nebius.com/sandboxes"
    assert s.executor == "contree"
    assert s.base_image == "python:3.12"
    assert s.web_search is False
    assert s.allow_dev is False

    cli = s.budget_cli()
    assert (cli.max_steps, cli.max_seconds, cli.max_cost_usd, cli.max_parallel) == (40, 900, 1.0, 3)
    demo = s.budget_demo()
    assert (demo.max_steps, demo.max_seconds, demo.max_cost_usd) == (30, 600, 0.6)

    sampling = s.sampling()
    assert set(sampling) == {"temperature", "max_tokens", "top_p"}


def test_env_overrides(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIXPROOF_WORKER_MODEL", "nvidia/Nemotron-3_5-Lightning")
    monkeypatch.setenv("FIXPROOF_TEMPERATURE", "0.1")
    monkeypatch.setenv("FIXPROOF_WEB_SEARCH", "1")
    s = make()
    assert s.worker_model == "nvidia/Nemotron-3_5-Lightning"
    assert s.temperature == pytest.approx(0.1)
    assert s.web_search is True


@pytest.mark.parametrize(
    ("url", "is_dev"),
    [
        ("https://api.tokenfactory.nebius.com/v1/", False),
        ("https://api.tokenfactory.us-central1.nebius.com/v1/", False),
        ("https://openrouter.ai/api/v1", True),
        ("http://localhost:8000/v1", True),
        ("https://nebius.com.evil.example/v1", True),
    ],
)
def test_is_dev_endpoint(clean_env: None, url: str, is_dev: bool) -> None:
    assert make(nebius_base_url=url).is_dev_endpoint() is is_dev


def test_secret_values_only_non_empty(clean_env: None) -> None:
    s = make(nebius_api_key="key-123456", github_token="", tavily_api_key="tvly-abcdef")
    assert sorted(s.secret_values()) == ["key-123456", "tvly-abcdef"]


def test_missing_api_key_names_the_variable(clean_env: None) -> None:
    with pytest.raises(ConfigError, match="NEBIUS_API_KEY"):
        make().require_api_key()


def test_sandbox_token_falls_back_to_nebius_key(clean_env: None) -> None:
    assert make(nebius_api_key="abc12345").sandbox_token() == "abc12345"
    assert make(nebius_api_key="abc12345", contree_token="tok98765").sandbox_token() == "tok98765"
    with pytest.raises(ConfigError, match="CONTREE_TOKEN"):
        make().sandbox_token()


def test_sandbox_project_accepts_the_sdk_variable_name(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ConfigError, match="CONTREE_PROJECT"):
        make().require_sandbox_project()
    monkeypatch.setenv("NEBIUS_PROJECT_ID", "project-from-sdk-name")
    assert make().require_sandbox_project() == "project-from-sdk-name"
    monkeypatch.setenv("CONTREE_PROJECT", "project-from-fixproof-name")
    assert make().require_sandbox_project() == "project-from-fixproof-name"


def test_model_chain_per_role(clean_env: None) -> None:
    s = make()
    assert s.model_chain(ModelRole.PLANNER) == [s.planner_model, s.worker_model, s.fallback_model]
    assert s.model_chain(ModelRole.WORKER) == [s.worker_model, s.fallback_model]
    assert s.model_chain(ModelRole.CONDENSER) == [s.fallback_model]


def test_price_table_merges_overrides_case_insensitively(clean_env: None) -> None:
    s = make(prices={"NVIDIA/Custom-Model": (1.5, 2.5)})
    table = s.price_table()
    assert table["nvidia/custom-model"] == (1.5, 2.5)
    assert table["nvidia/nemotron-3-super-120b-a12b"] == (0.30, 0.90)
