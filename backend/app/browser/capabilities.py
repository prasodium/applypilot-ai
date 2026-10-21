"""Per-site integration capability declarations (master prompt section 10). Default for any unknown site: NOT automatable.

Only the local mock employer has form filling and submission enabled. Adding a real site requires an entry here backed by a
permitted, tested integration path; until then the app offers a manual handoff.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from app.config import Settings


@dataclass(frozen=True)
class SiteCapability:
    name: str
    origin: str  # scheme://host[:port]
    path_prefix: str = "/"
    form_filling: bool = False
    submission: bool = False
    auth_required: bool = False
    account_creation: bool = False  # never automated
    restrictions: str = ""
    docs_url: str = ""
    last_tested: str = ""
    is_mock: bool = False

    def as_dict(self) -> dict:
        return asdict(self)

    def matches(self, url: str) -> bool:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}" == self.origin and p.path.startswith(self.path_prefix)


UNSUPPORTED = SiteCapability(
    name="unsupported site", origin="*", form_filling=False, submission=False,
    restrictions="No authorized automation path is implemented for this site. Prepare documents here and apply manually (manual handoff).",
)


def mock_capability(settings: Settings) -> SiteCapability:
    p = urlparse(settings.mock_employer_base_url)
    return SiteCapability(
        name="Local mock employer", origin=f"{p.scheme}://{p.netloc}", path_prefix=p.path or "/", form_filling=True, submission=True,
        restrictions="Local test fixture only. Never a real employer; a 'submission' here is not a real application.",
        docs_url="docs/INTEGRATIONS.md", last_tested="verified by the automated browser tests", is_mock=True,
    )


def registry(settings: Settings) -> list[SiteCapability]:
    return [mock_capability(settings)]


def capability_for(url: str, settings: Settings) -> SiteCapability:
    for cap in registry(settings):
        if cap.matches(url):
            return cap
    return UNSUPPORTED
