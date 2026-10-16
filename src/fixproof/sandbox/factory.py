"""Executor selection and the demo-safety guard (Constitution I, research R5).

Token Factory Sandboxes (``contree``) is the default. The Docker executor is for local
development only; the public demo and the video must never use it or a non-Nebius model
endpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fixproof.config import ConfigError, Settings
from fixproof.events import EventType
from fixproof.sandbox.contree import ContreeExecutor
from fixproof.sandbox.docker_dev import DockerExecutor
from fixproof.sandbox.executor import Executor

EventCallback = Callable[[EventType, dict[str, Any]], None]


def make_executor(settings: Settings, on_event: EventCallback | None = None) -> Executor:
    """Return the executor selected by ``FIXPROOF_EXECUTOR`` (``contree`` by default).

    Raises:
        ConfigError: If Sandboxes credentials or the project are missing.
    """
    if settings.executor == "docker":
        return DockerExecutor(on_event=on_event)
    return ContreeExecutor.from_settings(settings, on_event=on_event)


def assert_demo_safe(settings: Settings) -> None:
    """Refuse dev-only settings for the public demo unless ``FIXPROOF_ALLOW_DEV=1``.

    Raises:
        ConfigError: If the executor is not Token Factory Sandboxes or the model endpoint is
            not Nebius Token Factory.
    """
    if settings.allow_dev:
        return
    problems = []
    personal = settings.personal_provider()
    if personal is not None:
        problems.append(
            f"FIXPROOF_PROVIDER={personal.name} is personal mode ({personal.label}), not Nebius"
        )
    if settings.executor != "contree":
        problems.append(f"FIXPROOF_EXECUTOR={settings.executor} is for local development only")
    if settings.is_dev_endpoint():
        problems.append(f"NEBIUS_BASE_URL={settings.nebius_base_url} is not Nebius Token Factory")
    if problems:
        raise ConfigError(
            "The public demo must run on Token Factory Sandboxes and Nebius Token Factory: "
            + "; ".join(problems)
            + ". FIXPROOF_ALLOW_DEV=1 is only for local UI testing and must never be set for "
            "the public demo or the video."
        )
