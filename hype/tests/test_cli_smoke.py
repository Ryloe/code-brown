from __future__ import annotations

import json

from hype import cli
from shared.models import RelatedQuery, TrendPoint, TrendSeries


def _stub_fetch(term: str, range_value: str) -> TrendSeries:
    points = [
        TrendPoint(day_unix=1700000000 + i * 86400, intensity=20 + i)
        for i in range({"7d": 7, "30d": 30, "90d": 90}[range_value])
    ]
    return TrendSeries(range=range_value, points=points)


def _stub_related(term: str) -> list[RelatedQuery]:
    return [
        RelatedQuery(query="bape hoodie", value=250, kind="rising", is_breakout=False),
        RelatedQuery(query="bape", value=92, kind="top", is_breakout=False),
    ]


def test_cli_summary_smoke(monkeypatch, capsys):
    monkeypatch.setattr(cli.trends, "fetch", _stub_fetch)
    monkeypatch.setattr(cli.related, "fetch", _stub_related)
    monkeypatch.setattr("sys.argv", ["hype", "bape"])

    exit_code = cli.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "term=bape" in out
    assert "score=" in out


def test_cli_json_smoke(monkeypatch, capsys):
    monkeypatch.setattr(cli.trends, "fetch", _stub_fetch)
    monkeypatch.setattr(cli.related, "fetch", _stub_related)
    monkeypatch.setattr("sys.argv", ["hype", "bape", "--json"])

    exit_code = cli.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    payload = json.loads(out)
    assert payload["term"] == "bape"
    assert "score" in payload
    assert "confidence" in payload
    assert "series_30d" in payload
