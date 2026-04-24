# Scraper output (`GrailedScrapeResult`)

Top-level object returned by the GRAILED scraper: query metadata, plus one row per **live** listing, each with nested **sold** comparables.

## Top level

| Field        | Type                    | Description |
|-------------|-------------------------|-------------|
| `metadata`  | `ScrapeMetadata`        | Query, limits, scrape time, counts. |
| `results`   | `GrailedResultRow[]`    | One entry per live listing; each has its own `sold_comparables`. Up to `live_limit_requested` entries (e.g. 40). |

## `ScrapeMetadata`

| Field                    | Type       | Description |
|-------------------------|------------|-------------|
| `query`                 | `string`   | Search string (e.g. product name). |
| `categories`            | `string[]` | e.g. `menswear`, `footwear`. |
| `live_limit_requested`  | `int`      | Max live listings to return. |
| `sold_limit_requested`  | `int`      | Max sold comparables per live row. |
| `scraped_at_unix`      | `int`      | Unix seconds when scrape finished. |
| `total_live_found`      | `int`      | Live listings found (may be less than `live_limit_requested`). |

## `GrailedResultRow`

| Field                | Type              | Description |
|---------------------|-------------------|-------------|
| `live_listing`      | `LiveListing`     | The active GRAILED listing. |
| `sold_comparables`  | `SoldListing[]`   | Past sold listings matched as comps for this live row. Up to `sold_limit_requested` per row (e.g. 40). |

## `LiveListing`

| Field            | Type              | Description |
|-----------------|-------------------|-------------|
| `id`            | `string`          | GRAILED listing id. |
| `url`           | `string`          | Listing URL. |
| `designer`      | `string`          | Brand. |
| `name`          | `string`          | Title. |
| `size`          | `string`          | Size as shown on site. |
| `condition_raw` | `string`          | Condition label (e.g. Gently Used). |
| `location`      | `string`          | Region (e.g. US, EU). |
| `color`         | `string`          | Color. |
| `image_urls`    | `string[]`        | Image URLs. |
| `price`         | `LivePrice`      | Asking + shipping. |
| `seller`        | `Seller`          | Seller profile snapshot. |
| `description`   | `string`          | Listing body text. |

## `LivePrice`

| Field                 | Type   | Description |
|----------------------|--------|-------------|
| `listing_price_usd`  | `int`  | Asking price USD. |
| `shipping_price_usd` | `int`  | Shipping USD. |

## `SoldListing`

Same catalog fields as live where applicable, plus sale-specific fields.

| Field            | Type              | Description |
|-----------------|-------------------|-------------|
| `id` … `color`  | (same as live)    | — |
| `image_urls`    | `string[]`        | — |
| `price`         | `SoldPrice`       | Sold total + shipping. |
| `sold_at_unix`  | `int`             | When sale recorded (Unix seconds). |
| `seller`        | `Seller`          | — |
| `description`   | `string`          | — |

## `SoldPrice`

| Field                 | Type  | Description |
|----------------------|-------|-------------|
| `sold_price_usd`     | `int` | Sold price USD. |
| `shipping_price_usd` | `int` | Shipping USD. |

## `Seller`

| Field                   | Type            | Description |
|------------------------|-----------------|-------------|
| `seller_name`          | `string`        | Display name. |
| `reviews_count`        | `int`           | — |
| `transactions_count`   | `int`           | — |
| `items_for_sale_count` | `int`           | — |
| `posted_at_unix`       | `int`           | Listing post time (Unix seconds). |
| `badges`               | `SellerBadges`  | — |

## `SellerBadges`

| Field              | Type   |
|-------------------|--------|
| `verified`        | `bool` |
| `trusted_seller`  | `bool` |
| `quick_responder` | `bool` |
| `speedy_shipper`  | `bool` |

## Example (shape)

```json
{
  "metadata": {
    "query": "Guidi 788Z",
    "categories": ["menswear", "footwear"],
    "live_limit_requested": 40,
    "sold_limit_requested": 40,
    "scraped_at_unix": 1713995645,
    "total_live_found": 38
  },
  "results": [
    {
      "live_listing": {
        "id": "14589321",
        "url": "https://www.grailed.com/listings/14589321-guidi-788z-back-zip-boots",
        "designer": "Guidi",
        "name": "788Z Back Zip Boots",
        "size": "43",
        "condition_raw": "Gently Used",
        "location": "US",
        "color": "Black",
        "image_urls": [
          "https://media-assets.grailed.com/prd/listing/14589321/photo1.jpg"
        ],
        "price": { "listing_price_usd": 850, "shipping_price_usd": 20 },
        "seller": {
          "seller_name": "ArchiveArchivist",
          "reviews_count": 150,
          "transactions_count": 175,
          "items_for_sale_count": 12,
          "posted_at_unix": 1713000000,
          "badges": {
            "verified": true,
            "trusted_seller": true,
            "quick_responder": false,
            "speedy_shipper": true
          }
        },
        "description": "Vibramed since day one. Slight heel drag..."
      },
      "sold_comparables": [
        {
          "id": "13904822",
          "url": "https://www.grailed.com/listings/13904822-guidi-788z-horse-full-grain",
          "designer": "Guidi",
          "name": "788Z Horse Full Grain",
          "size": "43",
          "condition_raw": "Used",
          "location": "EU",
          "color": "Black",
          "image_urls": [
            "https://media-assets.grailed.com/prd/listing/13904822/photo1.jpg"
          ],
          "price": { "sold_price_usd": 720, "shipping_price_usd": 45 },
          "sold_at_unix": 1711500000,
          "seller": {
            "seller_name": "DarkwearEU",
            "reviews_count": 89,
            "transactions_count": 94,
            "items_for_sale_count": 3,
            "posted_at_unix": 1709000000,
            "badges": {
              "verified": true,
              "trusted_seller": false,
              "quick_responder": true,
              "speedy_shipper": false
            }
          },
          "description": "Classic backzips. Worn a handful of times."
        }
      ]
    }
  ]
}
```

Each `results` element pairs one live row with up to `sold_limit_requested` sold rows (e.g. 40). Total live rows is at most `live_limit_requested`.
