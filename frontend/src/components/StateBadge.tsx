import { Badge } from "./ui";

type Tone = "slate" | "green" | "amber" | "red" | "blue" | "violet";
const MAP: Record<string, { label: string; tone: Tone; mark: string }> = {
  APPLICATION_PREPARING: { label: "Preparing", tone: "blue", mark: "…" },
  FORM_IN_PROGRESS: { label: "Browser filling form", tone: "blue", mark: "…" },
  PROFILE_INFORMATION_REQUIRED: { label: "Your input needed", tone: "amber", mark: "!" },
  FORM_VALIDATION_FAILED: { label: "Form rejected a value", tone: "amber", mark: "!" },
  LOGIN_REQUIRED: { label: "Sign-in needed", tone: "amber", mark: "!" },
  ACCOUNT_CREATION_REQUIRED: { label: "Account needed", tone: "amber", mark: "!" },
  EMAIL_VERIFICATION_REQUIRED: { label: "Email verification needed", tone: "amber", mark: "!" },
  HUMAN_VERIFICATION_REQUIRED: { label: "Human verification needed", tone: "amber", mark: "!" },
  READY_FOR_REVIEW: { label: "Ready for review", tone: "violet", mark: "?" },
  SUBMISSION_PENDING_APPROVAL: { label: "Approved, not submitted", tone: "violet", mark: "✓" },
  SUBMISSION_IN_PROGRESS: { label: "Submitting", tone: "blue", mark: "…" },
  SUBMITTED: { label: "Submitted", tone: "green", mark: "✓" },
  SUBMISSION_UNCONFIRMED: { label: "Result unconfirmed", tone: "red", mark: "?" },
  APPLICATION_FAILED: { label: "Failed", tone: "red", mark: "✕" },
  APPLICATION_WITHDRAWN: { label: "Withdrawn", tone: "slate", mark: "–" },
  JOB_CLOSED: { label: "Job closed", tone: "slate", mark: "–" },
};

/** State is always shown as TEXT plus a symbol, never by colour alone. */
export function StateBadge({ state }: { state: string }) {
  const s = MAP[state] ?? { label: state, tone: "slate" as Tone, mark: "" };
  return (
    <Badge tone={s.tone} title={state}>
      <span aria-hidden="true" className="mr-1">{s.mark}</span>
      {s.label}
    </Badge>
  );
}

export const stateLabel = (state: string) => MAP[state]?.label ?? state;
