"""Configuration loaded from environment variables or ``.env`` (Constitution I and VI).

Every model ID, endpoint, key, sampling parameter, and limit is configuration. Nothing is
hardcoded in the agent. ``.env.example`` documents each variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr, model_validator
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

# Personal mode (FR-024, constitution 2.1.0): NVIDIA's own OpenAI-compatible API. The model IDs
# follow third-party documentation of that API; `fixproof doctor` checks them against the
# endpoint's model list. NVIDIA's API is free to use for these models (no per-token charge).
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/"
NVIDIA_PLANNER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
NVIDIA_WORKER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
NVIDIA_FALLBACK_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
NVIDIA_PRICES: dict[str, tuple[float, float]] = {
    model: (0.0, 0.0)
    for model in (NVIDIA_PLANNER_MODEL, NVIDIA_WORKER_MODEL, NVIDIA_FALLBACK_MODEL)
}

# Personal mode through OpenRouter (constitution 2.2.0): the same NVIDIA Nemotron models as free
# ":free" variants, listed by https://openrouter.ai/api/v1/models on 2026-10-15. Free variants
# have request limits per day; any other OpenRouter model is billed and needs FIXPROOF_PRICES.
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/"
OPENROUTER_PLANNER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENROUTER_WORKER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_FALLBACK_MODEL = "nvidia/nemotron-3.5-lightning:free"
_FREE_SUFFIX = ":free"

# Personal mode through Requesty (constitution 2.3.0): the same NVIDIA Nemotron IDs as NVIDIA's
# API, listed at $0 with tool calling by https://router.requesty.ai/v1/models on 2026-10-17. Any
# other Requesty model is billed and needs FIXPROOF_PRICES.
REQUESTY_API_URL = "https://router.requesty.ai/v1/"
REQUESTY_PRICES: dict[str, tuple[float, float]] = dict(NVIDIA_PRICES)


@dataclass(frozen=True)
class PersonalProvider:
    """A personal-mode model provider: its endpoint, key, and NVIDIA Nemotron model IDs."""

    name: str
    label: str
    base_url: str
    key_variable: str
    key_page: str
    planner_model: str
    worker_model: str
    fallback_model: str


PERSONAL_PROVIDERS = {
    "nvidia": PersonalProvider(
        name="nvidia",
        label="NVIDIA's API",
        base_url=NVIDIA_API_URL,
        key_variable="NVIDIA_API_KEY",
        key_page="https://build.nvidia.com/settings/api-keys",
        planner_model=NVIDIA_PLANNER_MODEL,
        worker_model=NVIDIA_WORKER_MODEL,
        fallback_model=NVIDIA_FALLBACK_MODEL,
    ),
    "openrouter": PersonalProvider(
        name="openrouter",
        label="OpenRouter",
        base_url=OPENROUTER_API_URL,
        key_variable="OPENROUTER_API_KEY",
        key_page="https://openrouter.ai/settings/keys",
        planner_model=OPENROUTER_PLANNER_MODEL,
        worker_model=OPENROUTER_WORKER_MODEL,
        fallback_model=OPENROUTER_FALLBACK_MODEL,
    ),
    "requesty": PersonalProvider(
        name="requesty",
        label="Requesty",
        base_url=REQUESTY_API_URL,
        key_variable="REQUESTY_API_KEY",
        key_page="https://app.requesty.ai/api-keys",
        planner_model=NVIDIA_PLANNER_MODEL,
        worker_model=NVIDIA_WORKER_MODEL,
        fallback_model=NVIDIA_FALLBACK_MODEL,
    ),
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

    # Model provider: nebius (the hackathon configuration), or nvidia, openrouter, or requesty
    # (personal mode, FR-024)
    provider: Literal["nebius", "nvidia", "openrouter", "requesty"] = Field(
        default="nebius", validation_alias="FIXPROOF_PROVIDER"
    )
    nvidia_api_key: SecretStr | None = Field(default=None, validation_alias="NVIDIA_API_KEY")
    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    requesty_api_key: SecretStr | None = Field(default=None, validation_alias="REQUESTY_API_KEY")

    # Nebius Token Factory (inference). In personal mode the base URL defaults to the provider's.
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

    @model_validator(mode="after")
    def _apply_provider_defaults(self) -> Settings:
        """In personal mode, default the endpoint and models to the provider's.

        Values set explicitly (in the environment, ``.env``, or by name) always win.
        """
        personal = self.personal_provider()
        if personal is not None:
            defaults = {
                "nebius_base_url": personal.base_url,
                "planner_model": personal.planner_model,
                "worker_model": personal.worker_model,
                "fallback_model": personal.fallback_model,
            }
            for name, value in defaults.items():
                if name not in self.model_fields_set:
                    setattr(self, name, value)
        return self

    def personal_provider(self) -> PersonalProvider | None:
        """Return the personal-mode provider (FR-024), or ``None`` for Nebius Token Factory."""
        return PERSONAL_PROVIDERS.get(self.provider)

    def is_personal_mode(self) -> bool:
        """Return whether personal mode (NVIDIA's API, OpenRouter, or Requesty) is selected."""
        return self.personal_provider() is not None

    def api_key_variable(self) -> str:
        """Return the name of the variable that holds the model API key."""
        personal = self.personal_provider()
        return personal.key_variable if personal is not None else "NEBIUS_API_KEY"

    def api_key_page(self) -> str:
        """Return the page where the model API key is created."""
        personal = self.personal_provider()
        return personal.key_page if personal is not None else "https://tokenfactory.nebius.com"

    def api_key(self) -> str:
        """Return the model API key of the selected provider, or ``""`` if it is not set."""
        keys = {
            "nebius": self.nebius_api_key,
            "nvidia": self.nvidia_api_key,
            "openrouter": self.openrouter_api_key,
            "requesty": self.requesty_api_key,
        }
        return _secret(keys[self.provider])

    def require_api_key(self) -> str:
        """Return the model API key: Token Factory's, or the personal-mode provider's.

        Raises:
            ConfigError: If the key is not set; the message names the variable to set.
        """
        personal = self.personal_provider()
        if personal is not None:
            value = self.api_key()
            if not value:
                raise ConfigError(
                    f"{personal.key_variable} is not set. Create a key at {personal.key_page} "
                    f"and add {personal.key_variable}=... to your .env file (personal mode)."
                )
            return value
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
        """Return whether the endpoint is not the selected provider's own (dev-only use).

        The provider's own endpoint is Nebius Token Factory, or in personal mode NVIDIA's API,
        OpenRouter, or Requesty.
        """
        host = (urlparse(self.nebius_base_url).hostname or "").lower()
        personal = self.personal_provider()
        if personal is not None:
            return host != urlparse(personal.base_url).hostname
        is_token_factory = host.endswith(".nebius.com") and host.startswith("api.tokenfactory.")
        return not is_token_factory

    def platform_note(self) -> str | None:
        """Return a label for setups that are not the hackathon platform, else ``None``.

        The hackathon platform is Nebius Token Factory with Token Factory Sandboxes.
        """
        on_platform = not (
            self.is_personal_mode() or self.is_dev_endpoint() or self.executor != "contree"
        )
        if on_platform:
            return None
        personal = self.personal_provider()
        if personal is not None and not self.is_dev_endpoint():
            models = f"{personal.label} (personal mode)"
        elif self.is_dev_endpoint():
            models = f"a development endpoint ({self.nebius_base_url})"
        else:
            models = "Nebius Token Factory"
        code = "Token Factory Sandboxes" if self.executor == "contree" else "local Docker"
        return f"Not the hackathon platform: models from {models}, code run in {code}."

    def secret_values(self) -> list[str]:
        """Return every non-empty secret value, for redaction in traces and logs."""
        candidates = (
            self.nebius_api_key,
            self.nvidia_api_key,
            self.openrouter_api_key,
            self.requesty_api_key,
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
        """Return prices per 1M tokens keyed by lowercase model ID, with overrides applied.

        The defaults are the provider's: Token Factory prices; $0 for NVIDIA's API (also for any
        other model configured for a role); on OpenRouter, $0 for the free ``:free`` variants
        only; on Requesty, $0 for the three NVIDIA models it lists at $0 only. A billed model
        needs a price in ``FIXPROOF_PRICES``.
        """
        roles = (self.planner_model, self.worker_model, self.fallback_model)
        if self.provider == "nvidia":
            table = dict(NVIDIA_PRICES)
            table.update({model.lower(): (0.0, 0.0) for model in roles})
        elif self.provider == "openrouter":
            free = (model for model in roles if model.lower().endswith(_FREE_SUFFIX))
            table = {model.lower(): (0.0, 0.0) for model in free}
        elif self.provider == "requesty":
            table = dict(REQUESTY_PRICES)
        else:
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
