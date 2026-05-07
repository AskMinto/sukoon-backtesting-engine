"""Structured logging tests."""

from __future__ import annotations

import logging
from io import StringIO

import orjson
import pytest

from sukoon_bt.utils.logging import JsonFormatter, LOGGER_NAME, configure, get_logger


@pytest.fixture(autouse=True)
def _reset_logger() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    yield
    for h in list(logger.handlers):
        logger.removeHandler(h)


def test_formatter_emits_iso_timestamp_and_level() -> None:
    record = logging.LogRecord(
        name="sukoon_bt.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    line = JsonFormatter().format(record)
    payload = orjson.loads(line)
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "sukoon_bt.test"
    assert payload["ts"].endswith("+00:00") or "T" in payload["ts"]


def test_extra_fields_propagate() -> None:
    logger = configure()
    sink = StringIO()
    h = logging.StreamHandler(sink)
    h.setFormatter(JsonFormatter())
    logger.addHandler(h)
    logger.info("trade booked", extra={"fund_id": "120503", "units": 12.5})
    line = sink.getvalue().strip().splitlines()[0]
    payload = orjson.loads(line)
    assert payload["msg"] == "trade booked"
    assert payload["fund_id"] == "120503"
    assert payload["units"] == 12.5


def test_get_logger_namespacing() -> None:
    assert get_logger().name == LOGGER_NAME
    assert get_logger("engine").name == f"{LOGGER_NAME}.engine"
