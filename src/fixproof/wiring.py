"""Default construction of the external services from settings (shared by the CLI and the web)."""

from __future__ import annotations

from fixproof.config import Settings
from fixproof.llm.client import ModelClient, TokenFactoryClient
from fixproof.repo.github import GitHubClient, RepoSource
from fixproof.tools.registry import web_search_enabled
from fixproof.tools.tavily import TavilySearch


def token_factory_client(settings: Settings) -> ModelClient:
    """Return the Nebius Token Factory model client.

    Raises:
        ConfigError: If ``NEBIUS_API_KEY`` is not set.
    """
    return TokenFactoryClient(settings)


def github_client(settings: Settings) -> GitHubClient:
    """Return a GitHub client with ``GITHUB_TOKEN`` when it is set."""
    token = settings.github_token.get_secret_value() if settings.github_token else None
    return GitHubClient(token=token or None)


def github_source(settings: Settings) -> RepoSource:
    """Return the GitHub intake client, with the optional read-only ``GITHUB_TOKEN``."""
    return github_client(settings)


def web_search_backend(settings: Settings) -> TavilySearch | None:
    """Return the Tavily search backend when web search is enabled (FR-022), else ``None``."""
    if not web_search_enabled(settings) or settings.tavily_api_key is None:
        return None
    return TavilySearch(
        settings.tavily_api_key.get_secret_value(), secrets=settings.secret_values()
    )
