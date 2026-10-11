"""Contract test: the FastAPI app implements every operation of contracts/openapi.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from fixproof.web.app import create_app
from tests.fakes.web import make_manager

CONTRACT_FILE = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "001-verified-fix-agent"
    / "contracts"
    / "openapi.yaml"
)
CONTRACT: dict[str, Any] = yaml.safe_load(CONTRACT_FILE.read_text(encoding="utf-8"))
OPERATIONS = [
    (path, method, operation)
    for path, methods in CONTRACT["paths"].items()
    for method, operation in methods.items()
]


@pytest.fixture
def app_schema(tmp_path: Path) -> dict[str, Any]:
    manager, _ = make_manager(tmp_path)
    return create_app(manager=manager).openapi()


@pytest.mark.parametrize(
    ("path", "method", "operation"), OPERATIONS, ids=[op["operationId"] for *_, op in OPERATIONS]
)
def test_contract_operation_is_implemented(
    app_schema: dict[str, Any], path: str, method: str, operation: dict[str, Any]
) -> None:
    assert path in app_schema["paths"], path
    implemented = app_schema["paths"][path]
    assert method in implemented, f"{method.upper()} {path}"
    assert implemented[method]["operationId"] == operation["operationId"]
    missing = set(operation["responses"]) - set(implemented[method]["responses"])
    assert not missing, f"{operation['operationId']} does not document {sorted(missing)}"


def test_the_app_has_no_undocumented_api_operations(app_schema: dict[str, Any]) -> None:
    documented = {(path, method) for path, method, _ in OPERATIONS}
    implemented = {
        (path, method)
        for path, methods in app_schema["paths"].items()
        for method in methods
        if path.startswith("/api/")
    }
    assert implemented == documented


def test_the_contract_has_no_patch_or_pull_request_operations() -> None:
    """FR-016: the public demo never applies patches or opens pull requests."""
    for path, method, operation in OPERATIONS:
        text = f"{path} {operation['operationId']}".lower()
        assert "apply" not in text and "pull" not in text, (path, method)
