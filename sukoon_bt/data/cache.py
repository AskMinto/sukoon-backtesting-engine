"""Local cache layer — spec §7.

Two cache stores live under ``~/.sukoon_bt/cache/``:

  * **Time-series cache** (NAV + benchmark): each fund/benchmark gets a
    parquet file under ``ts/<key>/<id>.parquet`` plus an entry in a
    sqlite-backed diskcache that records the cached date range and the
    fetched-at timestamp. Polars reads parquet directly which keeps
    backtest data loads fast (spec §2 — 10y single strategy run <5 sec).

  * **Metadata cache** (Fund objects): plain diskcache JSON.

Cache keys: time-series cached per-(kind, id), with TTL governing whether
we re-fetch the *full* range. Range queries narrower than the cached
window are served from parquet without a network call; queries wider
than the cached window invalidate and refetch.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from typing import Final, Literal

import diskcache
import polars as pl

from sukoon_bt.data.models import Fund

NAV_TTL_SECONDS: Final[int] = 24 * 3600
BENCHMARK_TTL_SECONDS: Final[int] = 24 * 3600
METADATA_TTL_SECONDS: Final[int] = 7 * 24 * 3600

_TimeSeriesKind = Literal["nav", "benchmark"]


def default_cache_dir() -> Path:
    return Path.home() / ".sukoon_bt" / "cache"


class TimeSeriesCache:
    """Per-id parquet store with a diskcache index for TTL + range tracking."""

    def __init__(self, root: Path, kind: _TimeSeriesKind, ttl_seconds: int) -> None:
        self._kind = kind
        self._ttl = ttl_seconds
        self._dir = root / "ts" / kind
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index = diskcache.Cache(str(root / "ts" / f"{kind}_index"))

    def _path(self, key: str) -> Path:
        # Keys may contain spaces (e.g. "NIFTY 500"); replace with underscore.
        safe = key.replace("/", "_").replace(" ", "_")
        return self._dir / f"{safe}.parquet"

    def get(self, key: str, start: date, end: date) -> pl.DataFrame | None:
        """Return cached rows in [start, end] if still fresh and covering."""
        meta = self._index.get(key)
        if not isinstance(meta, dict):
            return None
        fetched_at = float(meta.get("fetched_at", 0))
        if time.time() - fetched_at > self._ttl:
            return None
        cached_start = date.fromisoformat(meta["start"])
        cached_end = date.fromisoformat(meta["end"])
        if start < cached_start or end > cached_end:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        df = pl.read_parquet(path)
        return df.filter((pl.col("date") >= start) & (pl.col("date") <= end))

    def put(self, key: str, df: pl.DataFrame, start: date, end: date) -> None:
        if df.is_empty():
            return
        df.write_parquet(self._path(key))
        self._index[key] = {
            "fetched_at": time.time(),
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._index.clear()
            for f in self._dir.glob("*.parquet"):
                f.unlink()
        else:
            self._index.pop(key, None)
            self._path(key).unlink(missing_ok=True)

    def close(self) -> None:
        self._index.close()


class MetadataCache:
    """Plain key/value diskcache for Fund metadata."""

    def __init__(self, root: Path, ttl_seconds: int = METADATA_TTL_SECONDS) -> None:
        self._cache = diskcache.Cache(str(root / "metadata"))
        self._ttl = ttl_seconds

    def get(self, fund_id: str) -> Fund | None:
        payload = self._cache.get(fund_id)
        if not isinstance(payload, dict):
            return None
        return Fund(**payload)

    def put(self, fund: Fund) -> None:
        self._cache.set(fund.id, fund.model_dump(), expire=self._ttl)

    def clear(self) -> None:
        self._cache.clear()

    def close(self) -> None:
        self._cache.close()


class CacheBundle:
    """Container holding all cache stores; created once per process."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_cache_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.nav = TimeSeriesCache(self.root, "nav", NAV_TTL_SECONDS)
        self.benchmark = TimeSeriesCache(self.root, "benchmark", BENCHMARK_TTL_SECONDS)
        self.metadata = MetadataCache(self.root)

    def close(self) -> None:
        self.nav.close()
        self.benchmark.close()
        self.metadata.close()

    def __enter__(self) -> "CacheBundle":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def widen_range(
    cached_start: date,
    cached_end: date,
    requested_start: date,
    requested_end: date,
    pad_days: int = 0,
) -> tuple[date, date]:
    """Return the union of two date ranges (with optional pad).

    Used by the repository to refetch a single wider range rather than two
    disjoint slices when the user expands the requested window.
    """
    start = min(cached_start, requested_start) - timedelta(days=pad_days)
    end = max(cached_end, requested_end) + timedelta(days=pad_days)
    return start, end


__all__ = [
    "BENCHMARK_TTL_SECONDS",
    "CacheBundle",
    "METADATA_TTL_SECONDS",
    "MetadataCache",
    "NAV_TTL_SECONDS",
    "TimeSeriesCache",
    "default_cache_dir",
    "widen_range",
]
