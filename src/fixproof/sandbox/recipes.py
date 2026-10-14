"""Detect how to install a Python repository inside the sandbox (research.md R4, decision 5).

The recipe comes from files every Python project already has (``pyproject.toml``, ``setup.py``,
``requirements*.txt``). The orchestrator runs these commands, and asks the worker model for one
alternative command if installation fails.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from collections.abc import Callable, Sequence
from typing import Any

PIP = "python -m pip install --quiet --disable-pip-version-check"

_SPECIFIER = r"(?:===|==|!=|<=|>=|~=|<|>)[A-Za-z0-9.*+!_-]+"
_REQUIREMENT = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"  # name
    r"(?:\[[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*\])?"  # extras
    rf"(?:{_SPECIFIER}(?:,{_SPECIFIER})*)?"  # version specifiers
)

_RUNTIME_REQUIREMENTS = ("requirements.txt",)
_TEST_REQUIREMENTS = (
    "requirements-dev.txt",
    "requirements_dev.txt",
    "requirements-test.txt",
    "requirements_test.txt",
    "requirements-tests.txt",
    "test-requirements.txt",
    "dev-requirements.txt",
    "requirements/dev.txt",
    "requirements/test.txt",
    "requirements/tests.txt",
    "requirements/testing.txt",
)
_TEST_EXTRAS = ("test", "tests", "testing", "dev")


def detect_install_commands(paths: Sequence[str], read: Callable[[str], str]) -> list[str]:
    """Return the shell commands that install a repository and pytest, in order.

    The order is: runtime requirements, then the project itself (editable, with a test extra
    when one exists), then test or dev requirements, then ``pytest``.

    Args:
        paths: Repository file paths relative to the repository root.
        read: Function returning the text content of one of ``paths``.

    Returns:
        Install commands; always ends with installing ``pytest``.
    """
    present = {path.replace("\\", "/").removeprefix("./") for path in paths}
    commands = [
        f"{PIP} -r {shlex.quote(path)}" for path in _RUNTIME_REQUIREMENTS if path in present
    ]

    project_command = _project_install(present, read)
    if project_command:
        commands.append(project_command)

    commands.extend(
        f"{PIP} -r {shlex.quote(path)}" for path in _TEST_REQUIREMENTS if path in present
    )
    commands.append(f"{PIP} pytest")
    return commands


def pin_command(packages: Sequence[str]) -> str:
    """Return the command that installs pinned packages after the recipe.

    Benchmark tasks on old commits use pins the way SWE-bench's environments do, because newer
    releases of a dependency can break an old revision (for example ``MarkupSafe==2.0.1``).

    Args:
        packages: Plain requirements: a name, optional extras, and optional version specifiers.

    Returns:
        One ``pip install`` command with every requirement shell-quoted.

    Raises:
        ValueError: If a package is anything else (options, URLs, markers, shell syntax).
    """
    invalid = [package for package in packages if not _REQUIREMENT.fullmatch(package)]
    if invalid or not packages:
        raise ValueError(f"not a package requirement: {', '.join(map(repr, invalid))}")
    return f"{PIP} " + " ".join(shlex.quote(package) for package in packages)


def _project_install(present: set[str], read: Callable[[str], str]) -> str | None:
    has_setup = "setup.py" in present or "setup.cfg" in present
    if "pyproject.toml" not in present:
        return f"{PIP} -e ." if has_setup else None
    try:
        data: dict[str, Any] = tomllib.loads(read("pyproject.toml"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return f"{PIP} -e ."
    project = data.get("project")
    is_package = isinstance(project, dict) or "build-system" in data or has_setup
    if not is_package:
        return None
    extras = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
    for extra in _TEST_EXTRAS:
        if isinstance(extras, dict) and extra in extras:
            return f'{PIP} -e ".[{extra}]"'
    return f"{PIP} -e ."
