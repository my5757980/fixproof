"""Executor selection and the demo-safety guard."""

from __future__ import annotations

import pytest

from fixproof.config import ConfigError
from fixproof.sandbox.contree import ContreeExecutor
from fixproof.sandbox.docker_dev import DockerExecutor
from fixproof.sandbox.factory import assert_demo_safe, make_executor
from tests.fakes.settings import make_settings


def test_contree_is_the_default_executor() -> None:
    assert isinstance(make_executor(make_settings()), ContreeExecutor)


def test_contree_requires_a_project() -> None:
    with pytest.raises(ConfigError, match="CONTREE_PROJECT"):
        make_executor(make_settings(contree_project=None))


def test_docker_is_opt_in(capsys: pytest.CaptureFixture[str]) -> None:
    assert isinstance(make_executor(make_settings(executor="docker")), DockerExecutor)
    assert "DEV ONLY" in capsys.readouterr().err


def test_demo_accepts_only_nebius_settings() -> None:
    assert_demo_safe(make_settings())
    with pytest.raises(ConfigError, match="FIXPROOF_EXECUTOR=docker"):
        assert_demo_safe(make_settings(executor="docker"))
    with pytest.raises(ConfigError, match="NEBIUS_BASE_URL"):
        assert_demo_safe(make_settings(nebius_base_url="https://example.com/v1/"))
    assert_demo_safe(make_settings(executor="docker", allow_dev=True))


def test_demo_refuses_personal_mode() -> None:
    with pytest.raises(ConfigError, match="FIXPROOF_PROVIDER=nvidia"):
        assert_demo_safe(make_settings(provider="nvidia"))
    assert_demo_safe(make_settings(provider="nvidia", allow_dev=True))
