"""Browser session: headless-by-default Chromium, ephemeral profile (no cookies persisted), and a network guard that aborts any
request leaving the allowed origin, so a page can neither pull in third-party code nor receive data elsewhere. No stealth plugins,
no fingerprint tricks, no anti-bot evasion: this is plain Playwright."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright

from app.config import Settings


@asynccontextmanager
async def browser_session(settings: Settings, allowed_origin: str) -> AsyncIterator[Page]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.browser_headless)
        context = await browser.new_context(accept_downloads=False, viewport={"width": 1100, "height": 900}, locale="en-US",
                                            service_workers="block")

        async def guard(route):
            u = urlparse(route.request.url)
            if u.scheme in {"data", "about", "blob"} or f"{u.scheme}://{u.netloc}" == allowed_origin:
                await route.continue_()
            else:
                await route.abort("blockedbyclient")

        await context.route("**/*", guard)
        context.set_default_timeout(8000)
        context.set_default_navigation_timeout(15000)
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()
