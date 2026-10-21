"""Page analysis: form fields, navigation buttons, challenges and submission outcomes.

Page content is untrusted DATA. Nothing here reads instructions from a page: hidden text, comments and alt text are ignored, and
only structural facts (controls, labels, attributes) are extracted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from playwright.async_api import Page

_EXTRACT_JS = r"""
() => {
  const text = n => (n && n.textContent || '').replace(/\s+/g, ' ').trim();
  const shown = el => {
    if (el.closest('[hidden],[aria-hidden="true"]')) return false;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
    }
    if (el.type === 'file') return true;
    const r = el.getBoundingClientRect();
    return (r.width > 0 || r.height > 0) && r.right > 0 && r.bottom > 0 && r.left < innerWidth + 5000;
  };
  const labelOf = el => {
    if (el.labels && el.labels.length) return text(el.labels[0]);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(i => text(document.getElementById(i))).join(' ').trim(); if (t) return t; }
    const al = el.getAttribute('aria-label'); if (al) return al.trim();
    if (el.placeholder) return el.placeholder;
    return el.name || el.id || '';
  };
  const sel = el => el.id ? '#' + CSS.escape(el.id) : (el.name ? el.tagName.toLowerCase() + '[name="' + CSS.escape(el.name) + '"]' : '');
  const root = [...document.forms].find(f => shown(f)) || document.body;
  const out = [], seenRadio = new Set();
  root.querySelectorAll('input, select, textarea').forEach((el, i) => {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image'].includes(type) || el.disabled || !shown(el)) return;
    if (el.closest('[data-challenge]') || el.name === 'human_check') return;  // challenge widgets are never form fields
    const key = el.name || el.id || ('field-' + i);
    if (type === 'radio') {
      if (seenRadio.has(el.name)) return;
      seenRadio.add(el.name);
      const group = [...root.querySelectorAll('input[type=radio]')].filter(r => r.name === el.name);
      const fs = el.closest('fieldset');
      const legend = fs && fs.querySelector('legend');
      out.push({key, selector: 'input[type="radio"][name="' + CSS.escape(el.name) + '"]', type: 'radio',
        label: legend ? text(legend) : labelOf(el), required: group.some(r => r.required) || el.getAttribute('aria-required') === 'true',
        options: group.map(r => labelOf(r) || r.value), values: group.map(r => r.value), maxLength: null,
        value: (group.find(r => r.checked) || {}).value || ''});
      return;
    }
    let options = [];
    if (el.tagName === 'SELECT') options = [...el.options].filter(o => o.value !== '' && !o.disabled).map(o => text(o));
    const label = labelOf(el);
    out.push({key, selector: sel(el), type: el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : type,
      label, required: el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label),
      options, values: [], maxLength: el.maxLength > 0 ? el.maxLength : null,
      value: type === 'checkbox' ? (el.checked ? 'yes' : '') : (type === 'file' ? '' : (el.value || ''))});
  });
  return out;
}
"""

_PAGE_FLAGS_JS = r"""
() => {
  const t = (document.body.innerText || '').toLowerCase();
  return {
    text: t.slice(0, 4000),
    title: document.title || '',
    hasChallengeEl: !!document.querySelector('[data-challenge], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], .g-recaptcha, .h-captcha, .cf-turnstile'),
    hasPassword: !!document.querySelector('input[type=password]'),
    errors: [...document.querySelectorAll('[role=alert] li, .error, [aria-invalid=true] ~ .error, .field-error')].map(e => (e.textContent || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 20),
    invalidCount: document.querySelectorAll('[aria-invalid="true"]').length,
    reference: (document.querySelector('[data-testid="confirmation-ref"]') || {}).textContent || '',
    url: location.href,
  };
}
"""


@dataclass
class FormField:
    key: str
    selector: str
    field_type: str
    label: str
    required: bool = False
    options: list[str] = field(default_factory=list)
    option_values: list[str] = field(default_factory=list)
    max_length: int | None = None
    value: str = ""
    step_index: int = 0


class Challenge(StrEnum):
    NONE = "none"
    HUMAN_VERIFICATION = "human_verification"
    LOGIN_REQUIRED = "login_required"
    EMAIL_VERIFICATION = "email_verification"
    ACCOUNT_CREATION = "account_creation"


class Outcome(StrEnum):
    CONFIRMED = "confirmed"
    VALIDATION_ERRORS = "validation_errors"
    CHALLENGE = "challenge"
    SESSION_EXPIRED = "session_expired"
    AMBIGUOUS = "ambiguous"


async def extract_fields(page: Page, step_index: int = 0) -> list[FormField]:
    raw = await page.evaluate(_EXTRACT_JS)
    out: list[FormField] = []
    for r in raw:
        label = re.sub(r"\s*\*\s*$", "", r["label"]).strip()
        out.append(FormField(key=r["key"], selector=r["selector"], field_type=r["type"], label=label[:1000], required=bool(r["required"]),
                             options=[o for o in r["options"] if o], option_values=r.get("values", []), max_length=r["maxLength"],
                             value=r["value"], step_index=step_index))
    return out


async def page_flags(page: Page) -> dict:
    return await page.evaluate(_PAGE_FLAGS_JS)


_HUMAN = re.compile(r"verify (that )?you('| a)re (a )?human|i am not a robot|i'm not a robot|captcha|unusual traffic|are you a robot", re.I)
_LOGIN = re.compile(r"session (has )?expired|please (sign|log) in|sign in to continue|log in to continue|you must be logged in|login required", re.I)
_EMAIL = re.compile(r"verify your e-?mail|confirm your e-?mail|enter the (6-digit )?code (we )?sent|check your inbox", re.I)
_ACCOUNT = re.compile(r"create an account to (apply|continue)|register to apply|sign up to apply", re.I)


def detect_challenge(flags: dict) -> Challenge:
    """Challenges are DETECTED so the workflow can pause for the human. Nothing here attempts to solve or bypass them."""
    text = flags["text"]
    if flags["hasChallengeEl"] or _HUMAN.search(text):
        return Challenge.HUMAN_VERIFICATION
    if _EMAIL.search(text):
        return Challenge.EMAIL_VERIFICATION
    if _ACCOUNT.search(text):
        return Challenge.ACCOUNT_CREATION
    if _LOGIN.search(text) or (flags["hasPassword"] and re.search(r"sign in|log in", text)):
        return Challenge.LOGIN_REQUIRED
    return Challenge.NONE


_SUCCESS = re.compile(r"application (has been |was )?(received|submitted|sent)|thank you for (applying|your application)|successfully submitted", re.I)


def classify_outcome(flags: dict, http_status: int | None = None) -> tuple[Outcome, dict]:
    """Explicit success needs BOTH success wording AND a confirmation reference/marker. Anything vaguer is AMBIGUOUS."""
    ch = detect_challenge(flags)
    if ch == Challenge.HUMAN_VERIFICATION:
        return Outcome.CHALLENGE, {"challenge": ch.value}
    if ch in {Challenge.LOGIN_REQUIRED, Challenge.EMAIL_VERIFICATION, Challenge.ACCOUNT_CREATION} or http_status in (401, 403):
        return Outcome.SESSION_EXPIRED, {"challenge": ch.value, "http_status": http_status}
    ref = (flags.get("reference") or "").strip()
    if _SUCCESS.search(flags["text"]) and ref:
        return Outcome.CONFIRMED, {"reference": ref[:100]}
    if flags["errors"] or flags["invalidCount"]:
        return Outcome.VALIDATION_ERRORS, {"errors": flags["errors"][:10]}
    return Outcome.AMBIGUOUS, {"note": "The page did not clearly confirm or reject the submission."}


async def find_buttons(page: Page):
    """Returns (next_button | None, submit_button | None) among visible, enabled controls."""
    async def first(selector: str):
        loc = page.locator(selector)
        for i in range(await loc.count()):
            el = loc.nth(i)
            if await el.is_visible() and await el.is_enabled():
                return el
        return None

    nxt = await first('button[data-action="next"], button:text-matches("^\\\\s*(next|continue|save and continue)\\\\s*$", "i")')
    sub = await first('button[type="submit"]:text-matches("submit|apply|send", "i"), input[type="submit"][value*="ubmit" i], button:text-matches("^\\\\s*(submit|apply)( application)?\\\\s*$", "i")')
    return nxt, sub
