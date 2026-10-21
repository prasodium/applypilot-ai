# Security and privacy

## Model
ApplyPilot is a **single-user, local** application. It binds to `127.0.0.1`, has no login, and stores everything on your computer. Anyone who can
already run code as you or reach port 8000 on your machine can use it; protect the machine (FileVault, screen lock). Do not expose the port to a network.
Multi-user isolation is therefore **not applicable** (there is no `users` table); this is a deliberate scope decision, not an omission.

What it defends against: hostile **content** (job pages, résumé files, form pages, model output) trying to make the app lie, leak or act beyond the user's authority;
accidental or ambiguous submissions; and sloppy data handling.

## Controls and where they are tested

| Control | Implementation | Tests |
|---|---|---|
| Review-before-submit is the default; auto-submit needs every condition | `core/policy.py`, `UserPreferences.submission_mode` default | `test_browser_flow.py` (default mode, restrictive modes, auto-submit conditions), `test_core_safety.py` (policy table) |
| Authorization enforced in the **backend**, and again right before the click | `services/applications.begin_submit`, `workflow.run_submit` | `test_editing_after_approval_invalidates_it`, `test_policy_denies_each_unsafe_condition` |
| Approval bound to the exact version | `Application.version/approved_version`, `bump_version` | `test_editing_after_approval_invalidates_it` |
| Idempotent submission, no double submit | compare-and-set + stored run, `idempotency_key` | `test_repeated_submit_requests_never_double_submit` |
| Ambiguous outcome is `SUBMISSION_UNCONFIRMED`, never retried | `workflow.run_submit`, `states.py` (no way back to `SUBMISSION_IN_PROGRESS`) | `test_ambiguous_result_is_unconfirmed_and_never_retried`, state tests |
| Crash after the click cannot cause a retry | `clicked` persisted before the click; `recover_interrupted` | `test_recovery_*` |
| Never infer sensitive answers; legal declarations never pre-filled | `core/classify.py`, `services/answers.py` | `test_answers.py` (sensitive/legal parametrized) |
| Only confirmed facts are used | `profile.confirmed_facts` | `test_unconfirmed_facts_are_never_used`, generation and match tests |
| Model output is untrusted: grounding, ids, invented numbers rejected | `core/grounding.py`, `services/answers.py`, `documents.generate_cover_letter` | `test_ungrounded_or_failed_model_output_is_discarded`, `test_ungrounded_ai_output_is_rejected` |
| Prompt injection cannot change settings/state | `core/untrusted.py`; no code path from content to settings; delimiters for real providers | `test_instruction_text_on_pages_and_in_jobs_cannot_change_anything`, resume/answer/provider tests |
| CAPTCHA / login / MFA are **never bypassed** | `browser/pages.detect_challenge`, filler returns `challenge` | `test_human_verification_pauses_for_the_user_and_is_never_bypassed`, expired-session test |
| Browser can only reach the allowed origin | `browser/session.py` route guard | `test_browser_cannot_reach_origins_outside_the_allowed_site` |
| Only the mock site is automatable | `browser/capabilities.py` | `test_unsupported_site_gets_a_manual_handoff_not_automation` |
| Daily limit and duplicate-application checks | policy + `prepare` | `test_daily_limit_is_enforced`, `test_duplicate_application_for_the_same_job_is_refused` |
| Upload validation: extension, MIME, magic bytes, size, encrypted/corrupt/zip-bomb, path traversal | `services/documents.upload_resume` | `test_documents.py` (hostile uploads) |
| Private files: server-chosen names, dir 0700, files 0600, outside static dirs | `upload_resume`, `_mktemp` | `test_path_traversal_filename_is_neutralised_and_file_is_private` |
| SSRF and robots.txt for URL import | `services/urlfetch.py` | `test_unsafe_urls_are_refused`, `test_fetch_*` |
| Secrets/PII not in logs, audit, evidence, API | `core/redact.py` (global log record redaction), audit stores no values | `test_no_personal_data_in_logs_events_or_evidence`, `test_global_log_redaction`, `test_api_key_is_never_returned` |
| Safe errors, no stack traces | exception handlers in `main.py` | `test_errors_never_leak_internals` |
| **CSRF**: state-changing requests from a browser must come from this app's own origin (or the configured frontend origin) | `cross_origin_guard` middleware in `main.py` | `test_cross_site_state_changing_requests_are_blocked`, `test_blocked_cross_site_request_has_no_effect` |
| **DNS rebinding**: only `127.0.0.1`/`localhost` Host headers are served | `TrustedHostMiddleware` (`allowed_hosts`) | `test_unknown_host_headers_are_rejected` |
| CORS limited to the frontend origin; security headers; rate limits on sensitive endpoints | `main.py`, `ratelimit.py` | `test_security_headers_and_cors`, `test_sensitive_endpoints_are_rate_limited` |
| Export and deletion of all data | `profile.export_all/delete_all` | `test_export_contains_everything_then_delete_removes_everything` |
| Evidence is minimal; screenshots/HTML are never stored | `workflow._evidence`, `evidence_capture` setting | `test_evidence_capture_can_be_turned_off` |
| SQL injection | SQLAlchemy ORM / bound parameters only | n/a (no string-built SQL) |

## Credentials and accounts
**ApplyPilot stores no passwords, tokens, cookies or session data and automates no login or account creation.** If a site needs you to sign in, the workflow pauses and you do it yourself.
`platform_accounts` holds metadata only and is currently unused. The AI API key is read from the environment, never stored in the database, never returned by the API (only `ai_api_key_set`) and redacted from logs.

## Data handling
* Everything is stored in `backend/data/` (SQLite, uploads). **SQLite is not encrypted at rest**; rely on disk encryption.
* Uploaded résumés are kept only so you can re-parse them; delete them in Résumé studio or via *Delete all my data*.
* Temporary files for browser uploads (rendered PDFs) live in `backend/data/tmp/<random>` and are removed after each run.
* Nothing is sent to any third party unless you configure a real AI provider (your confirmed facts and the question text go to that provider for answers/cover letters) or enable a job source (a read-only request to that source). No telemetry. Candidate data is not used for training by this app.
* Retention is configurable in preferences (`retention_days`); an automatic purge job is **not implemented**; use Settings → Your data.

## Known limitations
* No authentication; local-only by design (see Model). Browser-driven cross-site requests are blocked by the origin guard, but a *non-browser* process on your machine (or anything that can reach the port) is not stopped: keep the port bound to localhost.
* Rate limits and the in-memory run registry are per process.
* The ambiguous-result detection relies on page text; a site that shows a success phrase and a reference without really accepting the form would be treated as confirmed.
* The résumé parser and the job parser are heuristics, so wrong extractions are possible. That is why a human confirmation step exists.
* The mock employer fixture contains hidden "AI agent" instructions on purpose; do not point the app at untrusted sites expecting protection beyond what is listed above.
* Dependencies were not audited for known vulnerabilities (`npm audit`/`pip-audit` were not run).
