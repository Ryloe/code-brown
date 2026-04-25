"""Unit tests for the scraper HTTP client."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from scraper.client import GrailedClient
from scraper.exceptions import GrailedRateLimitExceeded


@pytest.mark.asyncio
@respx.mock
async def test_get_json_returns_decoded_body():
    route = respx.get("https://example.test/x").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with GrailedClient(delay_range=(0.0, 0.0)) as client:
        body = await client.get_json("https://example.test/x")
    assert body == {"ok": True}
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_get_json_sets_user_agent_and_referer():
    captured: dict[str, str | None] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent")
        captured["ref"] = request.headers.get("referer")
        return httpx.Response(200, json={})

    respx.get("https://example.test/x").mock(side_effect=_capture)
    async with GrailedClient(delay_range=(0.0, 0.0)) as client:
        await client.get_json("https://example.test/x")

    assert captured["ua"]
    assert captured["ref"] == "https://www.grailed.com/"


@pytest.mark.asyncio
@respx.mock
async def test_get_json_retries_on_429_then_succeeds():
    route = respx.get("https://example.test/y").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    async with GrailedClient(
        delay_range=(0.0, 0.0), retry_wait_initial=0.01, max_429_attempts=2
    ) as client:
        body = await client.get_json("https://example.test/y")
    assert body == {"ok": 1}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_json_raises_after_429_exhaustion():
    respx.get("https://example.test/z").mock(return_value=httpx.Response(429))
    async with GrailedClient(
        delay_range=(0.0, 0.0), retry_wait_initial=0.01, max_429_attempts=2
    ) as client:
        with pytest.raises(GrailedRateLimitExceeded):
            await client.get_json("https://example.test/z")
