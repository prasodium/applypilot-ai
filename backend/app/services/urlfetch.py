"""Safe, polite fetching of a user-provided job URL.

Rules: http(s) only; never touch private/loopback/link-local addresses (SSRF) unless the origin is explicitly allow-listed
(the local mock employer); obey robots.txt; no cookies or credentials; size/time limits; refuse login walls; re-validate every
redirect hop. When fetching is not permitted the caller gets a clear message and the user can paste the text instead.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx

from app.errors import Forbidden, Unprocessable

USER_AGENT = "ApplyPilotBot/0.1 (+local user-initiated fetch; respects robots.txt)"
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
OK_TYPES = ("text/html", "application/xhtml+xml", "application/ld+json", "text/plain")
LOGIN_HINTS = ("/login", "/signin", "/sign-in", "/sso", "/auth", "/account/login")


def _is_blocked_ip(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified


def assert_url_allowed(url: str, allow_origins: set[str]) -> tuple[str, str]:
    """Returns (scheme://host[:port], host). Raises Forbidden for anything unsafe."""
    p = urlparse(url)
    if p.scheme not in {"http", "https"} or not p.hostname:
        raise Forbidden("Only http(s) URLs can be imported.", code="bad_url")
    if p.username or p.password:
        raise Forbidden("URLs with embedded credentials are not accepted.", code="bad_url")
    origin = f"{p.scheme}://{p.netloc}"
    if origin in allow_origins:
        return origin, p.hostname
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise Unprocessable("The address could not be resolved.", code="unresolvable") from exc
    if not infos or any(_is_blocked_ip(i[4][0]) for i in infos):
        raise Forbidden("That address points to a private or local network and cannot be fetched.", code="blocked_address")
    return origin, p.hostname


def robots_allows(client: httpx.Client, origin: str, url: str) -> bool:
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = client.get(urljoin(origin, "/robots.txt"), timeout=5.0)
        if r.status_code in (401, 403):
            return False  # access restricted: treat as disallowed
        if r.status_code >= 400:
            return True  # no robots.txt: no restriction published
        rp.parse(r.text.splitlines())
    except httpx.HTTPError:
        return True
    return rp.can_fetch(USER_AGENT, url)


def fetch_page(url: str, *, allow_origins: set[str] | None = None, transport: httpx.BaseTransport | None = None) -> tuple[str, str]:
    """Returns (final_url, body_text). `allow_origins` are exempt from the private-address rule (mock employer only)."""
    allow = allow_origins or set()
    with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain"},
                      follow_redirects=False, timeout=10.0, transport=transport, trust_env=False, cookies=None) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            origin, _host = assert_url_allowed(current, allow)
            if origin not in allow and not robots_allows(client, origin, current):
                raise Forbidden("The site's robots.txt does not allow automated access to this page. "
                                "Paste the job text instead.", code="robots_disallowed")
            try:
                with client.stream("GET", current) as r:
                    if r.is_redirect:
                        loc = r.headers.get("location", "")
                        current = urljoin(current, loc)
                        continue
                    if r.status_code in (401, 403):
                        raise Forbidden("This page requires a login or blocks automated access. Paste the job text instead.",
                                        code="login_required")
                    if r.status_code >= 400:
                        raise Unprocessable(f"The page returned HTTP {r.status_code}.", code="fetch_failed")
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype and ctype not in OK_TYPES:
                        raise Unprocessable("That URL is not a web page.", code="unsupported_content")
                    if any(h in urlparse(str(r.url)).path.lower() for h in LOGIN_HINTS):
                        raise Forbidden("This looks like a login page. Paste the job text instead.", code="login_required")
                    chunks, size = [], 0
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise Unprocessable("The page is too large to import.", code="too_large")
                        chunks.append(chunk)
                    return str(r.url), b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
            except httpx.HTTPError as exc:
                raise Unprocessable("The page could not be fetched.", code="fetch_failed") from exc
        raise Unprocessable("Too many redirects.", code="too_many_redirects")
