"""JSON reporter — spec §19."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import orjson

from sukoon_bt.analytics.drawdown import DrawdownStats
from sukoon_bt.analytics.metrics import PerformanceMetrics
from sukoon_bt.data.models import PortfolioSnapshot, Transaction


def write_run_json(
    path: Path,
    *,
    config: dict[str, Any],
    config_hash: str,
    engine_version: str,
    performance: PerformanceMetrics,
    drawdown: DrawdownStats,
    snapshots: list[PortfolioSnapshot],
    transactions: list[Transaction],
) -> None:
    payload: dict[str, Any] = {
        "engine_version": engine_version,
        "config_hash": config_hash,
        "config": config,
        "performance": _dataclass_to_dict(performance),
        "drawdown": _dataclass_to_dict(drawdown),
        "snapshots": [s.model_dump(mode="json") for s in snapshots],
        "transactions": [t.model_dump(mode="json") for t in transactions],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(orjson.dumps(payload, default=_default, option=orjson.OPT_INDENT_2))


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"expected dataclass, got {type(obj).__name__}")


def _default(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"unhandled type for JSON: {type(obj).__name__}")


__all__ = ["write_run_json"]
