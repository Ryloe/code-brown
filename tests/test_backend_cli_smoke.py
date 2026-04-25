from __future__ import annotations

import json

from backend import cli
from shared.models import (
    HypeEvidence,
    HypeResult,
    LiveListing,
    LivePrice,
    RankedListing,
    RelatedQuery,
    ScrapeMetadata,
    SearchParams,
    SearchResponse,
    Seller,
    SellerBadges,
    SoldListing,
    SoldPrice,
    TrendPoint,
    TrendSeries,
)


def _seller() -> Seller:
    return Seller(
        seller_name="tester",
        reviews_count=10,
        transactions_count=20,
        items_for_sale_count=3,
        posted_at_unix=1700000000,
        badges=SellerBadges(
            verified=True,
            trusted_seller=False,
            quick_responder=False,
            speedy_shipper=False,
        ),
    )


def _search_response() -> SearchResponse:
    live = LiveListing(
        id="1",
        url="https://www.grailed.com/listings/1",
        designer="Guidi",
        name="788Z",
        size="43",
        condition_raw="Used",
        location="US",
        color="Black",
        image_urls=[],
        price=LivePrice(listing_price_usd=700, shipping_price_usd=25),
        seller=_seller(),
        description="desc",
    )
    sold = SoldListing(
        id="s1",
        url="https://www.grailed.com/listings/s1",
        designer="Guidi",
        name="788Z",
        size="43",
        condition_raw="Used",
        location="US",
        color="Black",
        image_urls=[],
        price=SoldPrice(sold_price_usd=680, shipping_price_usd=20),
        sold_at_unix=1700000200,
        seller=_seller(),
        description="desc",
    )
    ranked = RankedListing(
        live_listing=live,
        sold_comparables=[sold],
        valuation={
            "id": "1",
            "name": "788Z",
            "cost": 725.0,
            "dist": {"q10": 610.0, "q50": 700.0, "q90": 780.0},
            "metrics": {
                "edge_usd": 55.0,
                "percent_under": 7.59,
                "effective_n": 3.0,
                "confidence": "medium",
            },
        },
        sell_probability={
            "p_sell": 0.5,
            "horizon_days": 7,
            "median_days_to_sell": 10.0,
            "adjusted_days_to_sell": 11.0,
            "pricing_ratio": 1.0,
            "live_price": 725.0,
            "q50_comp_price": 700.0,
            "num_valid_time_comps": 2,
            "num_sold_comps": 3,
        },
    )
    metadata = ScrapeMetadata(
        query="guidi",
        categories=["menswear"],
        live_limit_requested=3,
        sold_limit_requested=5,
        scraped_at_unix=1700000000,
        total_live_found=1,
    )
    return SearchResponse(metadata=metadata, ranked=[ranked])


def _hype_result() -> HypeResult:
    return HypeResult(
        term="guidi",
        score=0.8,
        confidence="medium",
        series_30d=TrendSeries(range="30d", points=[TrendPoint(day_unix=1700000000, intensity=20)]),
        series_7d=TrendSeries(range="7d", points=[TrendPoint(day_unix=1700000000, intensity=22)]),
        series_90d=TrendSeries(range="90d", points=[TrendPoint(day_unix=1700000000, intensity=15)]),
        evidence=HypeEvidence(
            related=[RelatedQuery(query="guidi boots", value=90, kind="top", is_breakout=False)]
        ),
        fetched_at_unix=1700000600,
    )


def test_search_subcommand_invokes_orchestrator(monkeypatch, capsys):
    calls: list[SearchParams] = []

    async def _run_search_stub(params: SearchParams):
        calls.append(params)
        return _search_response()

    monkeypatch.setattr(cli, "_prompt_params", lambda: SearchParams(query="guidi"))
    monkeypatch.setattr(cli.orchestrator, "run_search", _run_search_stub)
    monkeypatch.setattr("sys.argv", ["backend.cli", "search"])

    exit_code = cli.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert len(calls) == 1
    assert "metadata" in out
    assert "[1/1]" in out
    assert "Guidi 788Z" in out


def test_hype_subcommand_invokes_orchestrator(monkeypatch, capsys):
    calls: list[str] = []

    async def _run_hype_stub(term: str):
        calls.append(term)
        return _hype_result()

    monkeypatch.setattr(cli.orchestrator, "run_hype", _run_hype_stub)
    monkeypatch.setattr("sys.argv", ["backend.cli", "hype", "guidi"])

    exit_code = cli.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert calls == ["guidi"]
    assert "term=guidi" in out
    assert "score=" in out


def test_search_subcommand_json_flag_produces_valid_json(monkeypatch, capsys):
    async def _run_search_stub(params: SearchParams):
        return _search_response()

    monkeypatch.setattr(cli, "_prompt_params", lambda: SearchParams(query="guidi"))
    monkeypatch.setattr(cli.orchestrator, "run_search", _run_search_stub)
    monkeypatch.setattr("sys.argv", ["backend.cli", "search", "--json"])

    exit_code = cli.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert "metadata" in payload
    assert "ranked" in payload