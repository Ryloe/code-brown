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