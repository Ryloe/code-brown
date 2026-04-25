"""Scraper-specific exceptions."""

from __future__ import annotations


class ScraperError(Exception):
    """Base for all scraper errors."""


class GrailedRateLimitExceeded(ScraperError):
    """Raised after tenacity exhausts retries on HTTP 429."""


class SchemaValidationError(ScraperError):
    """Raised when a raw response cannot be parsed into the expected Pydantic model."""


class ScrapeAborted(ScraperError):
    """Raised when the caller-provided abort signal fires mid-run."""
