from __future__ import annotations

import pandas as pd

from hype import related


class _ClientStub:
    def __init__(self, payload):
        self._payload = payload

    def build_payload(self, kw_list, cat, timeframe, geo, gprop):
        return None

    def related_queries(self):
        return self._payload


def test_fetch_sorts_breakouts_then_rising_then_top(monkeypatch):
    term = "bape"
    rising = pd.DataFrame(
        {
            "query": ["q1", "q2", "q3", "skip"],
            "value": ["Breakout", 350, 120, "n/a"],
        }
    )
    top = pd.DataFrame(
        {
            "query": ["q4", "q5"],
            "value": [90, 75],
        }
    )
    payload = {term: {"top": top, "rising": rising}}
    monkeypatch.setattr(related, "_build_client", lambda: _ClientStub(payload))

    items = related.fetch(term)

    assert [i.query for i in items] == ["q1", "q2", "q3", "q4", "q5"]
    assert items[0].is_breakout is True
    assert items[1].kind == "rising"
    assert items[3].kind == "top"


def test_fetch_returns_empty_when_frames_none(monkeypatch):
    term = "bape"
    payload = {term: {"top": None, "rising": None}}
    monkeypatch.setattr(related, "_build_client", lambda: _ClientStub(payload))

    assert related.fetch(term) == []


def test_fetch_returns_empty_when_term_missing(monkeypatch):
    term = "bape"
    payload = {}
    monkeypatch.setattr(related, "_build_client", lambda: _ClientStub(payload))

    assert related.fetch(term) == []


def test_fetch_caps_at_ten_items(monkeypatch):
    term = "bape"
    rising = pd.DataFrame(
        {
            "query": [f"rq{i}" for i in range(8)],
            "value": [100 - i for i in range(8)],
        }
    )
    top = pd.DataFrame(
        {
            "query": [f"tq{i}" for i in range(8)],
            "value": [80 - i for i in range(8)],
        }
    )
    payload = {term: {"top": top, "rising": rising}}
    monkeypatch.setattr(related, "_build_client", lambda: _ClientStub(payload))

    items = related.fetch(term)

    assert len(items) == 10
