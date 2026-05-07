"""Cache + repository tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import polars as pl
import pytest

from sukoon_bt.data.cache import CacheBundle, MetadataCache, TimeSeriesCache, widen_range
from sukoon_bt.data.client import SukoonDataClient
from sukoon_bt.data.models import Fund
from sukoon_bt.data.repository import DataUnavailableError, FundRepository


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def cache(cache_root: Path):
    bundle = CacheBundle(cache_root)
    yield bundle
    bundle.close()


def _df(rows: list[tuple[date, float]]) -> pl.DataFrame:
    return pl.DataFrame({"date": [r[0] for r in rows], "nav": [r[1] for r in rows]}).with_columns(
        pl.col("date").cast(pl.Date), pl.col("nav").cast(pl.Float64)
    )


class TestTimeSeriesCache:
    def test_round_trip_within_cached_range(self, cache_root: Path) -> None:
        ts = TimeSeriesCache(cache_root, "nav", ttl_seconds=60)
        df = _df(
            [
                (date(2024, 1, 1), 100.0),
                (date(2024, 1, 2), 101.0),
                (date(2024, 1, 3), 102.0),
            ]
        )
        ts.put("120503", df, date(2024, 1, 1), date(2024, 1, 3))
        got = ts.get("120503", date(2024, 1, 1), date(2024, 1, 2))
        assert got is not None
        assert got["date"].to_list() == [date(2024, 1, 1), date(2024, 1, 2)]
        ts.close()

    def test_miss_when_range_exceeds_cache(self, cache_root: Path) -> None:
        ts = TimeSeriesCache(cache_root, "nav", ttl_seconds=60)
        ts.put("120503", _df([(date(2024, 1, 1), 100.0)]), date(2024, 1, 1), date(2024, 1, 1))
        assert ts.get("120503", date(2024, 1, 1), date(2024, 1, 5)) is None
        ts.close()

    def test_ttl_expiry(self, cache_root: Path) -> None:
        ts = TimeSeriesCache(cache_root, "nav", ttl_seconds=0)
        ts.put("120503", _df([(date(2024, 1, 1), 100.0)]), date(2024, 1, 1), date(2024, 1, 1))
        # ttl=0 means anything older than now is stale.
        assert ts.get("120503", date(2024, 1, 1), date(2024, 1, 1)) is None
        ts.close()


class TestMetadataCache:
    def test_round_trip(self, cache_root: Path) -> None:
        m = MetadataCache(cache_root)
        f = Fund(id="120503", name="Parag Parikh Flexi Cap", category="Flexi Cap", amc="PPFAS")
        m.put(f)
        got = m.get("120503")
        assert got == f
        m.close()


class TestWidenRange:
    def test_union(self) -> None:
        s, e = widen_range(date(2024, 1, 5), date(2024, 1, 10), date(2024, 1, 1), date(2024, 1, 7))
        assert s == date(2024, 1, 1)
        assert e == date(2024, 1, 10)


class TestRepository:
    @pytest.mark.asyncio
    async def test_nav_caches_after_first_fetch(self, cache: CacheBundle) -> None:
        client = AsyncMock(spec=SukoonDataClient)
        client.get_nav_history.return_value = _df([(date(2024, 1, 1), 100.0)])
        repo = FundRepository(client=client, cache=cache)

        df1 = await repo.nav("120503", date(2024, 1, 1), date(2024, 1, 1))
        df2 = await repo.nav("120503", date(2024, 1, 1), date(2024, 1, 1))

        assert df1.height == 1
        assert df2.height == 1
        client.get_nav_history.assert_awaited_once()  # second call hit cache

    @pytest.mark.asyncio
    async def test_offline_mode_raises_on_miss(self, cache: CacheBundle) -> None:
        client = AsyncMock(spec=SukoonDataClient)
        repo = FundRepository(client=client, cache=cache, offline=True)
        with pytest.raises(DataUnavailableError):
            await repo.nav("120503", date(2024, 1, 1), date(2024, 1, 2))
        client.get_nav_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_fund_metadata_cached(self, cache: CacheBundle) -> None:
        client = AsyncMock(spec=SukoonDataClient)
        f = Fund(id="120503", name="PPFC", category="Flexi Cap", amc="PPFAS")
        client.get_fund_metadata.return_value = f
        repo = FundRepository(client=client, cache=cache)

        await repo.fund("120503")
        await repo.fund("120503")
        client.get_fund_metadata.assert_awaited_once()
