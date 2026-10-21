import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { StateBadge, stateLabel } from "../components/StateBadge";
import { Badge, Card, Empty, ErrorBox, Loading, TextInput, fmt, inputCls, useAsync } from "../components/ui";
import { ScoreBadge } from "./Jobs";

const STATES = ["PROFILE_INFORMATION_REQUIRED", "FORM_IN_PROGRESS", "HUMAN_VERIFICATION_REQUIRED", "LOGIN_REQUIRED", "READY_FOR_REVIEW", "SUBMISSION_PENDING_APPROVAL",
  "SUBMITTED", "SUBMISSION_UNCONFIRMED", "APPLICATION_FAILED", "APPLICATION_WITHDRAWN"];

export default function Applications() {
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const load = useCallback(() => api.applications({ state, q }), [state, q]);
  const { data, error, loading } = useAsync(load);
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Application tracker</h1>
      <Card id="tracker">
        <div className="mb-3 grid gap-3 md:grid-cols-3">
          <TextInput id="aq" label="Search company or role" value={q} onChange={setQ} />
          <div><label htmlFor="as" className="block text-sm font-medium">State</label>
            <select id="as" className={inputCls} value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">All</option>{STATES.map((s) => <option key={s} value={s}>{stateLabel(s)}</option>)}
            </select></div>
        </div>
        {loading && !data && <Loading />}
        <ErrorBox error={error} />
        {data && data.length === 0 && <Empty title="No applications yet">Open a job and press “Prepare application”.</Empty>}
        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Applications</caption>
              <thead><tr className="border-b"><th className="py-2 pr-3">Role</th><th className="pr-3">Match</th><th className="pr-3">State</th><th className="pr-3">Next action</th><th>Updated</th></tr></thead>
              <tbody>
                {data.map((a) => (
                  <tr key={a.id} className="border-b border-slate-100 align-top">
                    <td className="py-2 pr-3"><Link className="font-medium text-indigo-800 underline" to={`/applications/${a.id}`}>{a.title}</Link><div>{a.company}{a.location && <span className="text-slate-600"> · {a.location}</span>}</div>
                      {a.is_demo && <Badge tone="amber">DEMO</Badge>} {a.target_kind === "manual" && <Badge>Manual handoff</Badge>}</td>
                    <td className="pr-3"><ScoreBadge score={a.match_score} /></td>
                    <td className="pr-3"><StateBadge state={a.state} />{a.confirmation_reference && <div className="mt-1 text-xs">Ref {a.confirmation_reference}</div>}{a.outcome === "user_attested" && <div className="mt-1 text-xs">Reported by you</div>}</td>
                    <td className="pr-3 max-w-xs">{a.next_action}</td>
                    <td><time dateTime={a.updated_at}>{fmt(a.updated_at)}</time></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
