"""Link crawler tests. httpx.MockTransport only; no live network."""

from __future__ import annotations

import threading

import httpx
import pytest

from portfolio_qc.links import (
    LinkCheck,
    LinkReport,
    build_client,
    check_links,
    exit_code,
    format_summary,
    user_agent,
)

BASE = "https://example.test/"


def _html(body: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=f"<!doctype html><html><body>{body}</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )


def _run(
    transport: httpx.BaseTransport,
    *,
    base: str = BASE,
    max_pages: int = 10,
    concurrency: int = 4,
    client: httpx.Client | None = None,
) -> LinkReport:
    return check_links(
        base,
        max_pages=max_pages,
        timeout=2.0,
        concurrency=concurrency,
        client=client,
        transport=None if client is not None else transport,
    )


def test_build_client_sets_timeout_user_agent_and_connection_limit() -> None:
    client = build_client(timeout=4.0, concurrency=3)
    try:
        assert client.timeout == httpx.Timeout(4.0)
        assert client.headers["user-agent"] == user_agent()
        pool = client._transport._pool  # type: ignore[attr-defined]
        assert pool._max_connections == 3
        assert pool._max_keepalive_connections == 3
    finally:
        client.close()


def test_check_links_rejects_bad_arguments() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200))
    with pytest.raises(ValueError, match="absolute http"):
        check_links("/relative", transport=transport)
    with pytest.raises(ValueError, match="max_pages"):
        check_links(BASE, max_pages=0, transport=transport)
    with pytest.raises(ValueError, match="concurrency"):
        check_links(BASE, concurrency=0, transport=transport)
    with pytest.raises(ValueError, match="timeout"):
        check_links(BASE, timeout=0, transport=transport)
    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(ValueError, match="not both"),
    ):
        check_links(BASE, client=client, transport=transport)


def test_crawl_checks_href_and_src_and_sends_user_agent() -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (request.method, str(request.url), request.headers.get("user-agent"))
        )
        if request.url.path == "/":
            return _html(
                '<a href="/docs/">docs</a>'
                '<img src="/logo.png" alt="">'
                '<script src="https://cdn.example/app.js"></script>'
                '<a href="mailto:dev@example.test">mail</a>'
                '<a href="#section">here</a>'
            )
        if request.url.path == "/docs/":
            return _html("<p>docs</p>")
        if request.url.path == "/logo.png":
            return httpx.Response(200, content=b"png")
        if str(request.url) == "https://cdn.example/app.js":
            assert request.method == "HEAD"
            return httpx.Response(200)
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler))
    assert report.pages_crawled == (BASE, "https://example.test/docs/")
    assert [
        (item.url, item.kind, item.outcome, item.status) for item in report.results
    ] == [
        (BASE, "internal", "ok", 200),
        ("https://example.test/docs/", "internal", "ok", 200),
        ("https://example.test/logo.png", "internal", "ok", 200),
        ("https://cdn.example/app.js", "external", "ok", 200),
    ]
    docs = next(item for item in report.results if item.url.endswith("/docs/"))
    assert docs.sources == (BASE,)
    assert all(agent == user_agent() for _method, _url, agent in seen)
    assert exit_code(report) == 0
    assert not any(path == "/section" for _method, path, _agent in seen)


def test_max_pages_does_not_parse_uncrawled_pages() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        pages = {
            "/": '<a href="/a.html">a</a><a href="/b.html">b</a>',
            "/a.html": '<a href="/secret.html">s</a>',
            "/b.html": '<a href="/secret.html">s</a>',
            "/secret.html": '<a href="/deeper.html">d</a>',
        }
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(599)
        return _html(body)

    report = _run(httpx.MockTransport(handler), max_pages=1)
    assert report.pages_crawled == (BASE,)
    assert "https://example.test/secret.html" not in requested
    assert {item.url for item in report.results} == {
        BASE,
        "https://example.test/a.html",
        "https://example.test/b.html",
    }

    requested.clear()
    report = _run(httpx.MockTransport(handler), max_pages=2)
    assert report.pages_crawled == (BASE, "https://example.test/a.html")
    assert "https://example.test/secret.html" in requested
    assert "https://example.test/deeper.html" not in requested
    secret = next(item for item in report.results if item.url.endswith("/secret.html"))
    assert secret.outcome == "ok"
    assert secret.sources == ("https://example.test/a.html",)


def test_same_origin_only_and_assets_are_not_crawled() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url == httpx.URL(BASE):
            return _html(
                '<a href="http://example.test/plain.html">http</a>'
                '<a href="/next">next</a>'
                '<a href="/data.json">json</a>'
            )
        if str(request.url) == "http://example.test/plain.html":
            return _html('<a href="/only-on-http.html">hidden</a>')
        if request.url.path == "/next":
            return _html("<p>next</p>")
        if request.url.path == "/data.json":
            return httpx.Response(
                200,
                text='<a href="/only-in-json.html">x</a>',
                headers={"content-type": "application/json"},
            )
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler))
    assert "http://example.test/only-on-http.html" not in requested
    assert "https://example.test/only-in-json.html" not in requested
    assert "https://example.test/next" in report.pages_crawled
    assert "http://example.test/plain.html" not in report.pages_crawled
    assert "https://example.test/data.json" not in report.pages_crawled
    plain = next(item for item in report.results if item.url.startswith("http://"))
    assert plain.kind == "internal"
    assert plain.outcome == "ok"
    data = next(item for item in report.results if item.url.endswith(".json"))
    assert data.outcome == "ok"


def test_relative_links_use_the_redirect_target() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                301, headers={"location": "https://example.test/dir/"}
            )
        if request.url.path == "/dir/":
            return _html('<a href="page.html">page</a>')
        if request.url.path == "/dir/page.html":
            return _html("<p>page</p>")
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler), base="https://example.test/start")
    assert "https://example.test/dir/page.html" in {item.url for item in report.results}
    assert "https://example.test/page.html" not in requested
    start = report.results[0]
    assert start.url == "https://example.test/start"
    assert start.outcome == "ok"
    assert start.status == 200


def test_non_html_and_error_pages_are_not_parsed() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path == "/":
            return _html(
                '<a href="/notes.txt">t</a><a href="/gone.html">g</a><a href="/empty">e</a>'
            )
        if request.url.path == "/notes.txt":
            return httpx.Response(
                200,
                text='<a href="/from-text.html">x</a>',
                headers={"content-type": "text/plain"},
            )
        if request.url.path == "/gone.html":
            return httpx.Response(
                404,
                text='<a href="/from-404.html">x</a>',
                headers={"content-type": "text/html"},
            )
        if request.url.path == "/empty":
            response = httpx.Response(200, content=b'<a href="/from-empty.html">x</a>')
            response.headers.pop("content-type", None)
            return response
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler))
    assert "/from-text.html" not in requested
    assert "/from-404.html" not in requested
    assert "/from-empty.html" not in requested
    by_url = {item.url: item for item in report.results}
    assert by_url["https://example.test/gone.html"].outcome == "broken"
    assert by_url["https://example.test/gone.html"].status == 404
    assert by_url["https://example.test/notes.txt"].outcome == "ok"
    assert exit_code(report) == 1


def test_internal_redirect_and_failure_outcomes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return _html(
                '<a href="/old">old</a>'
                '<a href="/missing">missing</a>'
                '<a href="/nope">nope</a>'
                '<a href="/denied">denied</a>'
            )
        if path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        if path == "/new":
            return httpx.Response(200, content=b"ok")
        if path == "/missing":
            return httpx.Response(404)
        if path == "/denied":
            return httpx.Response(403)
        if path == "/nope":
            raise httpx.ConnectError("down")
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler), max_pages=1)
    by_url = {item.url: item for item in report.results}
    assert by_url["https://example.test/old"].outcome == "ok"
    assert by_url["https://example.test/old"].status == 200
    assert by_url["https://example.test/missing"].status == 404
    assert by_url["https://example.test/denied"].outcome == "broken"
    assert by_url["https://example.test/denied"].status == 403
    assert by_url["https://example.test/nope"].outcome == "broken"
    assert by_url["https://example.test/nope"].error is not None
    assert "ConnectError" in (by_url["https://example.test/nope"].error or "")
    assert exit_code(report) == 1


def test_crawl_transport_error_is_a_broken_internal_page() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("base down")

    report = _run(httpx.MockTransport(handler))
    assert report.pages_crawled == (BASE,)
    assert report.results[0].outcome == "broken"
    assert report.results[0].status is None
    assert exit_code(report) == 1


def test_external_head_fallback_and_warnings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "cdn.example":
            return _html(
                '<a href="https://cdn.example/ok">ok</a>'
                '<a href="https://cdn.example/warn">warn</a>'
                '<a href="https://cdn.example/limited">limited</a>'
                '<a href="https://cdn.example/missing">missing</a>'
                '<a href="https://cdn.example/head-405">fallback</a>'
                '<a href="https://cdn.example/head-500">server</a>'
                '<a href="https://cdn.example/flaky">flaky</a>'
                '<a href="https://cdn.example/down">down</a>'
            )
        path = request.url.path
        if path == "/ok":
            assert request.method == "HEAD"
            return httpx.Response(200)
        if path == "/warn":
            assert request.method == "HEAD"
            return httpx.Response(403)
        if path == "/limited":
            assert request.method == "HEAD"
            return httpx.Response(429)
        if path == "/missing":
            if request.method == "HEAD":
                return httpx.Response(404)
            return httpx.Response(404)
        if path == "/head-405":
            if request.method == "HEAD":
                return httpx.Response(405)
            return httpx.Response(201)
        if path == "/head-500":
            if request.method == "HEAD":
                return httpx.Response(500)
            return httpx.Response(200)
        if path == "/flaky":
            if request.method == "HEAD":
                raise httpx.ConnectError("head failed")
            return httpx.Response(200)
        if path == "/down":
            raise httpx.ConnectError("down")
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler), max_pages=1)
    by_path = {
        httpx.URL(item.url).path: item
        for item in report.results
        if item.kind == "external"
    }
    assert by_path["/ok"].outcome == "ok"
    assert by_path["/warn"] == LinkCheck(
        url="https://cdn.example/warn",
        kind="external",
        outcome="warn",
        status=403,
        error=None,
        sources=(BASE,),
    )
    assert by_path["/limited"].outcome == "warn"
    assert by_path["/limited"].status == 429
    assert by_path["/missing"].outcome == "broken"
    assert by_path["/missing"].status == 404
    assert by_path["/head-405"].outcome == "ok"
    assert by_path["/head-405"].status == 201
    assert by_path["/head-500"].outcome == "ok"
    assert by_path["/flaky"].outcome == "ok"
    assert by_path["/flaky"].status == 200
    assert by_path["/down"].outcome == "broken"
    assert by_path["/down"].status is None
    counts = report.counts()
    assert counts.warn == 2
    assert counts.broken_external == 2
    assert counts.broken_internal == 0
    assert exit_code(report) == 0


def test_external_redirect_on_head_is_ok() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.test":
            return _html('<a href="https://cdn.example/old">old</a>')
        if request.url.path == "/old":
            assert request.method == "HEAD"
            return httpx.Response(302, headers={"location": "https://cdn.example/new"})
        if request.url.path == "/new":
            assert request.method == "HEAD"
            return httpx.Response(200)
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler), max_pages=1)
    external = next(item for item in report.results if item.kind == "external")
    assert external.outcome == "ok"
    assert external.status == 200


def test_get_after_head_can_warn() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.test":
            return _html('<a href="https://cdn.example/asset">a</a>')
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(429)

    report = _run(httpx.MockTransport(handler), max_pages=1)
    external = next(item for item in report.results if item.kind == "external")
    assert external.outcome == "warn"
    assert external.status == 429
    assert exit_code(report) == 0


def test_sources_accumulate_across_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return _html('<a href="/a.html">a</a><a href="https://cdn.example/x">x</a>')
        if request.url.path == "/a.html":
            return _html('<a href="https://cdn.example/x">x</a>')
        assert request.method == "HEAD"
        return httpx.Response(200)

    report = _run(httpx.MockTransport(handler))
    external = next(item for item in report.results if item.kind == "external")
    assert external.sources == (BASE, "https://example.test/a.html")


def test_supplied_client_is_not_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "caller-agent"
        if request.url.path == "/":
            return _html("<p>home</p>")
        return httpx.Response(599)

    transport = httpx.MockTransport(handler)
    with httpx.Client(
        transport=transport,
        headers={"User-Agent": "caller-agent"},
    ) as client:
        report = check_links(BASE, client=client, max_pages=1, timeout=2.0)
        again = client.get(BASE)
    assert report.results[0].outcome == "ok"
    assert again.status_code == 200


def test_link_checks_are_bounded_by_concurrency() -> None:
    current = 0
    peak = 0
    release = threading.Event()
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal current, peak
        if request.url.host != "cdn.example":
            hrefs = "".join(
                f'<a href="https://cdn.example/{index}">x</a>' for index in range(4)
            )
            return _html(hrefs)
        with lock:
            current += 1
            peak = max(peak, current)
            if current >= 2:
                release.set()
        try:
            assert release.wait(2.0)
            return httpx.Response(204)
        finally:
            with lock:
                current -= 1

    report = _run(httpx.MockTransport(handler), max_pages=1, concurrency=2)
    assert peak == 2
    assert report.counts().ok == 5
    assert all(item.status == 204 for item in report.results if item.kind == "external")


def test_format_summary_uses_error_text_when_status_is_missing() -> None:
    report = LinkReport(
        base=BASE,
        pages_crawled=(BASE,),
        results=(
            LinkCheck(
                url="https://example.test/missing",
                kind="internal",
                outcome="broken",
                status=None,
                error=None,
                sources=(),
            ),
        ),
    )
    text = format_summary(report)
    assert "broken_internal: 1" in text
    assert "https://example.test/missing (error) from -" in text


def test_explicit_default_port_is_same_origin() -> None:
    from portfolio_qc.links import _origin

    assert _origin("https://example.test/docs") == ("https", "example.test", 443)
    assert _origin("https://example.test:443/docs") == ("https", "example.test", 443)
    assert _origin("http://example.test/docs") == ("http", "example.test", 80)
    assert _origin("mailto:dev@example.test") is None

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return _html('<a href="https://example.test:443/docs">docs</a>')
        if request.url.path == "/docs":
            return _html("<p>docs</p>")
        return httpx.Response(599)

    report = check_links(
        "https://example.test:443/",
        max_pages=5,
        timeout=2.0,
        transport=httpx.MockTransport(handler),
    )
    assert report.pages_crawled == (
        "https://example.test:443/",
        "https://example.test:443/docs",
    )
    assert report.counts().broken_internal == 0


def test_redirects_to_the_same_document_are_parsed_once() -> None:
    parsed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(
                301, headers={"location": "https://example.test/shared/"}
            )
        if request.url.path == "/b":
            return httpx.Response(
                301, headers={"location": "https://example.test/shared/"}
            )
        if request.url.path == "/shared/":
            parsed.append(str(request.url))
            return _html('<a href="/b">b</a><a href="/only-once.html">once</a>')
        if request.url.path == "/only-once.html":
            return _html("<p>once</p>")
        return httpx.Response(599)

    report = _run(httpx.MockTransport(handler), base="https://example.test/a")
    # /a and /b both redirect to /shared/, so the document is fetched twice,
    # but links are recorded from the first parse only.
    assert parsed == [
        "https://example.test/shared/",
        "https://example.test/shared/",
    ]
    once = next(item for item in report.results if item.url.endswith("/only-once.html"))
    assert once.sources == ("https://example.test/a",)
