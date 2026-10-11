"""Default construction of the external services from settings (shared by the CLI and the web)."""

from __future__ import annotations

from fixproof.config import Settings
from fixproof.llm.client import ModelClient, TokenFactoryClient
from fixproof.repo.github import GitHubClient, RepoSource


def token_factory_client(settings: Settings) -> ModelClient:
    """Return the Nebius Token Factory model client.

    Raises:
        ConfigError: If ``NEBIUS_API_KEY`` is not set.
    """
    return TokenFactoryClient(settings)


def github_source(settings: Settings) -> RepoSource:
    """Return the GitHub intake client, with the optional read-only ``GITHUB_TOKEN``."""
    token = settings.github_token.get_secret_value() if settings.github_token else None
    return GitHubClient(token=token or None)
