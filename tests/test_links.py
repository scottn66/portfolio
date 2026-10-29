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


def test_classify_hrefs_includes_src_and_non_anchor_hrefs() -> None:
    html = """
    <a href="/docs/">docs</a>
    <img src="/img/logo.svg" alt="logo">
    <script src="app.js"></script>
    <link href="https://cdn.example/style.css" rel="stylesheet">
    <source src="/media/clip.mp4">
    <img SRC="/img/logo.svg">
    """
    links = classify_hrefs(html, "https://scottn66.github.io/solar/")
    assert [(link.url, link.kind) for link in links] == [
        ("https://scottn66.github.io/docs/", "internal"),
        ("https://scottn66.github.io/img/logo.svg", "internal"),
        ("https://scottn66.github.io/solar/app.js", "internal"),
        ("https://cdn.example/style.css", "external"),
        ("https://scottn66.github.io/media/clip.mp4", "internal"),
    ]
    logo = next(link for link in links if link.url.endswith("logo.svg"))
    assert logo.href == "/img/logo.svg"


def test_fetch_status_head_and_redirects_use_the_supplied_client() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        if request.method == "HEAD":
            return httpx.Response(204)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        head = fetch_status("https://example.test/file", client=client, method="HEAD")
        followed = fetch_status(
            "https://example.test/old",
            client=client,
            follow_redirects=True,
        )
        raw = fetch_status("https://example.test/old", client=client)

    assert head == 204
    assert followed == 200
    assert raw == 301
    assert seen == [
        ("HEAD", "/file"),
        ("GET", "/old"),
        ("GET", "/new"),
        ("GET", "/old"),
    ]


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


def test_fetch_status_owned_client_honors_method_and_redirects(
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

        def request(
            self,
            method: str,
            url: str,
            *,
            follow_redirects: bool,
        ) -> _Response:
            captured["method"] = method
            captured["url"] = url
            captured["follow_redirects"] = follow_redirects
            return _Response()

    monkeypatch.setattr("portfolio_qc.links.httpx.Client", _Client)
    status = fetch_status(
        "https://scottn66.github.io/solar/",
        timeout=1.5,
        method="HEAD",
        follow_redirects=True,
    )
    assert status == 200
    assert captured == {
        "timeout": 1.5,
        "method": "HEAD",
        "url": "https://scottn66.github.io/solar/",
        "follow_redirects": True,
    }
