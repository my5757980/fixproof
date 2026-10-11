"""Input models of the agent tools, exactly as in ``contracts/agent-tools.md``.

Each model forbids unknown fields, so the exported JSON Schema has
``additionalProperties: false``. The bounds here are the ones the model sees in the ``tools=``
parameter and the ones enforced before any tool runs (Constitution III).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from fixproof.models import Citation


class ToolArgs(BaseModel):
    """Base class of every tool input model: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class ListDirArgs(ToolArgs):
    """Arguments of ``list_dir``."""

    path: str = "."
    depth: int = Field(default=2, ge=1, le=4)


class ReadFileArgs(ToolArgs):
    """Arguments of ``read_file``."""

    path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=200, ge=1)


class SearchCodeArgs(ToolArgs):
    """Arguments of ``search_code``."""

    pattern: str = Field(min_length=1, max_length=200)
    path: str = "."
    glob: str = "*.py"
    max_results: int = Field(default=40, ge=1, le=100)


class CreateFileArgs(ToolArgs):
    """Arguments of ``create_file``."""

    path: str
    content: str = Field(max_length=50000)
    purpose: str = Field(max_length=200)


class EditFileArgs(ToolArgs):
    """Arguments of ``edit_file``."""

    path: str
    old_text: str = Field(min_length=1, max_length=20000)
    new_text: str = Field(max_length=20000)
    purpose: str = Field(max_length=200)


class RunTestsArgs(ToolArgs):
    """Arguments of ``run_tests``."""

    selector: str | None = Field(default=None, max_length=500)
    purpose: str = Field(default="", max_length=200)


class RunCommandArgs(ToolArgs):
    """Arguments of ``run_command``."""

    command: str = Field(max_length=1000)
    timeout_s: int = Field(default=120, ge=1, le=300)
    purpose: str = Field(max_length=200)


class WebSearchArgs(ToolArgs):
    """Arguments of ``web_search``."""

    query: str = Field(min_length=3, max_length=200)


class FinishArgs(ToolArgs):
    """Arguments of ``finish``: the worker's summary, root cause, and cited code."""

    summary: str = Field(max_length=1000)
    root_cause: str = Field(max_length=4000)
    citations: list[Citation] = Field(default_factory=list, max_length=10)
