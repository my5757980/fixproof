from __future__ import annotations

from collections.abc import Callable

from fixproof.sandbox.recipes import PIP, detect_install_commands


def reader(files: dict[str, str]) -> Callable[[str], str]:
    return lambda path: files[path]


def detect(files: dict[str, str]) -> list[str]:
    return detect_install_commands(list(files), reader(files))


PYPROJECT_WITH_TEST_EXTRA = """
[project]
name = "demo"
version = "1.0"
[project.optional-dependencies]
docs = ["sphinx"]
test = ["pytest", "hypothesis"]
"""

PYPROJECT_NO_EXTRAS = """
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
[project]
name = "demo"
version = "1.0"
"""

PYPROJECT_TOOLS_ONLY = """
[tool.black]
line-length = 88
"""


def test_pyproject_with_test_extra() -> None:
    commands = detect({"pyproject.toml": PYPROJECT_WITH_TEST_EXTRA})
    assert f'{PIP} -e ".[test]"' in commands
    assert commands[-1] == f"{PIP} pytest"


def test_pyproject_prefers_test_extra_over_dev() -> None:
    content = PYPROJECT_WITH_TEST_EXTRA.replace("docs = ", "dev = ")
    assert f'{PIP} -e ".[test]"' in detect({"pyproject.toml": content})


def test_pyproject_without_extras() -> None:
    commands = detect({"pyproject.toml": PYPROJECT_NO_EXTRAS})
    assert f"{PIP} -e ." in commands


def test_tool_only_pyproject_without_setup_py_is_not_installed() -> None:
    assert detect({"pyproject.toml": PYPROJECT_TOOLS_ONLY}) == [f"{PIP} pytest"]


def test_tool_only_pyproject_with_setup_py_installs_editable() -> None:
    commands = detect(
        {"pyproject.toml": PYPROJECT_TOOLS_ONLY, "setup.py": "from setuptools import setup"}
    )
    assert f"{PIP} -e ." in commands


def test_setup_py_only() -> None:
    assert detect({"setup.py": "from setuptools import setup\nsetup()"}) == [
        f"{PIP} -e .",
        f"{PIP} pytest",
    ]


def test_requirements_runtime_and_dev() -> None:
    commands = detect({"requirements.txt": "requests", "requirements-dev.txt": "pytest"})
    assert commands == [
        f"{PIP} -r requirements.txt",
        f"{PIP} -r requirements-dev.txt",
        f"{PIP} pytest",
    ]


def test_order_runtime_then_project_then_test_requirements() -> None:
    commands = detect(
        {
            "requirements.txt": "x",
            "pyproject.toml": PYPROJECT_NO_EXTRAS,
            "requirements/test.txt": "pytest",
        }
    )
    assert commands == [
        f"{PIP} -r requirements.txt",
        f"{PIP} -e .",
        f"{PIP} -r requirements/test.txt",
        f"{PIP} pytest",
    ]


def test_invalid_pyproject_falls_back_to_editable_install() -> None:
    assert f"{PIP} -e ." in detect({"pyproject.toml": "[project\nname="})


def test_empty_repository_installs_only_pytest() -> None:
    assert detect({}) == [f"{PIP} pytest"]
