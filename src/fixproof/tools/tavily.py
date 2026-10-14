"""Optional web search through Tavily (FR-022, research.md R12).

Off by default: the ``web_search`` tool exists only when ``FIXPROOF_WEB_SEARCH=1`` and
``TAVILY_API_KEY`` are set. Only a short, whitespace-normalized query is sent, never file
contents, and a query that contains a secret is refused before any request is made.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from fixproof.trace import Redactor

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_QUERY_CHARS = 200
MAX_RESULTS = 5
SNIPPET_CHARS = 500


class TavilySearch:
    """The ``WebSearch`` backend: Tavily search with ``search_depth: basic`` (1 credit per call).

    Args:
        api_key: The Tavily API key.
        secrets: Values that must never leave the machine inside a query.
        http: HTTP client to use (tests pass one with a mock transport).
        timeout_s: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        *,
        secrets: Iterable[str] = (),
        http: httpx.AsyncClient | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._redactor = Redactor([api_key, *secrets])
        self._http = http or httpx.AsyncClient(timeout=timeout_s)

    async def __call__(self, query: str) -> list[dict[str, str]]:
        """Search for ``query`` and return up to five ``{title, url, snippet}`` results.

        Raises:
            ValueError: If the query contains a secret, or the reply has an unexpected shape.
            httpx.HTTPError: If the request fails or Tavily answers with an error status.
        """
        text = " ".join(query.split())[:MAX_QUERY_CHARS]
        if self._redactor.redact_text(text) != text:
            raise ValueError("The query contains a secret, so it was not sent.")
        response = await self._http.post(
            TAVILY_SEARCH_URL,
            json={"query": text, "max_results": MAX_RESULTS, "search_depth": "basic"},
            headers=self._headers,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ValueError("Unexpected reply from Tavily.")
        return [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": _clip(" ".join(str(item.get("content") or "").split())),
            }
            for item in results[:MAX_RESULTS]
            if isinstance(item, dict)
        ]

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()


def _clip(text: str) -> str:
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1] + "…"
