"""Async REST client for the Sukoon data API — spec §7.

Maps onto these endpoints (verified against ``minto-data-api/mcp/src``):

  GET /v1/funds/{scheme_code}/nav?from=YYYY-MM-DD&to=YYYY-MM-DD
  GET /v1/funds/{scheme_code}
  GET /v1/funds?q=&amc=&type=&page=&pageSize=
  GET /v1/benchmarks/{url_encoded_index_name}?from=&to=

Auth: none required. Default base URL is ``https://api.minto.app`` and is
overridable via the ``MINTO_API_URL`` env var (matches the MCP convention).
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Final, Self
from urllib.parse import quote

import httpx
import polars as pl
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from sukoon_bt import __version__
from sukoon_bt.data.models import Fund

DEFAULT_BASE_URL: Final[str] = "https://api.minto.app"
USER_AGENT: Final[str] = f"sukoon-bt/{__version__}"


class SukoonAPIError(RuntimeError):
    """Raised when the Sukoon API returns an unexpected response."""


class SukoonDataClient:
    """Thin async wrapper over the Sukoon REST API.

    The client is connection-pooled and intended to be reused across calls.
    Use as an async context manager so the underlying httpx client is closed
    deterministically::

        async with SukoonDataClient() as client:
            navs = await client.get_nav_history("120503", start, end)
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or os.getenv("MINTO_API_URL", DEFAULT_BASE_URL)).rstrip("/")
        self._max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ----- public API ---------------------------------------------------

    async def get_nav_history(self, fund_id: str, start: date, end: date) -> pl.DataFrame:
        """Daily NAV time series for a fund as a polars DataFrame.

        Schema: ``{date: pl.Date, nav: pl.Float64}`` sorted ascending.
        """
        rows = await self._get_json(
            f"/v1/funds/{quote(fund_id, safe='')}/nav",
            params={"from": start.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(rows, list):
            raise SukoonAPIError(f"expected array NAV response, got {type(rows).__name__}")
        return _nav_to_df(rows)

    async def get_fund_metadata(self, fund_id: str) -> Fund:
        """Single-fund metadata."""
        payload = await self._get_json(f"/v1/funds/{quote(fund_id, safe='')}")
        if not isinstance(payload, dict):
            raise SukoonAPIError(f"expected object fund response, got {type(payload).__name__}")
        return _fund_from_payload(payload)

    async def search_funds(
        self,
        *,
        query: str | None = None,
        amc: str | None = None,
        category: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Fund]:
        """Filter funds by free text + AMC + category. Single page per call."""
        params: dict[str, str | int] = {"page": page, "pageSize": page_size}
        if query is not None:
            params["q"] = query
        if amc is not None:
            params["amc"] = amc
        if category is not None:
            params["type"] = category
        payload = await self._get_json("/v1/funds", params=params)
        if not isinstance(payload, dict) or "funds" not in payload:
            raise SukoonAPIError("expected wrapped {funds, total, ...} search response")
        return [_fund_from_payload(item) for item in payload["funds"]]

    async def get_benchmark_history(
        self,
        benchmark_id: str,
        start: date,
        end: date,
    ) -> pl.DataFrame:
        """Daily TRI series for a NIFTY index by name (e.g. ``"NIFTY 500"``).

        Schema: ``{date: pl.Date, tri_value: pl.Float64}`` sorted ascending.
        """
        payload = await self._get_json(
            f"/v1/benchmarks/{quote(benchmark_id, safe='')}",
            params={"from": start.isoformat(), "to": end.isoformat()},
        )
        if not isinstance(payload, dict) or "data" not in payload:
            raise SukoonAPIError("expected wrapped {index, data} benchmark response")
        return _benchmark_to_df(payload["data"])

    # ----- internals ----------------------------------------------------

    async def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                resp = await self._client.get(path, params=params)
                if resp.status_code >= 500:
                    resp.raise_for_status()  # triggers retry
                if resp.status_code == 429:
                    raise httpx.HTTPStatusError(
                        "rate limited",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.json()
        raise AssertionError("unreachable")  # pragma: no cover


# ----- payload helpers ---------------------------------------------------


def _fund_from_payload(payload: dict[str, Any]) -> Fund:
    """Map a Sukoon fund object onto the internal Fund model.

    Sukoon's response field names are scheme_code/scheme_name/amc_name/
    fund_type/ter; we normalise to id/name/category/amc/expense_ratio.
    """
    fund_id = str(payload.get("scheme_code") or payload.get("id") or "")
    name = str(payload.get("scheme_name") or payload.get("name") or "")
    category = str(payload.get("fund_type") or payload.get("category") or "")
    amc = str(payload.get("amc_name") or payload.get("amc") or "")
    benchmark = payload.get("benchmark")
    ter = payload.get("ter") if "ter" in payload else payload.get("expense_ratio")
    return Fund(
        id=fund_id,
        name=name,
        category=category,
        amc=amc,
        benchmark=str(benchmark) if benchmark else None,
        expense_ratio=float(ter) if ter is not None else None,
    )


def _nav_to_df(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(
            schema={"date": pl.Date, "nav": pl.Float64},
        )
    return (
        pl.DataFrame(rows)
        .rename({"nav_date": "date"})
        .with_columns(
            pl.col("date").str.strptime(pl.Date, "%Y-%m-%d"),
            pl.col("nav").cast(pl.Float64),
        )
        .sort("date")
    )


def _benchmark_to_df(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(
            schema={"date": pl.Date, "tri_value": pl.Float64},
        )
    return (
        pl.DataFrame(rows)
        .rename({"tri_date": "date"})
        .with_columns(
            pl.col("date").str.strptime(pl.Date, "%Y-%m-%d"),
            pl.col("tri_value").cast(pl.Float64),
        )
        .sort("date")
    )


__all__ = ["DEFAULT_BASE_URL", "SukoonAPIError", "SukoonDataClient"]
