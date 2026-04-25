from typing import Literal

from pydantic import BaseModel, Field


class EVDistribution(BaseModel):
    q10: float
    q50: float
    q90: float


class SellerBadges(BaseModel):
    verified: bool
    trusted_seller: bool
    quick_responder: bool
    speedy_shipper: bool


class Seller(BaseModel):
    seller_name: str
    reviews_count: int
    transactions_count: int
    items_for_sale_count: int
    posted_at_unix: int
    badges: SellerBadges


class LivePrice(BaseModel):
    listing_price_usd: int
    shipping_price_usd: int


class SoldPrice(BaseModel):
    sold_price_usd: int
    shipping_price_usd: int


class LiveListing(BaseModel):
    id: str
    url: str
    designer: str
    name: str
    size: str
    condition_raw: str
    location: str
    color: str
    image_urls: list[str]
    price: LivePrice
    seller: Seller
    description: str


class SoldListing(BaseModel):
    id: str
    url: str
    designer: str
    name: str
    size: str
    condition_raw: str
    location: str
    color: str
    image_urls: list[str]
    price: SoldPrice
    sold_at_unix: int
    seller: Seller
    description: str


class GrailedResultRow(BaseModel):
    live_listing: LiveListing
    sold_comparables: list[SoldListing] = Field(default_factory=list)


class ScrapeMetadata(BaseModel):
    query: str
    categories: list[str]
    live_limit_requested: int
    sold_limit_requested: int
    scraped_at_unix: int
    total_live_found: int


class GrailedScrapeResult(BaseModel):
    """Root object emitted by the scraper."""

    metadata: ScrapeMetadata
    results: list[GrailedResultRow] = Field(default_factory=list)


class TrendPoint(BaseModel):
    day_unix: int
    intensity: int


class TrendSeries(BaseModel):
    range: Literal["7d", "30d", "90d"]
    points: list[TrendPoint] = Field(default_factory=list)


class RelatedQuery(BaseModel):
    query: str
    value: int
    kind: Literal["rising", "top"]
    is_breakout: bool


class HypeEvidence(BaseModel):
    related: list[RelatedQuery] = Field(default_factory=list)


class HypeResult(BaseModel):
    term: str
    score: float | None
    confidence: Literal["high", "medium", "low", "insufficient"]
    series_30d: TrendSeries
    series_7d: TrendSeries | None = None
    series_90d: TrendSeries | None = None
    evidence: HypeEvidence
    fetched_at_unix: int