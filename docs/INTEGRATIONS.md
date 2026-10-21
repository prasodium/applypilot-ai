# Integrations

Every integration declares what it can really do. Nothing is assumed, and the UI shows these declarations (Settings → Job sources / Sites).

## Job sources (`app/jobsources/`)
| Source | Search | Fetch by URL | Application URL | Automated apply | Notes |
|---|---|---|---|---|---|
| `manual` | no | **yes** (robots.txt respected, private networks and login pages refused) or pasted text/HTML | from JSON-LD or the page URL | no | Always enabled. Parses schema.org `JobPosting` first, then headings and text. |
| `mock` | yes | no | local mock employer URLs | **yes (mock only)** | Synthetic, flagged DEMO. Eight listings covering each scenario (including a prompt-injection description and a closed job). Never a real integration. |
| `arbeitnow` | yes | no | listing page on arbeitnow.com | **no** | Public API `https://www.arbeitnow.com/api/job-board-api`, no key. **Off by default.** Verified live once on 2026-10-21 (field mapping); otherwise tested with a mocked transport. |

### Arbeitnow policy considerations
The API page (https://www.arbeitnow.com/blog/job-board-api) says the API is free and needs no key. It states **no rate limit, attribution or redistribution terms**, so the adapter is conservative: one request per search, results cached for one hour, attribution shown in the UI, read-only, and applying is a manual handoff to the listing page. Review their terms yourself before heavy use.

### Adding a source
Implement `JobSourceAdapter` (declare `SourceCapabilities` truthfully), register it in `jobsources/registry.py`, add it to the `Literal` in `schemas.JobSearchIn`, write tests with a mocked transport, and document its access method and limits here. Do not scrape login-protected pages and do not set `automated_apply=True` unless form filling for that source's application path is implemented, permitted and tested.

## Application sites (`app/browser/capabilities.py`)
| Site | Fill forms | Submit | Account creation | Notes |
|---|---|---|---|---|
| Local mock employer (`MOCK_EMPLOYER_BASE_URL`) | yes | yes | n/a | Test fixture only. Variants: basic, validation, multistep, ambiguous, expired-session, human-verification. Tested by the browser suite on every run. |
| anything else | **no** | **no** | never | Manual handoff: ApplyPilot prepares the résumé and cover letter; you apply and record the result ("reported by you"). |

To support a real site you need: an explicit `SiteCapability` entry (with `docs_url`, restrictions and a real `last_tested` date), a review of the site's terms and robots rules, tests against a faithful fixture, and handling for that site's login/verification (which must keep pausing for the human). **No real site has been integrated or tested in this version.**

## AI providers (`app/ai/`)
| Provider | Use | Status |
|---|---|---|
| `mock` | default; deterministic; output labelled DEMO | tested |
| `openai_compatible` | any endpoint implementing `POST {AI_BASE_URL}/chat/completions` with `response_format: json_object` | request shape, validation and error handling tested with a **mocked transport only**; never run against a live service |

Provider output is validated against Pydantic schemas and grounding checks; failures fall back to "needs your input". Set `AI_PROVIDER=openai_compatible`, `AI_MODEL`, `AI_API_KEY`, `AI_BASE_URL` in `backend/.env`.
