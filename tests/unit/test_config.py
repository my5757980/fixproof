from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import AliasChoices

from fixproof.config import ConfigError, Settings
from fixproof.models import ModelRole

ROOT = Path(__file__).resolve().parents[2]

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
    "FIXPROOF_PROVIDER",
    "NVIDIA_API_KEY",
    "OPENROUTER_API_KEY",
]
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/"
OPENROUTER_URL = "https://openrouter.ai/api/v1/"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def test_defaults_match_plan(clean_env: None) -> None:
    s = make()
    assert s.provider == "nebius" and not s.is_personal_mode()
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


# -- personal mode (FR-024, constitution 2.1.0) ------------------------------------------------


def test_personal_mode_switches_the_endpoint_and_models(clean_env: None) -> None:
    s = make(provider="nvidia")
    assert s.is_personal_mode()
    assert s.nebius_base_url == NVIDIA_URL
    assert s.planner_model == "nvidia/nemotron-3-ultra-550b-a55b"
    assert s.worker_model == "nvidia/nemotron-3-super-120b-a12b"
    assert s.fallback_model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert not s.is_dev_endpoint()


def test_personal_mode_keeps_values_set_explicitly(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FIXPROOF_PROVIDER", "nvidia")
    monkeypatch.setenv("FIXPROOF_WORKER_MODEL", "nvidia/some-other-model")
    s = make()
    assert s.worker_model == "nvidia/some-other-model"
    assert s.planner_model == "nvidia/nemotron-3-ultra-550b-a55b"
    custom = make(provider="nvidia", nebius_base_url="https://example.com/v1/")
    assert custom.nebius_base_url == "https://example.com/v1/" and custom.is_dev_endpoint()


def test_the_nvidia_host_counts_only_in_personal_mode(clean_env: None) -> None:
    assert make(nebius_base_url=NVIDIA_URL).is_dev_endpoint()
    assert not make(provider="nvidia", nebius_base_url=NVIDIA_URL).is_dev_endpoint()


def test_personal_mode_uses_the_nvidia_key(clean_env: None) -> None:
    with pytest.raises(ConfigError, match=r"NVIDIA_API_KEY.*build\.nvidia\.com"):
        make(provider="nvidia", nebius_api_key="nk-other-123456").require_api_key()
    s = make(provider="nvidia", nvidia_api_key="nvapi-test-123456")
    assert s.require_api_key() == "nvapi-test-123456"
    assert "nvapi-test-123456" in s.secret_values()


def test_personal_mode_prices_its_models_at_zero(clean_env: None) -> None:
    table = make(provider="nvidia").price_table()
    for model in ("nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-super-120b-a12b"):
        assert table[model] == (0.0, 0.0)
    assert make().price_table()["nvidia/nemotron-3-super-120b-a12b"] == (0.30, 0.90)
    assert make(provider="nvidia", prices={"x/y": (1.0, 2.0)}).price_table()["x/y"] == (1.0, 2.0)
    other = make(provider="nvidia", worker_model="nvidia/Other-Model")
    assert other.price_table()["nvidia/other-model"] == (0.0, 0.0)


def test_unknown_providers_are_rejected(clean_env: None) -> None:
    with pytest.raises(ValueError, match="(?i)provider"):
        make(provider="acme")


# -- personal mode through OpenRouter (constitution 2.2.0) -----------------------------------


def test_openrouter_switches_to_the_free_nemotron_models(clean_env: None) -> None:
    s = make(provider="openrouter")
    assert s.is_personal_mode() and s.nebius_base_url == OPENROUTER_URL
    assert s.planner_model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert s.worker_model == "nvidia/nemotron-3-super-120b-a12b:free"
    assert s.fallback_model == "nvidia/nemotron-3.5-lightning:free"
    assert not s.is_dev_endpoint()
    assert make(provider="openrouter", nebius_base_url=NVIDIA_URL).is_dev_endpoint()
    assert make(nebius_base_url=OPENROUTER_URL).is_dev_endpoint()


def test_openrouter_uses_its_own_key(clean_env: None) -> None:
    with pytest.raises(ConfigError, match=r"OPENROUTER_API_KEY.*openrouter\.ai/settings/keys"):
        make(provider="openrouter", nvidia_api_key="nvapi-other-123456").require_api_key()
    s = make(provider="openrouter", openrouter_api_key="sk-or-v1-test-123456")
    assert s.require_api_key() == "sk-or-v1-test-123456" and s.api_key() == "sk-or-v1-test-123456"
    assert s.api_key_variable() == "OPENROUTER_API_KEY"
    assert "sk-or-v1-test-123456" in s.secret_values()


def test_openrouter_prices_only_free_variants_at_zero(clean_env: None) -> None:
    table = make(provider="openrouter").price_table()
    assert table["nvidia/nemotron-3-super-120b-a12b:free"] == (0.0, 0.0)
    assert table["nvidia/nemotron-3.5-lightning:free"] == (0.0, 0.0)
    billed = make(provider="openrouter", worker_model="nvidia/nemotron-3-super-120b-a12b")
    assert "nvidia/nemotron-3-super-120b-a12b" not in billed.price_table()
    priced = make(
        provider="openrouter",
        worker_model="nvidia/nemotron-3-super-120b-a12b",
        prices={"nvidia/nemotron-3-super-120b-a12b": (0.08, 0.45)},
    )
    assert priced.price_table()["nvidia/nemotron-3-super-120b-a12b"] == (0.08, 0.45)


def test_openrouter_is_labelled_as_personal_mode(clean_env: None) -> None:
    note = make(provider="openrouter", executor="docker").platform_note()
    assert note is not None and "not the hackathon platform" in note.lower()
    assert "OpenRouter (personal mode)" in note and "local Docker" in note


def test_the_env_examples_cover_every_setting(clean_env: None) -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for field in Settings.model_fields.values():
        aliases = field.validation_alias
        names = aliases.choices if isinstance(aliases, AliasChoices) else [aliases]
        assert any(f"{name}=" in text for name in names), names


def test_the_personal_env_example_selects_personal_mode(clean_env: None) -> None:
    s = Settings(_env_file=ROOT / ".env.personal.example")  # type: ignore[call-arg]
    assert s.is_personal_mode() and s.executor == "docker"
    assert s.nebius_base_url == NVIDIA_URL and not s.is_dev_endpoint()
    assert s.worker_model == "nvidia/nemotron-3-super-120b-a12b"


def test_platform_note_labels_everything_but_the_hackathon_platform(clean_env: None) -> None:
    assert make().platform_note() is None
    personal = make(provider="nvidia", executor="docker").platform_note()
    assert personal is not None and "not the hackathon platform" in personal.lower()
    assert "NVIDIA" in personal and "local Docker" in personal
    docker_dev = make(executor="docker").platform_note()
    assert docker_dev is not None and "Nebius Token Factory" in docker_dev
