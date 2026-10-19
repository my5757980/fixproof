"""The static showcase: the page, its assets, the showcase API answers, and the replay traces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fixproof.web.showcase import build_showcase

REPLAYS = Path(__file__).resolve().parents[2] / "replays"


async def test_the_showcase_is_a_static_copy_of_the_demo(tmp_path: Path) -> None:
    site = tmp_path / "site"
    files = await build_showcase(site, REPLAYS)
    assert {f.name for f in files} >= {
        "index.html",
        "README.md",
        "style.css",
        "app.js",
        "health.json",
        "samples.json",
        "replays.json",
    }
    page = (site / "index.html").read_text(encoding="utf-8")
    assert 'data-mode="static"' in page and "/static/" not in page
    health = json.loads((site / "health.json").read_text(encoding="utf-8"))
    assert health["live_runs_available"] is False and "showcase" in health["reason"]
    replays = json.loads((site / "replays.json").read_text(encoding="utf-8"))
    assert replays and all((site / f"{r['name']}.jsonl").is_file() for r in replays)
    assert "sdk: static" in (site / "README.md").read_text(encoding="utf-8")


async def test_the_showcase_needs_a_new_or_empty_folder(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty"):
        await build_showcase(tmp_path, REPLAYS)
    assert [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


async def test_the_showcase_needs_a_replay(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no replay"):
        await build_showcase(tmp_path / "site", tmp_path / "no-replays")
    assert not (tmp_path / "site").exists()
