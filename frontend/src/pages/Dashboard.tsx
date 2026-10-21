import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, Empty, ErrorBox, Loading, fmt, useAsync } from "../components/ui";

export default function Dashboard() {
  const { data, error, loading } = useAsync(api.dashboard);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const tiles: [string, number, string][] = [
    ["Jobs discovered", data.jobs_discovered, "/jobs"], ["Shortlisted", data.shortlisted, "/jobs"], ["Drafts in progress", data.draft_applications, "/applications"],
    ["Awaiting your review", data.awaiting_review, "/applications"], ["Needs your action", data.needs_user_action, "/applications"],
    ["Submitted", data.submitted, "/applications"], ["Result unconfirmed", data.unconfirmed, "/applications"],
  ];
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Summary">
        {tiles.map(([label, n, to]) => (
          <li key={label}>
            <Link to={to} className="block rounded-lg border border-slate-200 bg-white p-4 shadow-sm hover:border-indigo-400">
              <span className="block text-3xl font-bold">{n}</span>
              <span className="text-sm text-slate-700">{label}</span>
            </Link>
          </li>
        ))}
      </ul>
      <Card title="Next actions">
        {data.next_actions.length === 0 ? (
          <Empty title="Nothing needs your attention">Search for jobs or import one by URL to get started.</Empty>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm">{data.next_actions.map((a) => <li key={a}>{a}</li>)}</ul>
        )}
      </Card>
      <Card title="Recent activity" actions={<Link className="text-sm text-indigo-700 underline" to="/activity">All activity</Link>}>
        {data.recent_activity.length === 0 ? (
          <Empty title="No activity yet" />
        ) : (
          <ul className="divide-y divide-slate-100 text-sm">
            {data.recent_activity.map((a) => (
              <li key={a.id} className="flex justify-between gap-4 py-1.5">
                <span>{a.summary || a.event_type}</span>
                <time className="shrink-0 text-slate-600" dateTime={a.ts}>{fmt(a.ts)}</time>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
