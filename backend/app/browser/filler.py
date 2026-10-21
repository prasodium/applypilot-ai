"""Form filling with per-action verification, checkpoints and cooperative pause/cancel.

For every field: confirm the field meaning (label from the DOM), take the value ONLY from the resolver (which only returns
profile-supported or user-approved answers), perform the action, READ THE VALUE BACK, checkpoint, record a safe audit event
(field key + type, never the value). Legal checkboxes are filled only when the resolver says the user explicitly provided the answer.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from app.browser.pages import (
    Challenge,
    FormField,
    Outcome,
    classify_outcome,
    detect_challenge,
    extract_fields,
    find_buttons,
    page_flags,
)

FILE_MARKER = re.compile(r"^\[FILE:(\w+)\]$")


@dataclass
class Resolved:
    value: str | None  # None: cannot be filled automatically
    reason: str = ""


class Resolver(Protocol):
    async def resolve(self, fields: list[FormField], step_index: int) -> dict[str, Resolved]: ...


@dataclass
class FillResult:
    status: Literal["ready", "needs_input", "challenge", "validation_failed", "paused", "cancelled", "error"]
    steps: int = 0
    filled: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # labels of required fields that need the user
    challenge: str = ""
    errors: list[str] = field(default_factory=list)
    reason: str = ""


Checkpoint = Callable[[str, str, bool], Awaitable[None]]
ShouldStop = Callable[[], Awaitable[str]]  # "", "pause" or "cancel"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\r\n", "\n")).strip()


async def fill_field(page: Page, f: FormField, value: str, files: dict[str, str]) -> tuple[bool, str]:
    """Performs one action and verifies it by reading the value back. Returns (ok, reason)."""
    try:
        t = f.field_type
        if t == "file":
            m = FILE_MARKER.match(value)
            path = files.get(m.group(1)) if m else None
            if not path:
                return False, "no_file_available"
            loc = page.locator(f.selector).first
            await loc.set_input_files(path)
            name = await loc.evaluate("el => el.files && el.files[0] ? el.files[0].name : ''")
            return (bool(name), "" if name else "upload_not_confirmed")
        if t == "radio":
            group = page.locator(f.selector)
            for i in range(await group.count()):
                r = group.nth(i)
                lab = await r.evaluate("el => (el.labels && el.labels[0] ? el.labels[0].textContent : el.value) || ''")
                if _norm(lab).lower() == value.strip().lower() or (await r.get_attribute("value") or "").lower() == value.strip().lower():
                    await r.check()
                    return (await r.is_checked(), "" if await r.is_checked() else "radio_not_checked")
            return False, "option_not_found"
        loc = page.locator(f.selector).first
        if t == "checkbox":
            want = value.strip().lower() in {"yes", "true", "1", "checked", "on"}
            await (loc.check() if want else loc.uncheck())
            return (await loc.is_checked()) == want, "" if (await loc.is_checked()) == want else "checkbox_mismatch"
        if t == "select":
            try:
                await loc.select_option(label=value)
            except PlaywrightError:
                await loc.select_option(value=value)
            chosen = await loc.evaluate("el => el.selectedOptions[0] ? el.selectedOptions[0].textContent : ''")
            ok = _norm(chosen).lower() == value.strip().lower() or (await loc.input_value()).lower() == value.strip().lower()
            return ok, "" if ok else "select_mismatch"
        await loc.fill(value)
        got = await loc.input_value()
        ok = _norm(got) == _norm(value)
        return ok, "" if ok else "readback_mismatch"
    except (PlaywrightError, PlaywrightTimeout) as exc:
        return False, f"action_failed:{type(exc).__name__}"


async def _click_and_wait(page: Page, button) -> int | None:
    """Clicks and waits for navigation if one happens. Returns the HTTP status of the resulting document, if any."""
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=10000) as nav:
            await button.click()
        resp = await nav.value
        return resp.status if resp else None
    except PlaywrightTimeout:
        await page.wait_for_timeout(300)  # a client-side step change without navigation
        return None


async def fill_form(page: Page, url: str, *, resolver: Resolver, files: dict[str, str], checkpoint: Checkpoint,
                    should_stop: ShouldStop, max_steps: int = 8) -> FillResult:
    """Walks the form step by step, filling what can be filled and stopping at the final step WITHOUT submitting."""
    resp = await page.goto(url, wait_until="domcontentloaded")
    if resp is not None and resp.status in (401, 403):
        return FillResult("challenge", challenge=Challenge.LOGIN_REQUIRED.value, reason=f"http_{resp.status}")
    await checkpoint("opened form", "", True)
    result = FillResult("error")
    for step in range(max_steps):
        stop = await should_stop()  # honour pause/cancel at the start of every step, not only between fields
        if stop:
            return FillResult("paused" if stop == "pause" else "cancelled", steps=step, filled=result.filled)
        flags = await page_flags(page)
        ch = detect_challenge(flags)
        if ch != Challenge.NONE:
            return FillResult("challenge", steps=step, filled=result.filled, challenge=ch.value)
        fields = await extract_fields(page, step)
        nxt, sub = await find_buttons(page)
        if not fields and not nxt and not sub:
            return FillResult("error", steps=step, filled=result.filled, reason="no_form_found")
        resolved = await resolver.resolve(fields, step)
        missing = [f.label for f in fields if f.required and (resolved.get(f.key) is None or resolved[f.key].value in (None, ""))]
        if missing:
            return FillResult("needs_input", steps=step, filled=result.filled, missing=missing, reason="required_answers_missing")
        for f in fields:
            stop = await should_stop()
            if stop:
                return FillResult("paused" if stop == "pause" else "cancelled", steps=step, filled=result.filled)
            r = resolved.get(f.key)
            if r is None or r.value in (None, ""):
                continue  # optional field without a verified answer: left blank on purpose
            ok, reason = await fill_field(page, f, r.value, files)
            await checkpoint(f"filled field '{f.key}' ({f.field_type})", reason, ok)
            if not ok:
                return FillResult("error", steps=step, filled=result.filled, reason=f"{reason} on field '{f.key}'")
            result.filled.append(f.key)
        if nxt is not None:
            stop = await should_stop()
            if stop:
                return FillResult("paused" if stop == "pause" else "cancelled", steps=step, filled=result.filled)
            status = await _click_and_wait(page, nxt)
            flags = await page_flags(page)
            ch = detect_challenge(flags)
            if ch != Challenge.NONE or status in (401, 403):
                return FillResult("challenge", steps=step + 1, filled=result.filled, challenge=(ch if ch != Challenge.NONE else Challenge.LOGIN_REQUIRED).value)
            if flags["errors"] or flags["invalidCount"]:
                return FillResult("validation_failed", steps=step + 1, filled=result.filled, errors=flags["errors"][:10])
            await checkpoint(f"completed step {step + 1}", "", True)
            continue
        if sub is not None:
            await checkpoint("reached final step (not submitted)", "", True)
            return FillResult("ready", steps=step + 1, filled=result.filled)
        return FillResult("error", steps=step, filled=result.filled, reason="no_next_or_submit_control")
    return FillResult("error", steps=max_steps, filled=result.filled, reason="too_many_steps")


async def click_submit(page: Page) -> tuple[Outcome, dict]:
    """Clicks the final submit control ONCE and classifies the resulting page. Never retries."""
    _, sub = await find_buttons(page)
    if sub is None:
        return Outcome.AMBIGUOUS, {"note": "submit control not found"}
    status = await _click_and_wait(page, sub)
    return classify_outcome(await page_flags(page), status)


_ = asyncio
