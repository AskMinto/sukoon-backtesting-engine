"""Repository facade — coordinates client + cache (spec §7).

Backtests should depend only on this module; the client and cache are
implementation details. Offline mode forces cache-only reads and raises
when data is missing.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from sukoon_bt.data.cache import CacheBundle
from sukoon_bt.data.client import SukoonDataClient
from sukoon_bt.data.models import Fund


class DataUnavailableError(RuntimeError):
    """Raised in offline mode when the requested data is not cached."""


class FundRepository:
    """Read-side facade over Sukoon data with local caching.

    The client and cache are owned externally — pass an existing client and
    CacheBundle so the engine can use a single connection pool across many
    funds and a single cache process across runs.
    """

    def __init__(
        self,
        *,
        client: SukoonDataClient,
        cache: CacheBundle,
        offline: bool = False,
    ) -> None:
        self._client = client
        self._cache = cache
        self._offline = offline

    @property
    def offline(self) -> bool:
        return self._offline

    async def nav(self, fund_id: str, start: date, end: date) -> pl.DataFrame:
        cached = self._cache.nav.get(fund_id, start, end)
        if cached is not None:
            return cached
        if self._offline:
            raise DataUnavailableError(
                f"NAV history for {fund_id} ({start}..{end}) not in cache and offline=True"
            )
        df = await self._client.get_nav_history(fund_id, start, end)
        self._cache.nav.put(fund_id, df, start, end)
        return df

    async def benchmark(self, benchmark_id: str, start: date, end: date) -> pl.DataFrame:
        cached = self._cache.benchmark.get(benchmark_id, start, end)
        if cached is not None:
            return cached
        if self._offline:
            raise DataUnavailableError(
                f"benchmark {benchmark_id} ({start}..{end}) not in cache and offline=True"
            )
        df = await self._client.get_benchmark_history(benchmark_id, start, end)
        self._cache.benchmark.put(benchmark_id, df, start, end)
        return df

    async def fund(self, fund_id: str) -> Fund:
        cached = self._cache.metadata.get(fund_id)
        if cached is not None:
            return cached
        if self._offline:
            raise DataUnavailableError(
                f"fund metadata {fund_id} not in cache and offline=True"
            )
        fund = await self._client.get_fund_metadata(fund_id)
        self._cache.metadata.put(fund)
        return fund

    async def funds(self, fund_ids: list[str]) -> dict[str, Fund]:
        return {fid: await self.fund(fid) for fid in fund_ids}


__all__ = ["DataUnavailableError", "FundRepository"]
