"""Extract hrefs and srcs from HTML, classify them, and check them."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib.metadata import version
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

LinkKind = Literal["internal", "external"]
Outcome = Literal["ok", "warn", "broken"]
HttpMethod = Literal["GET", "HEAD"]

_HTTP_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
# Extensions that are fetched and checked, but not crawled as HTML pages.
_ASSET_SUFFIXES = frozenset(
    {
        ".css",
        ".js",
        ".mjs",
        ".cjs",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".ico",
        ".bmp",
        ".avif",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pdf",
        ".zip",
        ".gz",
        ".tgz",
        ".mp4",
        ".webm",
        ".mp3",
        ".wav",
        ".ogg",
        ".json",
        ".xml",
        ".txt",
        ".map",
        ".csv",
        ".webmanifest",
        ".wasm",
    }
)

DEFAULT_BASE = "https://scottn66.github.io"
# The public site is about 70 HTML pages; 200 leaves room for new reports.
DEFAULT_MAX_PAGES = 200
DEFAULT_TIMEOUT = 10.0
DEFAULT_CONCURRENCY = 4

_Status = tuple[Outcome, int | None, str | None]


@dataclass(frozen=True, slots=True)
class ClassifiedHref:
    """Absolute http(s) URL from an href or src, plus its internal or external kind."""

    href: str
    url: str
    kind: LinkKind


@dataclass(frozen=True, slots=True)
class LinkCheck:
    """The outcome of checking one absolute URL."""

    url: str
    kind: LinkKind
    outcome: Outcome
    status: int | None
    error: str | None
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LinkCounts:
    """Aggregate counts for a link-check run."""

    pages_crawled: int
    checked: int
    ok: int
    warn: int
    broken_internal: int
    broken_external: int


@dataclass(frozen=True, slots=True)
class LinkReport:
    """Pages crawled from a base URL and the links checked on those pages."""

    base: str
    pages_crawled: tuple[str, ...]
    results: tuple[LinkCheck, ...]

    def counts(self) -> LinkCounts:
        """Return page and outcome counts. Broken internal links fail the run."""
        ok = warn = broken_internal = broken_external = 0
        for item in self.results:
            if item.outcome == "ok":
                ok += 1
            elif item.outcome == "warn":
                warn += 1
            elif item.kind == "internal":
                broken_internal += 1
            else:
                broken_external += 1
        return LinkCounts(
            pages_crawled=len(self.pages_crawled),
            checked=len(self.results),
            ok=ok,
            warn=warn,
            broken_internal=broken_internal,
            broken_external=broken_external,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping of this report."""
        counts = self.counts()
        return {
            "base": self.base,
            "pages_crawled": list(self.pages_crawled),
            "counts": {
                "pages_crawled": counts.pages_crawled,
                "checked": counts.checked,
                "ok": counts.ok,
                "warn": counts.warn,
                "broken_internal": counts.broken_internal,
                "broken_external": counts.broken_external,
            },
            "results": [
                {
                    "url": item.url,
                    "kind": item.kind,
                    "outcome": item.outcome,
                    "status": item.status,
                    "error": item.error,
                    "sources": list(item.sources),
                }
                for item in self.results
            ],
        }


class _RefParser(HTMLParser):
    """Collect raw href and src values from element start tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is not None and name.lower() in {"href", "src"}:
                self.refs.append(value)


def classify_hrefs(html: str, base_url: str) -> list[ClassifiedHref]:
    """Return deduped absolute links from ``html``, classified against ``base_url``.

    ``href`` and ``src`` attributes are both collected. Relative values are
    resolved with ``base_url``. Fragments are removed, the scheme and host are
    lowercased, and an empty path becomes ``/``. Non-http(s) values, including
    ``javascript:`` and ``mailto:``, and blank values are omitted. A link is
    internal when its hostname matches the base URL's hostname.
    """
    base = urlsplit(base_url)
    if base.scheme.lower() not in _HTTP_SCHEMES or base.hostname is None:
        raise ValueError(f"base_url must be an absolute http(s) URL, got {base_url!r}")

    base_host = base.hostname.lower()
    parser = _RefParser()
    parser.feed(html)
    parser.close()

    seen: set[str] = set()
    classified: list[ClassifiedHref] = []
    for raw in parser.refs:
        href = raw.strip()
        if not href:
            continue
        normalized = _normalize(urljoin(base_url, href))
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        host = urlsplit(normalized).hostname
        kind: LinkKind = "internal" if host == base_host else "external"
        classified.append(ClassifiedHref(href=href, url=normalized, kind=kind))
    return classified


def _normalize(url: str) -> str | None:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _HTTP_SCHEMES or parts.hostname is None:
        return None
    path = parts.path or "/"
    return urlunsplit((scheme, parts.netloc.lower(), path, parts.query, ""))


def _dispatch(
    client: httpx.Client,
    url: str,
    *,
    method: HttpMethod,
    follow_redirects: bool,
) -> httpx.Response:
    if method == "GET" and not follow_redirects:
        return client.get(url)
    return client.request(method, url, follow_redirects=follow_redirects)


def fetch_status(
    url: str,
    *,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
    follow_redirects: bool = False,
    method: HttpMethod = "GET",
) -> int:
    """Return the status code for ``url``.

    ``timeout`` is seconds and applies when this function builds the client.
    A caller-supplied ``client`` is used as-is and is not closed. Redirects are
    followed only when ``follow_redirects`` is true. ``method`` is ``GET`` or
    ``HEAD``.
    """
    if client is not None:
        response = _dispatch(
            client, url, method=method, follow_redirects=follow_redirects
        )
        return response.status_code
    with httpx.Client(timeout=timeout) as owned:
        response = _dispatch(
            owned, url, method=method, follow_redirects=follow_redirects
        )
        return response.status_code


def user_agent() -> str:
    """Return the polite User-Agent sent when this package builds the client."""
    return (
        f"portfolio-qc/{version('portfolio-qc')} "
        "(+https://github.com/scottn66/portfolio)"
    )


def build_client(
    *,
    timeout: float,
    concurrency: int,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    """Build the shared client used to crawl and check links.

    Connection count is capped at ``concurrency``. The client does not read
    proxy variables, so tests and the checker share one request path.
    """
    return httpx.Client(
        transport=transport,
        timeout=timeout,
        headers={"User-Agent": user_agent()},
        limits=httpx.Limits(
            max_connections=concurrency,
            max_keepalive_connections=concurrency,
        ),
        follow_redirects=False,
        trust_env=False,
    )


def _origin(url: str) -> tuple[str, str, int] | None:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _HTTP_SCHEMES or parts.hostname is None:
        return None
    port = parts.port
    if port is None:
        port = _DEFAULT_PORTS[scheme]
    return scheme, parts.hostname.lower(), port


def _is_page_url(url: str) -> bool:
    path = urlsplit(url).path
    if path.endswith("/"):
        return True
    leaf = path.rsplit("/", 1)[-1]
    if "." not in leaf:
        return True
    suffix = "." + leaf.rsplit(".", 1)[-1].lower()
    return suffix not in _ASSET_SUFFIXES


def _is_html(response: httpx.Response) -> bool:
    return "html" in response.headers.get("content-type", "").lower()


def _error_text(exc: httpx.HTTPError) -> str:
    return f"{type(exc).__name__}: {exc}"


def _try_status(
    client: httpx.Client,
    url: str,
    method: HttpMethod,
) -> tuple[int | None, str | None]:
    try:
        status = fetch_status(
            client=client, url=url, method=method, follow_redirects=True
        )
    except httpx.HTTPError as exc:
        return None, _error_text(exc)
    return status, None


def _classify_internal(client: httpx.Client, url: str) -> _Status:
    status, error = _try_status(client, url, "GET")
    if error is not None or status is None:
        return "broken", status, error
    if status == 200:
        return "ok", status, None
    return "broken", status, None


def _classify_external(client: httpx.Client, url: str) -> _Status:
    """HEAD, then GET unless HEAD already returned 2xx, 403, or 429.

    403 and 429 are warnings. They do not fail the process. Any other final
    status outside 2xx is a broken external link, which is reported and still
    does not fail the process.
    """
    status, error = _try_status(client, url, "HEAD")
    needs_get = (
        error is not None
        or status is None
        or (status not in (403, 429) and not 200 <= status < 300)
    )
    if needs_get:
        status, error = _try_status(client, url, "GET")
    if error is not None or status is None:
        return "broken", status, error
    if status in (403, 429):
        return "warn", status, None
    if 200 <= status < 300:
        return "ok", status, None
    return "broken", status, None


@dataclass(slots=True)
class _Found:
    kind: LinkKind
    sources: list[str]


def _validate_limits(max_pages: int, concurrency: int, timeout: float) -> None:
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if timeout <= 0:
        raise ValueError("timeout must be positive")


def check_links(
    base_url: str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    timeout: float = DEFAULT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
    client: httpx.Client | None = None,
    transport: httpx.BaseTransport | None = None,
) -> LinkReport:
    """Crawl same-origin HTML pages and check the links they contain.

    The crawl starts at ``base_url`` and stops after ``max_pages`` HTML-like
    URLs. Same-origin means the scheme, host, and port of the base URL.
    Internal links must return status 200 after redirects. External links are
    checked with HEAD, falling back to GET, and 403 or 429 is a warning.
    At most ``concurrency`` link checks run at once. A client this function
    creates sends :func:`user_agent` and is closed before returning. A
    caller-supplied ``client`` is used as-is and is not closed.
    """
    _validate_limits(max_pages, concurrency, timeout)
    if client is not None and transport is not None:
        raise ValueError("pass client or transport, not both")
    normalized = _normalize(base_url)
    if normalized is None:
        raise ValueError(f"base_url must be an absolute http(s) URL, got {base_url!r}")
    origin = _origin(normalized)
    assert origin is not None

    owns_client = client is None
    active = (
        client
        if client is not None
        else build_client(
            timeout=timeout,
            concurrency=concurrency,
            transport=transport,
        )
    )
    try:
        return _crawl(
            active,
            base=normalized,
            origin=origin,
            max_pages=max_pages,
            concurrency=concurrency,
        )
    finally:
        if owns_client:
            active.close()


def _crawl(
    client: httpx.Client,
    *,
    base: str,
    origin: tuple[str, str, int],
    max_pages: int,
    concurrency: int,
) -> LinkReport:
    queue: list[str] = [base]
    seen_pages = {base}
    crawled: list[str] = []
    page_status: dict[str, tuple[int | None, str | None]] = {}
    found: dict[str, _Found] = {}
    found_order: list[str] = []
    parsed_finals: set[str] = set()

    def enqueue(url: str) -> None:
        if url in seen_pages:
            return
        if _origin(url) != origin or not _is_page_url(url):
            return
        seen_pages.add(url)
        queue.append(url)

    while queue and len(crawled) < max_pages:
        page = queue.pop(0)
        crawled.append(page)
        try:
            response = _dispatch(client, page, method="GET", follow_redirects=True)
        except httpx.HTTPError as exc:
            page_status[page] = (None, _error_text(exc))
            continue
        page_status[page] = (response.status_code, None)
        if response.status_code != 200 or not _is_html(response):
            continue
        final = _normalize(str(response.url))
        if final is None or final in parsed_finals:
            continue
        parsed_finals.add(final)
        for link in classify_hrefs(response.text, final):
            slot = found.get(link.url)
            if slot is None:
                found[link.url] = _Found(kind=link.kind, sources=[page])
                found_order.append(link.url)
            elif page not in slot.sources:
                slot.sources.append(page)
            enqueue(link.url)

    ordered: list[str] = []
    seen: set[str] = set()
    for page in crawled:
        ordered.append(page)
        seen.add(page)
    for url in found_order:
        if url not in seen:
            ordered.append(url)
            seen.add(url)

    pending = [url for url in ordered if url not in page_status]
    checked = _check_pending(client, pending, found, concurrency)

    results: list[LinkCheck] = []
    for url in ordered:
        if url in page_status:
            status, error = page_status[url]
            outcome: Outcome = "ok" if error is None and status == 200 else "broken"
            sources = tuple(found[url].sources) if url in found else ()
            results.append(
                LinkCheck(
                    url=url,
                    kind="internal",
                    outcome=outcome,
                    status=status,
                    error=error,
                    sources=sources,
                )
            )
        else:
            results.append(checked[url])
    return LinkReport(base=base, pages_crawled=tuple(crawled), results=tuple(results))


def _check_pending(
    client: httpx.Client,
    pending: list[str],
    found: dict[str, _Found],
    concurrency: int,
) -> dict[str, LinkCheck]:
    if not pending:
        return {}
    kinds = {url: found[url].kind for url in pending}
    sources = {url: tuple(found[url].sources) for url in pending}

    def one(url: str) -> LinkCheck:
        classify: Callable[[httpx.Client, str], _Status]
        classify = (
            _classify_internal if kinds[url] == "internal" else _classify_external
        )
        outcome, status, error = classify(client, url)
        return LinkCheck(
            url=url,
            kind=kinds[url],
            outcome=outcome,
            status=status,
            error=error,
            sources=sources[url],
        )

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        return dict(zip(pending, executor.map(one, pending), strict=True))


def exit_code(report: LinkReport) -> int:
    """Return 1 when any internal link is broken, otherwise 0."""
    return 1 if report.counts().broken_internal else 0


def format_summary(report: LinkReport) -> str:
    """Return a short human-readable summary, including broken internal links."""
    counts = report.counts()
    lines = [
        f"base: {report.base}",
        f"pages_crawled: {counts.pages_crawled}",
        f"checked: {counts.checked}",
        f"ok: {counts.ok}",
        f"warn: {counts.warn}",
        f"broken_internal: {counts.broken_internal}",
        f"broken_external: {counts.broken_external}",
    ]
    broken = [
        item
        for item in report.results
        if item.kind == "internal" and item.outcome == "broken"
    ]
    if broken:
        lines.append("broken internal:")
        for item in broken:
            if item.status is not None:
                detail = str(item.status)
            else:
                detail = item.error or "error"
            where = ", ".join(item.sources) if item.sources else "-"
            lines.append(f"  {item.url} ({detail}) from {where}")
    return "\n".join(lines) + "\n"
