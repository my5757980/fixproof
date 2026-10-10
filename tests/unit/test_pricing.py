from __future__ import annotations

import pytest

from fixproof.llm.pricing import PriceTable, UnknownModelPriceError


def test_cost_is_case_insensitive() -> None:
    table = PriceTable({"nvidia/Nemotron-3-Ultra-550b-a55b": (1.0, 3.0)})
    cost = table.cost_usd("nvidia/nemotron-3-ultra-550b-a55b", 1_000_000, 500_000)
    assert cost == pytest.approx(2.5)
    assert "NVIDIA/NEMOTRON-3-ULTRA-550B-A55B" in table


def test_unknown_model_names_the_setting() -> None:
    with pytest.raises(UnknownModelPriceError, match="FIXPROOF_PRICES"):
        PriceTable({}).cost_usd("nvidia/unknown", 1, 1)
