import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, fmt, inputCls, useAsync } from "../components/ui";

export default function Activity() {
  const [type, setType] = useState("");
  const load = useCallback(async () => ({ audit: await api.audit(type || undefined), notes: await api.notifications() }), [type]);
  const { data, error, loading, reload } = useAsync(load);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Activity</h1>
      <Card title="Notifications" id="notes">
        {data.notes.length === 0 && <Empty title="No notifications" />}
        <ul className="divide-y divide-slate-100 text-sm">
          {data.notes.map((n) => (
            <li key={n.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span className={n.read ? "text-slate-600" : "font-medium"}>{n.title}{n.body && <span className="block font-normal text-slate-700">{n.body}</span>}</span>
              <span className="flex items-center gap-2"><time className="text-slate-600" dateTime={n.ts}>{fmt(n.ts)}</time>
                <Button variant="ghost" onClick={async () => { await api.markNotification(n.id, !n.read); await reload(); }}>{n.read ? "Mark unread" : "Mark read"}</Button></span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Audit log" id="audit" actions={<><label htmlFor="at" className="sr-only">Filter by event type</label>
        <select id="at" className={inputCls + " !mt-0 !w-auto"} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All events</option>
          {["application_prepared", "answer_drafted", "answer_edited", "approval_granted", "approval_revoked", "submission_attempted", "submission_confirmed", "submission_unconfirmed", "submission_denied", "state_changed", "job_imported", "data_exported"].map((t) => <option key={t} value={t}>{t.replaceAll("_", " ")}</option>)}
        </select></>}>
        <p className="mb-2 text-xs text-slate-600">Events never contain passwords, tokens or your answers.</p>
        {data.audit.length === 0 ? <Empty title="No events" /> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {data.audit.map((a) => (
              <li key={a.id} className="flex flex-wrap justify-between gap-2 py-1.5"><span><Badge>{a.event_type.replaceAll("_", " ")}</Badge> {a.summary}</span><time className="text-slate-600" dateTime={a.ts}>{fmt(a.ts)}</time></li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
