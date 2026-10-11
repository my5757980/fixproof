"""Settings for offline tests: fake keys, never read from ``.env``."""

from __future__ import annotations

from typing import Any

from fixproof.config import Settings


def make_settings(**overrides: Any) -> Settings:
    """Return settings with fake credentials; ``overrides`` use field names."""
    values: dict[str, Any] = {
        "nebius_api_key": "nk-test-key-0001",
        "contree_project": "project-test",
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]
