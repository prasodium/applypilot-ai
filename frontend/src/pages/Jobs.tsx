import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { type S, api } from "../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, TextInput, fmt, inputCls, useAsync } from "../components/ui";

export function ScoreBadge({ score }: { score?: number | null }) {
  if (score === null || score === undefined) return <Badge title="Not matched yet">No score</Badge>;
  const tone = score >= 70 ? "green" : score >= 45 ? "amber" : "slate";
  return <Badge tone={tone} title="Overlap between your confirmed profile and the posting. Not a hiring prediction.">Match {score.toFixed(0)}/100</Badge>;
}

function SearchForm({ onDone }: { onDone: (msg: string) => void }) {
  const [source, setSource] = useState<"mock" | "arbeitnow">("mock");
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [remote, setRemote] = useState(false);
  const [err, setErr] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.searchJobs({ source, query, location, remote_only: remote, limit: 30 });
      setErr(undefined);
      onDone(`${r.created} new, ${r.duplicates} already known. ${r.attribution}`);
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Find jobs" id="search">
      <form onSubmit={go} className="grid gap-3 md:grid-cols-4">
        <div>
          <label htmlFor="src" className="block text-sm font-medium">Source</label>
          <select id="src" className={inputCls} value={source} onChange={(e) => setSource(e.target.value as "mock" | "arbeitnow")}>
            <option value="mock">Mock jobs (synthetic demo data)</option>
            <option value="arbeitnow">Arbeitnow (real public listings, read-only)</option>
          </select>
        </div>
        <TextInput id="q" label="Keywords" value={query} onChange={setQuery} />
        <TextInput id="loc" label="Location" value={location} onChange={setLocation} />
        <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={remote} onChange={(e) => setRemote(e.target.checked)} /> Remote only</label>
        <div className="md:col-span-4 flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={busy}>{busy ? "Searching…" : "Search"}</Button>
          {source === "arbeitnow" && <span className="text-xs text-slate-600">Disabled by default: enable it in Settings first. Applying happens on the listing page (manual handoff).</span>}
        </div>
      </form>
      {err !== undefined && <div className="mt-2"><ErrorBox error={err} />{(err as { code?: string }).code === "source_not_allowed" && <Link className="text-sm text-indigo-700 underline" to="/settings">Open Settings</Link>}</div>}
    </Card>
  );
}

function ImportForm({ onDone }: { onDone: (msg: string) => void }) {
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [err, setErr] = useState<unknown>();
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const fields: Record<string, string> = {};
      if (company) fields.company = company;
      if (title) fields.title = title;
      const r = await api.importJob({ url, html: "", text, source: "manual", fields });
      setErr(undefined);
      setUrl(""); setText(""); setCompany(""); setTitle("");
      onDone(r.created ? `Imported “${r.job.title}” at ${r.job.company}.` : r.notes.join(" "));
    } catch (x) {
      setErr(x);
    }
  };
  return (
    <Card title="Import one job" id="import">
      <form onSubmit={go} className="grid gap-3 md:grid-cols-2">
        <TextInput id="iu" label="Job page URL" type="url" value={url} onChange={setUrl} hint="robots.txt is respected; login-protected pages are refused." />
        <div className="grid grid-cols-2 gap-3">
          <TextInput id="ic" label="Company (optional)" value={company} onChange={setCompany} />
          <TextInput id="it" label="Title (optional)" value={title} onChange={setTitle} />
        </div>
        <div className="md:col-span-2">
          <label htmlFor="itx" className="block text-sm font-medium">…or paste the job description</label>
          <textarea id="itx" rows={4} className={inputCls} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <div className="md:col-span-2"><Button type="submit" variant="primary" disabled={!url && !text}>Import</Button></div>
      </form>
      {err !== undefined && <div className="mt-2"><ErrorBox error={err} /></div>}
    </Card>
  );
}

export default function Jobs() {
  const [q, setQ] = useState("");
  const [arr, setArr] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("score");
  const [min, setMin] = useState("");
  const [msg, setMsg] = useState<string>();
  const load = useCallback(() => api.jobs({ q, arrangement: arr, user_status: status, sort, min_score: min || undefined, page_size: 50 }), [q, arr, status, sort, min]);
  const { data, error, loading, reload } = useAsync(load);
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Job explorer</h1>
      {msg && <Notice tone="ok">{msg}</Notice>}
      <div className="grid gap-4 lg:grid-cols-2">
        <SearchForm onDone={(m) => { setMsg(m); void reload(); }} />
        <ImportForm onDone={(m) => { setMsg(m); void reload(); }} />
      </div>
      <Card title="Saved jobs" id="list">
        <div className="mb-3 grid gap-3 md:grid-cols-5">
          <TextInput id="fq" label="Filter text" value={q} onChange={setQ} />
          <div><label htmlFor="fa" className="block text-sm font-medium">Work arrangement</label>
            <select id="fa" className={inputCls} value={arr} onChange={(e) => setArr(e.target.value)}><option value="">Any</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></select></div>
          <div><label htmlFor="fs" className="block text-sm font-medium">Status</label>
            <select id="fs" className={inputCls} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option><option value="new">New</option><option value="shortlisted">Shortlisted</option><option value="rejected">Rejected</option></select></div>
          <TextInput id="fm" label="Minimum score" type="number" value={min} onChange={setMin} />
          <div><label htmlFor="fo" className="block text-sm font-medium">Sort</label>
            <select id="fo" className={inputCls} value={sort} onChange={(e) => setSort(e.target.value)}><option value="score">Best match</option><option value="newest">Newest</option></select></div>
        </div>
        {loading && !data && <Loading />}
        <ErrorBox error={error} />
        {data && data.items.length === 0 && <Empty title="No jobs yet">Search the mock source to see the full flow with demo data, or import a job.</Empty>}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Saved jobs</caption>
              <thead><tr className="border-b text-slate-700"><th className="py-2 pr-3">Role</th><th className="pr-3">Location</th><th className="pr-3">Match</th><th className="pr-3">Source</th><th>Status</th></tr></thead>
              <tbody>
                {data.items.map((j: S["JobOut"]) => (
                  <tr key={j.id} className="border-b border-slate-100 align-top">
                    <td className="py-2 pr-3"><Link className="font-medium text-indigo-800 underline" to={`/jobs/${j.id}`}>{j.title}</Link><div className="text-slate-700">{j.company}</div></td>
                    <td className="pr-3">{j.location || "—"}<div className="text-xs text-slate-600">{j.work_arrangement}</div></td>
                    <td className="pr-3"><ScoreBadge score={j.match_score} /></td>
                    <td className="pr-3">{j.source_name}{j.is_demo && <> <Badge tone="amber">DEMO</Badge></>}<div className="text-xs text-slate-600">{fmt(j.retrieved_at)}</div></td>
                    <td>{j.user_status}{j.status === "closed" && <> <Badge tone="red">Closed</Badge></>}{j.flags.length > 0 && <> <Badge tone="red" title={j.flags.join("; ")}>Suspicious text</Badge></>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-slate-600">{data.total} job(s).</p>
          </div>
        )}
      </Card>
    </div>
  );
}

