"""SukoonDataClient REST mapping tests using respx."""

from __future__ import annotations

from datetime import date

import httpx
import polars as pl
import pytest
import respx

from sukoon_bt.data.client import DEFAULT_BASE_URL, SukoonAPIError, SukoonDataClient


@pytest.fixture
def base_url() -> str:
    return DEFAULT_BASE_URL


@pytest.mark.asyncio
async def test_get_nav_history_maps_to_polars(base_url: str) -> None:
    payload = [
        {"nav_date": "2024-01-02", "nav": 101.5},
        {"nav_date": "2024-01-01", "nav": 100.0},
    ]
    async with respx.mock(base_url=base_url, assert_all_called=True) as router:
        route = router.get("/v1/funds/120503/nav").mock(return_value=httpx.Response(200, json=payload))
        async with SukoonDataClient() as client:
            df = await client.get_nav_history("120503", date(2024, 1, 1), date(2024, 1, 31))

    assert route.calls.last is not None
    assert dict(route.calls.last.request.url.params) == {"from": "2024-01-01", "to": "2024-01-31"}
    assert df.schema == {"date": pl.Date, "nav": pl.Float64}
    assert df.height == 2
    # Sorted ascending by date
    assert df["date"].to_list() == [date(2024, 1, 1), date(2024, 1, 2)]
    assert df["nav"].to_list() == [100.0, 101.5]


@pytest.mark.asyncio
async def test_get_nav_history_empty(base_url: str) -> None:
    async with respx.mock(base_url=base_url) as router:
        router.get("/v1/funds/120503/nav").mock(return_value=httpx.Response(200, json=[]))
        async with SukoonDataClient() as client:
            df = await client.get_nav_history("120503", date(2024, 1, 1), date(2024, 1, 2))
    assert df.is_empty()
    assert df.schema == {"date": pl.Date, "nav": pl.Float64}


@pytest.mark.asyncio
async def test_get_fund_metadata(base_url: str) -> None:
    payload = {
        "scheme_code": "120503",
        "scheme_name": "Parag Parikh Flexi Cap",
        "amc_name": "PPFAS",
        "fund_type": "Flexi Cap",
        "ter": 0.0074,
    }
    async with respx.mock(base_url=base_url) as router:
        router.get("/v1/funds/120503").mock(return_value=httpx.Response(200, json=payload))
        async with SukoonDataClient() as client:
            fund = await client.get_fund_metadata("120503")
    assert fund.id == "120503"
    assert fund.name == "Parag Parikh Flexi Cap"
    assert fund.amc == "PPFAS"
    assert fund.category == "Flexi Cap"
    assert fund.expense_ratio == pytest.approx(0.0074)


@pytest.mark.asyncio
async def test_search_funds(base_url: str) -> None:
    payload = {
        "funds": [
            {
                "scheme_code": "120503",
                "scheme_name": "Parag Parikh Flexi Cap",
                "amc_name": "PPFAS",
                "fund_type": "Flexi Cap",
            },
            {
                "scheme_code": "118989",
                "scheme_name": "HDFC Flexi Cap",
                "amc_name": "HDFC",
                "fund_type": "Flexi Cap",
            },
        ],
        "total": 2,
        "page": 1,
        "pageSize": 50,
    }
    async with respx.mock(base_url=base_url) as router:
        route = router.get("/v1/funds").mock(return_value=httpx.Response(200, json=payload))
        async with SukoonDataClient() as client:
            funds = await client.search_funds(query="flexi", category="Flexi Cap")

    assert len(funds) == 2
    assert {f.id for f in funds} == {"120503", "118989"}
    params = dict(route.calls.last.request.url.params)
    assert params["q"] == "flexi"
    assert params["type"] == "Flexi Cap"
    assert params["page"] == "1"
    assert params["pageSize"] == "50"


@pytest.mark.asyncio
async def test_get_benchmark_history_url_encodes_index_name(base_url: str) -> None:
    payload = {
        "index": "NIFTY 500",
        "data": [{"tri_date": "2024-01-01", "tri_value": 33000.5}],
    }
    async with respx.mock(base_url=base_url) as router:
        # respx matches on the decoded path; assert encoded form is sent.
        route = router.get("/v1/benchmarks/NIFTY 500").mock(
            return_value=httpx.Response(200, json=payload)
        )
        async with SukoonDataClient() as client:
            df = await client.get_benchmark_history(
                "NIFTY 500", date(2024, 1, 1), date(2024, 1, 31)
            )
    assert "NIFTY%20500" in str(route.calls.last.request.url)
    assert df.schema == {"date": pl.Date, "tri_value": pl.Float64}
    assert df.height == 1


@pytest.mark.asyncio
async def test_retries_on_500(base_url: str) -> None:
    async with respx.mock(base_url=base_url) as router:
        route = router.get("/v1/funds/120503/nav").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json=[]),
            ]
        )
        async with SukoonDataClient(max_retries=3) as client:
            df = await client.get_nav_history("120503", date(2024, 1, 1), date(2024, 1, 2))
    assert df.is_empty()
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_unexpected_payload_raises(base_url: str) -> None:
    async with respx.mock(base_url=base_url) as router:
        router.get("/v1/funds/120503/nav").mock(
            return_value=httpx.Response(200, json={"unexpected": "object"})
        )
        async with SukoonDataClient() as client:
            with pytest.raises(SukoonAPIError):
                await client.get_nav_history("120503", date(2024, 1, 1), date(2024, 1, 2))


@pytest.mark.asyncio
async def test_user_agent_set(base_url: str) -> None:
    async with respx.mock(base_url=base_url) as router:
        route = router.get("/v1/funds/120503/nav").mock(return_value=httpx.Response(200, json=[]))
        async with SukoonDataClient() as client:
            await client.get_nav_history("120503", date(2024, 1, 1), date(2024, 1, 2))
    ua = route.calls.last.request.headers["user-agent"]
    assert ua.startswith("sukoon-bt/")
