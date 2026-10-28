"""Extract hrefs from HTML and classify them against a base URL."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

LinkKind = Literal["internal", "external"]

_HTTP_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class ClassifiedHref:
    """An absolute http(s) URL taken from an href, and how it relates to the base host."""

    href: str
    url: str
    kind: LinkKind


class _AnchorParser(HTMLParser):
    """Collect raw href values from anchor start tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value is not None:
                self.hrefs.append(value)


def classify_hrefs(html: str, base_url: str) -> list[ClassifiedHref]:
    """Return deduped absolute links from ``html``, classified against ``base_url``.

    Relative hrefs are resolved with ``base_url``. Fragments are removed, the
    scheme and host are lowercased, and an empty path becomes ``/``. Non-http(s)
    hrefs, including ``javascript:`` and ``mailto:``, and blank hrefs are omitted.
    A link is internal when its hostname matches the base URL's hostname.
    """
    base = urlsplit(base_url)
    if base.scheme.lower() not in _HTTP_SCHEMES or base.hostname is None:
        raise ValueError(f"base_url must be an absolute http(s) URL, got {base_url!r}")

    base_host = base.hostname.lower()
    parser = _AnchorParser()
    parser.feed(html)
    parser.close()

    seen: set[str] = set()
    classified: list[ClassifiedHref] = []
    for raw in parser.hrefs:
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


def fetch_status(
    url: str,
    *,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> int:
    """GET ``url`` and return the status code.

    ``timeout`` is seconds and applies when this function builds the client.
    A caller-supplied ``client`` is used as-is and is not closed. Redirects are
    not followed.
    """
    if client is not None:
        return client.get(url).status_code
    with httpx.Client(timeout=timeout) as owned:
        return owned.get(url).status_code
