# User guide

ApplyPilot helps with the repetitive parts of job applications while keeping **you** in control and **honest**. This version runs in demo mode: it never submits a real application.

## 1. Build a verified profile
**Profile** holds your details. Add education, experience, skills and projects, or upload a résumé in **Résumé studio**.
* After an upload you see a *preview* of what was extracted. Correct it, untick anything wrong, then **Confirm and save**, or **Save as unconfirmed** to review later.
* Only **confirmed** items are used for matching, documents and answers. Unconfirmed items show an amber badge; confirm them one by one or all at once.
* Optional sensitive fields (work authorization, sponsorship) are used only if you fill them in. Otherwise you are always asked.

## 2. Find jobs
**Jobs → Find jobs**: search the *Mock jobs* source (synthetic demo data) or enable *Arbeitnow* in **Settings** for real read-only listings. **Import one job** takes a URL (pages that need a login or forbid robots are refused) or pasted text.
Open a job to see **where its match score comes from**: each component, what matched, the gaps, and what was *unknown* (excluded, not counted against you). The score compares your profile with the posting; it does not predict hiring.
Postings containing instruction-like text aimed at AI tools are flagged; ApplyPilot treats them as plain text.

## 3. Prepare an application
Press **Prepare application**. ApplyPilot drafts a tailored résumé and cover letter from your confirmed facts and, for the mock site, opens the form in a browser and reads it.
* **Manual handoff** (any other site): you get the documents and a link; apply yourself and record the result.
* The browser stops when it needs an answer it may not supply. Those questions are highlighted: *Needs your input*.

## 4. Review and answer
On the application page:
* **Checklist** lists everything still missing. **Questions and answers** shows each answer with its confidence, source facts and warnings.
* **Sensitive** questions (work authorization, sponsorship, demographics, health, criminal history) are never guessed. If an answer came from your profile or saved answers you must still press *I have reviewed this: approve answer*.
* **Legal declarations** (certify/agree) are never pre-filled: choose the answer yourself.
* Free-text answers are drafted only from your confirmed projects and experience. *Why do you want to work here?* is never written for you.
* Edit anything. Each edit makes a new version and **cancels any approval**.

## 5. Verify, approve, submit
1. **Check form in browser** fills the form and verifies every value by reading it back. It never submits. Pause, resume or cancel at any time under *Browser*.
2. **Approve this version** (available when the checklist is complete and the form was verified for this version).
3. **Submit** (enabled only when the policy allows). If the page shows an explicit confirmation reference, the application becomes *Submitted* with that reference. If it is unclear it becomes **Result unconfirmed** and is **never retried automatically**; check the employer's site or your email and record what you found (stored as *reported by you*).
If a site shows a human-verification challenge, asks you to sign in, or needs email verification, the workflow pauses and tells you what to do. ApplyPilot never solves or bypasses these.

## 6. Let the bot do the routine work (optional)
Open **Bot**, tick *Run the bot automatically*, and pick how often it runs. Each run:
1. searches your enabled sources using your target roles (or the search terms you set),
2. scores new jobs and keeps those at or above your match threshold, skipping closed, rejected, duplicate and suspicious listings,
3. prepares applications and fills the form, up to *Max new applications per run* and your daily limit,
4. **stops for you**: open *Applications* to review, approve and submit. A notification summarises each run.

The bot is **off by default**, runs only while ApplyPilot is open, and **never submits** unless *Authorized auto-submit* is on in Settings and every safety check passes (approved documents, reviewed answers, verified form, limits). It never answers sensitive or legal questions and never gets past CAPTCHA, login or verification. *Run now* triggers one run on demand.

## 7. Settings
* **Submission mode**: *Review before submission* (default), *Prepare only*, *Research only*, or *Authorized auto-submit* (off by default; requires every safety condition).
* Match threshold, daily limit, target roles and locations, salary/relocation/start-date preferences (used only if filled), evidence capture, job sources, saved answers.
* **Your data**: export everything as JSON, or delete everything.

## What demo mode means
The AI is a deterministic mock and its text is labelled DEMO. Job listings from the mock source are synthetic. The only site that is filled and submitted is a local test site, so a "submission" never reaches a real employer.
