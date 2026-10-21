"""Job source adapters. Each adapter DECLARES what it can really do; nothing is assumed or faked."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceCapabilities:
    search: bool = False
    fetch_by_url: bool = False
    provides_application_url: bool = False
    automated_apply: bool = False  # True ONLY if form filling/submission has been implemented AND tested for this source
    requires_auth: bool = False
    is_demo: bool = False  # synthetic data; never presented as a real integration
    docs_url: str = ""
    notes: str = ""
    last_tested: str = ""  # ISO date of the last verified run against the real service ("" = never)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchQuery:
    query: str = ""
    location: str = ""
    remote_only: bool = False
    limit: int = 20


@dataclass
class RawJob:
    fields: dict[str, Any] = field(default_factory=dict)  # JobListing columns (+ optional _skills_* hints)


class SourceError(Exception):
    """Raised for adapter failures; the message is safe to show to the user."""


class JobSourceAdapter(ABC):
    name: str
    display_name: str
    capabilities: SourceCapabilities

    @abstractmethod
    def search(self, q: SearchQuery) -> list[RawJob]:
        """Return listings. Adapters that cannot search must raise SourceError and declare search=False."""
