import type { components } from "./schema";

export type S = components["schemas"];

/** Error returned by the backend ({"error": {code, message, details}}). `message` is safe to show to the user. */
export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the ApplyPilot backend. Is it running on port 8000?");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = undefined;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const e = (data as { error?: { code?: string; message?: string; details?: Record<string, unknown> } } | undefined)?.error;
    throw new ApiError(res.status, e?.code ?? "error", e?.message ?? `Request failed (${res.status})`, e?.details ?? {});
  }
  return data as T;
}

const q = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => request<{ status: string }>("GET", "/health"),
  dashboard: () => request<S["DashboardOut"]>("GET", "/dashboard"),
  settings: () => request<S["SettingsOut"]>("GET", "/settings"),
  patchSettings: (b: S["SettingsPatch"]) => request<S["SettingsOut"]>("PATCH", "/settings", b),
  // profile
  profile: () => request<S["ProfileOut"]>("GET", "/profile"),
  patchProfile: (b: S["ProfilePatch"]) => request<S["ProfileOut"]>("PATCH", "/profile", b),
  facts: () => request<S["Fact"][]>("GET", "/profile/facts"),
  confirmFact: (id: string) => request<S["Fact"]>("POST", `/profile/facts/${encodeURIComponent(id)}/confirm`),
  addRecord: <T>(kind: RecordKind, b: unknown) => request<T>("POST", `/profile/${kind}`, b),
  updateRecord: <T>(kind: RecordKind, id: number, b: unknown) => request<T>("PUT", `/profile/${kind}/${id}`, b),
  deleteRecord: (kind: RecordKind, id: number) => request<void>("DELETE", `/profile/${kind}/${id}`),
  answerLibrary: () => request<S["ApprovedAnswerOut"][]>("GET", "/answer-library"),
  addLibraryAnswer: (b: S["ApprovedAnswerIn"]) => request<S["ApprovedAnswerOut"]>("POST", "/answer-library", b),
  deleteLibraryAnswer: (id: number) => request<void>("DELETE", `/answer-library/${id}`),
  deleteAllData: () => request<{ deleted: Record<string, number> }>("DELETE", "/data?confirm=DELETE"),
  // documents
  documents: (kind?: string) => request<S["DocumentOut"][]>("GET", `/documents${q({ kind })}`),
  document: (id: number) => request<S["DocumentDetail"]>("GET", `/documents/${id}`),
  upload: (file: File) => {
    const f = new FormData();
    f.append("file", file);
    return request<S["DocumentDetail"]>("POST", "/documents", undefined, f);
  },
  applyParse: (id: number, b: S["ApplyParseIn"]) => request<S["ProfileOut"]>("POST", `/documents/${id}/apply-parse`, b),
  generateResume: (job_id?: number) => request<S["DocumentDetail"]>("POST", "/documents/generate-resume", { job_id }),
  generateCoverLetter: (job_id: number) => request<S["DocumentDetail"]>("POST", "/documents/generate-cover-letter", { job_id }),
  approveDocument: (id: number) => request<S["DocumentDetail"]>("POST", `/documents/${id}/approve`),
  diff: (id: number, against: number) => request<{ lines: string[] }>("GET", `/documents/${id}/diff?against=${against}`),
  deleteDocument: (id: number) => request<void>("DELETE", `/documents/${id}`),
  downloadUrl: (id: number, format: "txt" | "docx" | "pdf") => `/api/documents/${id}/download?format=${format}`,
  // jobs
  jobs: (p: Record<string, string | number | undefined>) => request<S["JobsPage"]>("GET", `/jobs${q(p)}`),
  job: (id: number) => request<S["JobOut"]>("GET", `/jobs/${id}`),
  importJob: (b: S["JobImportIn"]) => request<S["JobImportResult"]>("POST", "/jobs/import", b),
  searchJobs: (b: S["JobSearchIn"]) => request<S["JobSearchResult"]>("POST", "/jobs/search", b),
  match: (id: number) => request<S["MatchOut"]>("POST", `/jobs/${id}/match`),
  shortlist: (id: number, status: "shortlisted" | "rejected" | "new") => request<S["JobOut"]>("POST", `/jobs/${id}/shortlist`, { status }),
  // applications
  applications: (p: Record<string, string | number | undefined> = {}) => request<S["ApplicationOut"][]>("GET", `/applications${q(p)}`),
  application: (id: number) => request<S["ApplicationDetail"]>("GET", `/applications/${id}`),
  prepare: (job_id: number) => request<S["ApplicationDetail"]>("POST", "/applications/prepare", { job_id }),
  patchApplication: (id: number, b: S["ApplicationPatch"]) => request<S["ApplicationDetail"]>("PATCH", `/applications/${id}`, b),
  fill: (id: number) => request<S["WorkflowOut"]>("POST", `/applications/${id}/fill`),
  approve: (id: number, version: number) => request<S["ApplicationDetail"]>("POST", `/applications/${id}/approve`, { version }),
  submit: (id: number) => request<{ workflow_id: number; duplicate_request: boolean; state: string }>("POST", `/applications/${id}/submit`),
  attest: (id: number, b: S["AttestIn"]) => request<S["ApplicationDetail"]>("POST", `/applications/${id}/attest`, b),
  cancelApplication: (id: number) => request<S["ApplicationDetail"]>("POST", `/applications/${id}/cancel`),
  // workflows
  workflows: (application_id: number) => request<S["WorkflowOut"][]>("GET", `/workflows${q({ application_id })}`),
  workflow: (id: number) => request<S["WorkflowDetail"]>("GET", `/workflows/${id}`),
  pause: (id: number) => request<S["WorkflowOut"]>("POST", `/workflows/${id}/pause`),
  resume: (id: number) => request<S["WorkflowOut"]>("POST", `/workflows/${id}/resume`),
  cancelWorkflow: (id: number) => request<S["WorkflowOut"]>("POST", `/workflows/${id}/cancel`),
  // activity
  audit: (event_type?: string) => request<S["AuditOut"][]>("GET", `/audit${q({ event_type, limit: 100 })}`),
  bot: () => request<S["BotStatusOut"]>("GET", "/bot"),
  patchBot: (body: S["BotConfigPatch"]) => request<S["BotStatusOut"]>("PATCH", "/bot", body),
  runBot: () => request<S["BotStatusOut"]>("POST", "/bot/run"),
  notifications: () => request<S["NotificationOut"][]>("GET", "/notifications"),
  markNotification: (id: number, read: boolean) => request<S["NotificationOut"]>("PATCH", `/notifications/${id}`, { read }),
};

export type RecordKind = "education" | "experience" | "skills" | "projects";

/** Fields the backend rejected, keyed by field name, for inline form errors. */
export function fieldErrors(e: unknown): Record<string, string> {
  if (e instanceof ApiError && e.code === "validation_error") {
    const errs = (e.details.errors as { field: string; message: string }[] | undefined) ?? [];
    return Object.fromEntries(errs.map((x) => [x.field, x.message]));
  }
  return {};
}

export function errorMessage(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Something went wrong.";
}
