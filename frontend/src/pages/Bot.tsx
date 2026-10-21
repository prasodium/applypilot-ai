import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, fmt, inputCls, useAsync } from "../components/ui";

const INTERVALS: [number, string][] = [[60, "Every hour"], [360, "Every 6 hours"], [720, "Every 12 hours"], [1440, "Every day"], [10080, "Every week"]];

export default function Bot() {
  const load = useCallback(() => api.bot(), []);
  const { data, error, loading, reload, setData } = useAsync(load);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [queries, setQueries] = useState<string | null>(null);

  // Poll while a run is in progress so the page shows the result without a manual refresh.
  useEffect(() => {
    if (!data?.running) return;
    const t = setInterval(() => void reload(), 1500);
    return () => clearInterval(t);
  }, [data?.running, reload]);

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const { config: c } = data;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setMsg("");
    try {
      await fn();
    } catch (e) {
      setMsg(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  const patch = (body: Parameters<typeof api.patchBot>[0]) => act(async () => setData(await api.patchBot(body)));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Bot</h1>
      {data.will_submit_without_you ? (
        <Notice tone="warn"><strong>Auto-submit is on in Settings.</strong> The bot may submit applications only when every safety check passes. Turn it off in <Link className="underline" to="/settings">Settings</Link> to always review first.</Notice>
      ) : (
        <Notice tone="ok">The bot never submits. It prepares applications and stops for your review.</Notice>
      )}
      {msg && <p role="alert" className="text-sm text-red-800">{msg}</p>}
      <Card title="Schedule" actions={<Badge tone={c.enabled ? "green" : "slate"}>{c.enabled ? "On" : "Off"}</Badge>}>
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="flex items-center gap-2 text-sm font-medium sm:col-span-3">
            <input type="checkbox" checked={c.enabled} disabled={busy} onChange={(e) => void patch({ enabled: e.target.checked })} />
            Run the bot automatically
          </label>
          <div>
            <label htmlFor="bot-interval" className="text-sm font-medium">How often</label>
            <select id="bot-interval" className={inputCls} value={c.interval_minutes} disabled={busy} onChange={(e) => void patch({ interval_minutes: Number(e.target.value) })}>
              {INTERVALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              {!INTERVALS.some(([v]) => v === c.interval_minutes) && <option value={c.interval_minutes}>{c.interval_minutes} minutes</option>}
            </select>
          </div>
          <div>
            <label htmlFor="bot-max" className="text-sm font-medium">Max new applications per run</label>
            <select id="bot-max" className={inputCls} value={c.max_new_per_run} disabled={busy} onChange={(e) => void patch({ max_new_per_run: Number(e.target.value) })}>
              {[1, 3, 5, 10, 20].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="bot-queries" className="text-sm font-medium">Search terms</label>
            <input id="bot-queries" className={inputCls} placeholder="Uses your target roles if empty" value={queries ?? c.queries.join(", ")}
              onChange={(e) => setQueries(e.target.value)}
              onBlur={() => { if (queries !== null) { void patch({ queries: queries.split(",").map((q) => q.trim()).filter(Boolean).slice(0, 5) }); setQueries(null); } }} />
          </div>
        </div>
        <p className="mt-3 text-sm text-slate-700">
          {c.enabled ? `Next run: ${data.next_run_at ? fmt(data.next_run_at) : "soon"}.` : "The bot is off. Nothing runs until you turn it on."}
          {" "}It only runs while ApplyPilot is open. Match threshold, daily limit and allowed sources come from <Link className="underline" to="/settings">Settings</Link>.
        </p>
        <div className="mt-3"><Button variant="primary" disabled={busy || data.running} onClick={() => void act(async () => setData(await api.runBot()))}>{data.running ? "Running…" : "Run now"}</Button></div>
      </Card>
      <Card title="Recent runs" id="runs">
        {data.runs.length === 0 ? <Empty title="No runs yet">Press Run now to try it.</Empty> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {data.runs.map((r) => (
              <li key={r.id} className="py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span><Badge tone={r.status === "completed" ? "green" : r.status === "failed" ? "red" : "blue"}>{r.status}</Badge> {r.summary || "In progress"}</span>
                  <time className="text-slate-600" dateTime={r.started_at}>{fmt(r.started_at)} · {r.trigger}</time>
                </div>
                {r.needs_review > 0 && <p className="mt-1"><Link className="underline" to="/applications">{r.needs_review} application(s) need your review</Link></p>}
                {(r.details.errors as string[] | undefined)?.map((e) => <p key={e} className="mt-1 text-amber-900">{e}</p>)}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
