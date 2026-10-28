"""Tests for href classification and the httpx status wrapper. No live network."""

from __future__ import annotations

from typing import Self

import httpx
import pytest

from portfolio_qc.links import classify_hrefs, fetch_status

BASE = "https://scottn66.github.io/"

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
  <body>
    <a href="/solar/">solar</a>
    <a href="bitcoin-power-law/index.html">btc</a>
    <a href="https://github.com/scottn66/solar-energy-analysis">repo</a>
    <a href="//example.com/asset">cdn</a>
    <a href="https://scottn66.github.io.evil.example/phish">lookalike</a>
    <a href="mailto:dev@example.com">mail</a>
    <a href="javascript:void(0)">js</a>
    <a href="   ">blank</a>
    <a href="#section">here</a>
    <a href="https://ScottN66.GitHub.io/Q.html#part">q</a>
    <a href="/solar/">again</a>
    <a href="http://scottn66.github.io/demographics/">http</a>
  </body>
</html>
"""


def test_classify_hrefs_normalizes_and_classifies() -> None:
    links = classify_hrefs(SAMPLE_HTML, BASE)
    assert [(link.url, link.kind) for link in links] == [
        ("https://scottn66.github.io/solar/", "internal"),
        ("https://scottn66.github.io/bitcoin-power-law/index.html", "internal"),
        ("https://github.com/scottn66/solar-energy-analysis", "external"),
        ("https://example.com/asset", "external"),
        ("https://scottn66.github.io.evil.example/phish", "external"),
        ("https://scottn66.github.io/", "internal"),
        ("https://scottn66.github.io/Q.html", "internal"),
        ("http://scottn66.github.io/demographics/", "internal"),
    ]
    solar = next(link for link in links if link.url.endswith("/solar/"))
    assert solar.href == "/solar/"


def test_classify_hrefs_rejects_relative_base() -> None:
    with pytest.raises(ValueError, match="absolute http"):
        classify_hrefs('<a href="/solar/">solar</a>', "/not-absolute")


def test_fetch_status_uses_mock_transport() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=2.0) as client:
        status = fetch_status("https://scottn66.github.io/", timeout=2.0, client=client)

    assert status == 204
    assert [str(request.url) for request in seen] == ["https://scottn66.github.io/"]


def test_fetch_status_applies_timeout_when_it_builds_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 200

    class _Client:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, url: str) -> _Response:
            captured["url"] = url
            return _Response()

    monkeypatch.setattr("portfolio_qc.links.httpx.Client", _Client)
    assert fetch_status("https://scottn66.github.io/solar/", timeout=3.5) == 200
    assert captured == {"timeout": 3.5, "url": "https://scottn66.github.io/solar/"}
