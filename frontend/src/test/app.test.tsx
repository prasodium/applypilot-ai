import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api, fieldErrors } from "../api/client";
import { StateBadge } from "../components/StateBadge";
import ApplicationReview from "../pages/ApplicationReview";
import Settings from "../pages/Settings";
import { errorResponse, mockApi, renderAt } from "./render";

const prefs = {
  id: 1, target_roles: [], locations: [], remote_preference: "any", employment_types: [], salary_min: null, salary_max: null, salary_currency: "",
  sponsorship_preference: "", relocation_preference: "", start_date: "", match_threshold: 60, max_applications_per_day: 5,
  allowed_sources: ["manual", "mock"], submission_mode: "review_before_submission", match_weights: {}, retention_days: 365, evidence_capture: "minimal",
};
const settings = (mode = "review_before_submission") => ({
  app_env: "development", ai_provider: "mock", ai_model: "", ai_api_key_set: false, ai_demo_mode: true, browser_headless: true,
  mock_employer_base_url: "http://127.0.0.1:8000/mock-employer", max_upload_mb: 10, preferences: { ...prefs, submission_mode: mode },
  job_sources: [{ name: "mock", display_name: "Mock jobs", enabled: true, is_demo: true, automated_apply: true, notes: "Synthetic", docs_url: "" },
    { name: "arbeitnow", display_name: "Arbeitnow", enabled: false, is_demo: false, automated_apply: false, notes: "Read-only", docs_url: "https://x.example" }],
  site_capabilities: [{ name: "Local mock employer", origin: "http://127.0.0.1:8000", form_filling: true, submission: true, restrictions: "Local test fixture only." }],
});

describe("API client", () => {
  it("turns a backend error into an ApiError with a safe message", async () => {
    mockApi([["GET", "/profile", () => errorResponse(422, "validation_error", "Some fields are invalid.", { errors: [{ field: "email", message: "not a valid email address" }] })]]);
    const e = await api.profile().catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(422);
    expect(fieldErrors(e)).toEqual({ email: "not a valid email address" });
  });

  it("explains a network failure without leaking internals", async () => {
    globalThis.fetch = vi.fn(async () => { throw new TypeError("boom"); }) as typeof fetch;
    const e = await api.dashboard().catch((x) => x);
    expect(e.message).toMatch(/Cannot reach the ApplyPilot backend/);
    expect(e.message).not.toMatch(/boom/);
  });
});

describe("StateBadge", () => {
  it.each([["SUBMITTED", "Submitted"], ["SUBMISSION_UNCONFIRMED", "Result unconfirmed"], ["HUMAN_VERIFICATION_REQUIRED", "Human verification needed"]])(
    "shows %s as text, not only colour", (state, label) => {
      renderAt(<StateBadge state={state} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    });
});

describe("Settings", () => {
  it("defaults to review-before-submission and warns when auto-submit is chosen", async () => {
    const calls = mockApi([["GET", "/settings", () => settings()], ["GET", "/answer-library", () => []], ["PATCH", "/settings", () => settings("authorized_auto_submit")]]);
    renderAt(<Settings />);
    const review = await screen.findByRole("radio", { name: /Review before submission/ });
    expect(review).toBeChecked();
    expect(screen.queryByText(/Auto-submit is on/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Authorized auto-submit/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && JSON.stringify(c.body).includes("authorized_auto_submit"))).toBe(true));
  });

  it("shows capabilities honestly and keeps deletion locked until DELETE is typed", async () => {
    mockApi([["GET", "/settings", () => settings()], ["GET", "/answer-library", () => []]]);
    renderAt(<Settings />);
    expect(await screen.findByText(/Local test fixture only/)).toBeInTheDocument();
    expect(screen.getByText(/never fills or submits the form for you/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete all my data" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Type DELETE/), "DELETE");
    expect(screen.getByRole("button", { name: "Delete all my data" })).toBeEnabled();
  });
});

const question = (over = {}) => ({
  id: 1, position: 0, step_index: 0, field_key: "work_auth", label: "Are you legally authorized to work?", field_type: "select", required: true, options: ["Yes", "No"],
  max_length: null, question_type: "work_authorization", sensitive_or_legal: true, is_legal: false,
  answer: { id: 1, question_id: 1, answer_text: "", source_fact_ids: [], confidence: "low", needs_user_input: true, sensitive_or_legal: true, word_limit: null,
    character_limit: null, review_status: "needs_user_input", origin: "generated", notes: "Sensitive. Nothing is assumed." }, ...over,
});
const detail = (over = {}) => ({
  id: 7, job_id: 3, state: "PROFILE_INFORMATION_REQUIRED", version: 2, approved_version: null, filled_version: null, approved_at: null, target_kind: "mock", application_url: "http://x/y",
  confirmation_reference: "", outcome: "", outcome_evidence: {}, submitted_at: null, notes: "", last_error: "", is_demo: true, resume_document_id: null, cover_letter_document_id: null,
  created_at: "2026-10-21T10:00:00Z", updated_at: "2026-10-21T10:00:00Z", company: "Globex (demo)", title: "Backend Engineer", location: "Springfield", match_score: 62, source_url: "mock://jobs/1",
  next_action: "Answer the highlighted questions.", questions: [question()], issues: [{ code: "answer_missing", message: "Answer needed: Are you legally authorized to work?", question_id: 1 }],
  ready_for_approval: false, submit_decision: { allowed: false, reasons: ["approval_missing_or_stale", "incomplete_answers"], messages: ["You have not approved the current version of this application.", "Some required answers are missing."] }, ...over,
});

describe("Application review", () => {
  const base = (d: object) => mockApi([["GET", "/applications/7", () => d], ["GET", "/profile/facts", () => []], ["GET", "/workflows", () => []]]);

  it("never presents a sensitive unknown as answered, blocks approval and submit, and explains why", async () => {
    base(detail());
    renderAt(<ApplicationReview />, "/applications/7", "/applications/:id");
    expect(await screen.findByRole("heading", { name: "Backend Engineer" })).toBeInTheDocument();
    expect(screen.getByText(/Mock employer: not a real application/)).toBeInTheDocument();
    expect(screen.getByText(/Sensitive: never assumed/)).toBeInTheDocument();
    expect(screen.getAllByText(/Needs your input/).length).toBeGreaterThan(0);
    expect(screen.getByRole("combobox", { name: /legally authorized/ })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Approve this version" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(screen.getByText("Submission is currently blocked because:")).toBeInTheDocument();
    expect(screen.getByText(/Some required answers are missing\./)).toBeInTheDocument();
  });

  it("flags legal declarations as something only the user can answer", async () => {
    base(detail({ questions: [question({ id: 2, field_key: "certify", label: "I certify that the information is true", field_type: "checkbox", question_type: "legal_certification", is_legal: true })] }));
    renderAt(<ApplicationReview />, "/applications/7", "/applications/:id");
    expect(await screen.findByText(/Legal declaration: only you can answer/)).toBeInTheDocument();
  });

  it("saves a user-written answer through the API", async () => {
    const calls = mockApi([["GET", "/applications/7", () => detail()], ["GET", "/profile/facts", () => []], ["GET", "/workflows", () => []], ["PATCH", "/applications/7", () => detail()]]);
    renderAt(<ApplicationReview />, "/applications/7", "/applications/:id");
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: /legally authorized/ }), "Yes");
    await userEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ answers: { "1": { answer_text: "Yes" } } }));
  });

  it("enables approval only when the checklist is complete, and submit only when the policy allows it", async () => {
    base(detail({ state: "READY_FOR_REVIEW", issues: [], ready_for_approval: true, questions: [], submit_decision: { allowed: false, reasons: ["approval_missing_or_stale"], messages: ["You have not approved the current version of this application."] } }));
    renderAt(<ApplicationReview />, "/applications/7", "/applications/:id");
    expect(await screen.findByRole("button", { name: "Approve this version" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("tells the user an unconfirmed result will not be retried and lets them record what they found", async () => {
    base(detail({ state: "SUBMISSION_UNCONFIRMED", issues: [], questions: [], submit_decision: { allowed: false, reasons: ["already_submitted_or_unconfirmed"], messages: ["Already handled."] } }));
    renderAt(<ApplicationReview />, "/applications/7", "/applications/:id");
    const notice = (await screen.findByText(/The result is unclear/)).closest('[role="status"]');
    expect(notice?.textContent).toMatch(/will not retry/);
    const rec = screen.getByRole("group", { name: /Record what happened/ });
    expect(within(rec).getByText(/not machine-verified/)).toBeInTheDocument();
  });

  it("shows a manual handoff, not automation, for sites without an authorized path", async () => {
    base(detail({ target_kind: "manual", state: "READY_FOR_REVIEW", questions: [], issues: [], application_url: "https://careers.example.com/apply/1", is_demo: false }));
    renderAt(<ApplicationReview />, "/applications/7", "/applications/:id");
    expect(await screen.findByText(/no authorized automation for this site/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check form in browser" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the application page" })).toHaveAttribute("rel", "noopener noreferrer");
  });
});
