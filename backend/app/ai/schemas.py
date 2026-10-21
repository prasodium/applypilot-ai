"""Structured outputs the model must return. All model output is validated against these before use."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CoverLetterParagraph(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    source_fact_ids: list[str] = []


class CoverLetterOut(BaseModel):
    paragraphs: list[CoverLetterParagraph] = Field(min_length=1, max_length=8)


class FreeTextAnswerOut(BaseModel):
    answer: str = Field(default="", max_length=6000)
    source_fact_ids: list[str] = []
    confidence: Literal["high", "medium", "low"] = "low"
    missing_information: bool = False
    missing_reason: str = Field(default="", max_length=500)
