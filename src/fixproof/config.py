"""Configuration loaded from environment variables or ``.env`` (Constitution I and VI).

Every model ID, endpoint, key, sampling parameter, and limit is configuration. Nothing is
hardcoded in the agent. ``.env.example`` documents each variable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from fixproof.models import Budget, ModelRole

TOKEN_FACTORY_URL = "https://api.tokenfactory.nebius.com/v1/"
SANDBOXES_URL = "https://api.tokenfactory.nebius.com/sandboxes"

DEFAULT_PLANNER_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"
DEFAULT_WORKER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_FALLBACK_MODEL = "nvidia/nvidia-nemotron-3-nano-30b-a3b"

# USD per 1M tokens (input, output), from the Nebius Nemotron pricing page (research.md R2).
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "nvidia/nemotron-3-ultra-550b-a55b": (1.00, 3.00),
    "nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
    "nvidia/nvidia-nemotron-3-nano-30b-a3b": (0.06, 0.24),
    "nvidia/nemotron-3_5-lightning": (0.06, 0.24),
}


class ConfigError(Exception):
    """Raised when a required setting is missing or invalid; the message names the variable."""


class Settings(BaseSettings):
    """All FixProof settings, read from the environment or a ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_by_name=True,
        validate_by_alias=True,
    )

    # Nebius Token Factory (inference)
    nebius_api_key: SecretStr | None = Field(default=None, validation_alias="NEBIUS_API_KEY")
    nebius_base_url: str = Field(default=TOKEN_FACTORY_URL, validation_alias="NEBIUS_BASE_URL")

    # NVIDIA Nemotron models by role
    planner_model: str = Field(
        default=DEFAULT_PLANNER_MODEL, validation_alias="FIXPROOF_PLANNER_MODEL"
    )
    worker_model: str = Field(
        default=DEFAULT_WORKER_MODEL, validation_alias="FIXPROOF_WORKER_MODEL"
    )
    fallback_model: str = Field(
        default=DEFAULT_FALLBACK_MODEL, validation_alias="FIXPROOF_FALLBACK_MODEL"
    )
    temperature: float = Field(default=0.3, ge=0.0, le=2.0, validation_alias="FIXPROOF_TEMPERATURE")
    top_p: float = Field(default=0.95, gt=0.0, le=1.0, validation_alias="FIXPROOF_TOP_P")
    max_tokens: int = Field(default=4096, ge=1, validation_alias="FIXPROOF_MAX_TOKENS")
    prices: dict[str, tuple[float, float]] = Field(
        default_factory=dict, validation_alias="FIXPROOF_PRICES"
    )

    # Token Factory Sandboxes (code execution)
    contree_url: str = Field(default=SANDBOXES_URL, validation_alias="CONTREE_URL")
    # contree-sdk itself reads the project from NEBIUS_PROJECT_ID, so both names are accepted.
    contree_project: str | None = Field(
        default=None, validation_alias=AliasChoices("CONTREE_PROJECT", "NEBIUS_PROJECT_ID")
    )
    contree_token: SecretStr | None = Field(default=None, validation_alias="CONTREE_TOKEN")
    executor: Literal["contree", "docker"] = Field(
        default="contree", validation_alias="FIXPROOF_EXECUTOR"
    )
    base_image: str = Field(default="python:3.12", validation_alias="FIXPROOF_BASE_IMAGE")

    # Optional services
    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")
    tavily_api_key: SecretStr | None = Field(default=None, validation_alias="TAVILY_API_KEY")
    web_search: bool = Field(default=False, validation_alias="FIXPROOF_WEB_SEARCH")

    # Dev and test switches
    allow_dev: bool = Field(default=False, validation_alias="FIXPROOF_ALLOW_DEV")
    live: bool = Field(default=False, validation_alias="FIXPROOF_LIVE")

    # Run storage and judge-demo limits
    state_dir: Path = Field(default=Path("runs"), validation_alias="FIXPROOF_STATE_DIR")
    demo_max_concurrent: int = Field(
        default=2, ge=1, validation_alias="FIXPROOF_DEMO_MAX_CONCURRENT"
    )
    demo_runs_per_visitor: int = Field(
        default=3, ge=1, validation_alias="FIXPROOF_DEMO_RUNS_PER_VISITOR"
    )
    demo_daily_cap_usd: float = Field(
        default=2.0, gt=0.0, validation_alias="FIXPROOF_DEMO_DAILY_CAP_USD"
    )
    demo_max_repo_mb: int = Field(default=50, ge=1, validation_alias="FIXPROOF_DEMO_MAX_REPO_MB")
    sandbox_cost_per_min_usd: float = Field(
        default=0.0, ge=0.0, validation_alias="FIXPROOF_SANDBOX_COST_PER_MIN_USD"
    )
    demo_url: str | None = Field(default=None, validation_alias="FIXPROOF_DEMO_URL")

    def require_api_key(self) -> str:
        """Return the Token Factory API key.

        Raises:
            ConfigError: If ``NEBIUS_API_KEY`` is not set.
        """
        value = _secret(self.nebius_api_key)
        if not value:
            raise ConfigError(
                "NEBIUS_API_KEY is not set. Create a key at https://tokenfactory.nebius.com "
                "(API keys) and add NEBIUS_API_KEY=... to your .env file."
            )
        return value

    def sandbox_token(self) -> str:
        """Return the Sandboxes token, falling back to ``NEBIUS_API_KEY``.

        Raises:
            ConfigError: If neither ``CONTREE_TOKEN`` nor ``NEBIUS_API_KEY`` is set.
        """
        value = _secret(self.contree_token) or _secret(self.nebius_api_key)
        if not value:
            raise ConfigError(
                "No sandbox credentials: set CONTREE_TOKEN, or NEBIUS_API_KEY if your Token "
                "Factory key also has Sandboxes access."
            )
        return value

    def require_sandbox_project(self) -> str:
        """Return the Sandboxes project ID.

        Raises:
            ConfigError: If neither ``CONTREE_PROJECT`` nor ``NEBIUS_PROJECT_ID`` is set.
        """
        if not self.contree_project:
            raise ConfigError(
                "CONTREE_PROJECT is not set. Copy your Sandboxes project ID from the Token "
                "Factory console into .env as CONTREE_PROJECT (or NEBIUS_PROJECT_ID); request "
                "access at https://tokenfactory.nebius.com/sandboxes/about."
            )
        return self.contree_project

    def is_dev_endpoint(self) -> bool:
        """Return whether the inference endpoint is NOT Nebius Token Factory (dev-only use)."""
        host = (urlparse(self.nebius_base_url).hostname or "").lower()
        is_token_factory = host.endswith(".nebius.com") and host.startswith("api.tokenfactory.")
        return not is_token_factory

    def secret_values(self) -> list[str]:
        """Return every non-empty secret value, for redaction in traces and logs."""
        candidates = (
            self.nebius_api_key,
            self.contree_token,
            self.github_token,
            self.tavily_api_key,
        )
        return [value for value in (_secret(c) for c in candidates) if value]

    def sampling(self) -> dict[str, float | int]:
        """Return the sampling parameters sent with every model call (Constitution VI)."""
        return {"temperature": self.temperature, "max_tokens": self.max_tokens, "top_p": self.top_p}

    def model_chain(self, role: ModelRole) -> list[str]:
        """Return the models to try for ``role``, in order, without duplicates.

        Args:
            role: The role whose primary model and fallbacks are requested.

        Returns:
            Model IDs: planner tries Ultra, Super, then Nano; worker tries Super, then Nano;
            condenser uses Nano.
        """
        chains = {
            ModelRole.PLANNER: [self.planner_model, self.worker_model, self.fallback_model],
            ModelRole.WORKER: [self.worker_model, self.fallback_model],
            ModelRole.CONDENSER: [self.fallback_model],
        }
        ordered: list[str] = []
        for model in chains[role]:
            if model not in ordered:
                ordered.append(model)
        return ordered

    def models_by_role(self) -> dict[str, str]:
        """Return the primary model ID for each role."""
        return {
            ModelRole.PLANNER.value: self.planner_model,
            ModelRole.WORKER.value: self.worker_model,
            ModelRole.CONDENSER.value: self.fallback_model,
        }

    def price_table(self) -> dict[str, tuple[float, float]]:
        """Return prices per 1M tokens keyed by lowercase model ID, with overrides applied."""
        table = dict(DEFAULT_PRICES)
        table.update({model.lower(): price for model, price in self.prices.items()})
        return table

    def budget_cli(self) -> Budget:
        """Default budget for CLI runs (plan.md: 40 steps, 15 minutes, $1.00)."""
        return Budget(max_steps=40, max_seconds=900, max_cost_usd=1.0, max_parallel=3)

    def budget_demo(self) -> Budget:
        """Default budget for public demo runs (plan.md: 30 steps, 10 minutes, $0.60)."""
        return Budget(max_steps=30, max_seconds=600, max_cost_usd=0.6, max_parallel=3)


def _secret(value: SecretStr | None) -> str:
    return value.get_secret_value() if value is not None else ""


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Load settings from the environment and, when present, ``env_file``.

    Args:
        env_file: Path of the dotenv file to read, or ``None`` to read the environment only.

    Returns:
        The validated settings.
    """
    return Settings(_env_file=env_file)
