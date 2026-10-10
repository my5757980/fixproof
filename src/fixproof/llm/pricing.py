"""Cost of model calls from token usage (research.md R2).

Prices are USD per 1M tokens and come from configuration (``Settings.price_table``). Model IDs
are matched case-insensitively because published IDs differ in casing.
"""

from __future__ import annotations

from collections.abc import Mapping

_PER_TOKENS = 1_000_000


class UnknownModelPriceError(KeyError):
    """Raised when no price is configured for a model."""


class PriceTable:
    """Compute the cost of a call from its token usage.

    Args:
        prices: Mapping of model ID to ``(input, output)`` USD per 1M tokens.
    """

    def __init__(self, prices: Mapping[str, tuple[float, float]]) -> None:
        self._prices = {model.lower(): price for model, price in prices.items()}

    def cost_usd(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Return the cost of one call.

        Args:
            model: Model ID that served the call.
            prompt_tokens: Billed input tokens.
            completion_tokens: Billed output tokens.

        Returns:
            Cost in USD.

        Raises:
            UnknownModelPriceError: If the model has no configured price.
        """
        price = self._prices.get(model.lower())
        if price is None:
            raise UnknownModelPriceError(
                f"no price configured for model {model!r}; add it to FIXPROOF_PRICES as "
                f'{{"{model}": [input_usd_per_1m, output_usd_per_1m]}}'
            )
        input_price, output_price = price
        return (prompt_tokens * input_price + completion_tokens * output_price) / _PER_TOKENS

    def __contains__(self, model: object) -> bool:
        """Whether a price is configured for ``model``."""
        return isinstance(model, str) and model.lower() in self._prices
