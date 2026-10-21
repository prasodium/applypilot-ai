"""Deterministic mock AI provider for tests and demo mode (no API key needed).

It builds text ONLY from the confirmed facts it is given, so it can never invent employers, dates or outcomes. It cannot
write motivation/"why us" answers (there are no verified facts about feelings) and reports that as missing information.
Everything it produces is labelled DEMO by the callers.
"""
from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from app.ai.provider import ProviderError
from app.ai.schemas import CoverLetterOut, CoverLetterParagraph, FreeTextAnswerOut

T = TypeVar("T", bound=BaseModel)
_STOP = set("a an and are as at be by do for from have how in is it of on or our that the this to we what when where which who why will with you your about tell us me my describe give example".split())


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#.]{2,}", (s or "").lower()) if t not in _STOP}


def _rank(facts: list[dict], keywords: set[str], kinds: set[str]) -> list[tuple[int, dict]]:
    scored = []
    for f in facts:
        if f["kind"] not in kinds:
            continue
        overlap = len(_tokens(f["text"]) & keywords)
        scored.append((overlap, f))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return scored


def _fit(text: str, word_limit: int | None, char_limit: int | None) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out: list[str] = []
    for s in sentences:
        cand = " ".join([*out, s])
        if (word_limit and len(cand.split()) > word_limit) or (char_limit and len(cand) > char_limit):
            break
        out.append(s)
    if not out and sentences:  # even the first sentence is too long: hard cut at a word boundary
        words = sentences[0].split()
        while words and ((word_limit and len(words) > word_limit) or (char_limit and len(" ".join(words)) > char_limit)):
            words.pop()
        return " ".join(words)
    return " ".join(out)


class MockProvider:
    name = "mock"
    is_demo = True

    def generate(self, task: str, payload: dict, schema: type[T]) -> T:
        if task == "cover_letter" and schema is CoverLetterOut:
            return self._cover_letter(payload)  # type: ignore[return-value]
        if task == "free_text_answer" and schema is FreeTextAnswerOut:
            return self._free_text(payload)  # type: ignore[return-value]
        raise ProviderError(f"Mock provider does not implement task '{task}'")

    # ------------------------------------------------------------------ tasks
    def _cover_letter(self, p: dict) -> CoverLetterOut:
        job, facts = p["job"], p["facts"]
        company, title = job.get("company") or "the company", job.get("title") or "this role"
        want = {s.lower() for s in p.get("required_skills", [])}
        paras = [CoverLetterParagraph(text=f"Dear {company} hiring team,\n\nI am writing to apply for the {title} position at {company}.")]

        skills = [f for f in facts if f["kind"] == "skill"]
        matched = [f for f in skills if f["label"].lower() in want]
        if matched:
            paras.append(CoverLetterParagraph(
                text="My profile lists these skills that match your requirements: " + ", ".join(f["label"] for f in matched) + ".",
                source_fact_ids=[f["id"] for f in matched]))

        kw = want | _tokens(title)
        for _, f in [x for x in _rank(facts, kw, {"experience"}) if x[0] > 0][:2]:
            fl = f.get("fields", {})
            line = f"At {fl.get('employer', 'a previous employer')}, I worked as {fl.get('title', 'a team member')}."
            detail = (fl.get("achievements") or fl.get("responsibilities") or [""])[0]
            if detail:
                line += f" {detail.rstrip('.')}."
            paras.append(CoverLetterParagraph(text=line, source_fact_ids=[f["id"]]))

        proj = [x for x in _rank(facts, kw, {"project"}) if x[0] > 0][:1]
        for _, f in proj:
            fl = f.get("fields", {})
            line = f"I also built {fl.get('name', 'a project')}"
            line += f": {fl['summary'].rstrip('.')}." if fl.get("summary") else "."
            paras.append(CoverLetterParagraph(text=line, source_fact_ids=[f["id"]]))

        paras.append(CoverLetterParagraph(text="Thank you for considering my application. I would welcome the chance to discuss it further.\n\nSincerely,\n" + p["candidate"].get("name", "")))
        return CoverLetterOut(paragraphs=paras)

    def _free_text(self, p: dict) -> FreeTextAnswerOut:
        qtype = p.get("question_type", "other")
        facts = p.get("facts", [])
        if qtype == "motivation":
            return FreeTextAnswerOut(missing_information=True, confidence="low",
                                     missing_reason="There are no verified facts about your motivation for this role or company. Please write this answer yourself.")
        question = p.get("untrusted", {}).get("question", "")
        kw = _tokens(question)  # only what the QUESTION asks about; the job's skills must not make unrelated questions "answerable"
        ranked = [x for x in _rank(facts, kw, {"project", "experience"}) if x[0] > 0]
        if not ranked:
            return FreeTextAnswerOut(missing_information=True, confidence="low",
                                     missing_reason="None of your confirmed projects or experience match this question. Please answer it yourself.")
        ids, parts = [], []
        for _, f in ranked[:2]:
            fl = f.get("fields", {})
            ids.append(f["id"])
            if f["kind"] == "project":
                s = f"In my project {fl.get('name')}, {fl.get('summary', '').rstrip('.')}."
                if fl.get("contribution"):
                    s += f" My contribution: {fl['contribution'].rstrip('.')}."
                if fl.get("results"):
                    s += f" Results: {'; '.join(fl['results'])}."
            else:
                s = f"As {fl.get('title')} at {fl.get('employer')}, " + (
                    (fl.get("achievements") or fl.get("responsibilities") or ["I worked on related tasks"])[0].rstrip(".") + ".")
            parts.append(s.replace(", .", ".").replace("  ", " "))
        text = _fit(" ".join(parts), p.get("word_limit"), p.get("char_limit"))
        return FreeTextAnswerOut(answer=text, source_fact_ids=ids, confidence="medium")
