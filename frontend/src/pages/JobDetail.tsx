import { useCallback, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Button, Card, ErrorBox, Loading, Notice, fmt, useAsync } from "../components/ui";
import { ScoreBadge } from "./Jobs";

export default function JobDetail() {
  const id = Number(useParams().id);
  const nav = useNavigate();
  const load = useCallback(async () => ({ job: await api.job(id), match: await api.match(id) }), [id]);
  const { data, error, loading, reload } = useAsync(load);
  const [err, setErr] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const { job, match } = data;
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); setErr(undefined); await reload(); } catch (e) { setErr(e); } };
  const prepare = async () => {
    setBusy(true);
    try { const a = await api.prepare(id); nav(`/applications/${a.id}`); } catch (e) { setErr(e); setBusy(false); }
  };
  return (
    <div className="space-y-6">
      <p><Link className="text-sm text-indigo-700 underline" to="/jobs">← All jobs</Link></p>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{job.title}</h1>
          <p className="text-slate-700">{job.company} · {job.location || "Location not stated"} · {job.work_arrangement}</p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <ScoreBadge score={match.score} />
            {job.is_demo && <Badge tone="amber">DEMO data</Badge>}
            {job.status === "closed" && <Badge tone="red">Closed</Badge>}
            <Badge>{job.user_status}</Badge>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => act(() => api.shortlist(id, job.user_status === "shortlisted" ? "new" : "shortlisted"))}>{job.user_status === "shortlisted" ? "Remove from shortlist" : "Shortlist"}</Button>
          <Button onClick={() => act(() => api.shortlist(id, "rejected"))}>Reject</Button>
          <Button variant="primary" disabled={busy || job.status === "closed"} onClick={prepare}>{busy ? "Preparing…" : "Prepare application"}</Button>
        </div>
      </div>
      <ErrorBox error={err} />
      {job.flags.length > 0 && <Notice tone="warn"><strong>Suspicious text in this posting.</strong> It contains instruction-like content aimed at AI tools ({job.flags.join("; ")}). ApplyPilot treats it as plain data and ignores it.</Notice>}
      <Card title="Source" id="src">
        <dl className="grid gap-1 text-sm md:grid-cols-2">
          <div><dt className="inline font-medium">Source: </dt><dd className="inline">{job.source_name}</dd></div>
          <div><dt className="inline font-medium">Retrieved: </dt><dd className="inline">{fmt(job.retrieved_at)}</dd></div>
          <div className="md:col-span-2"><dt className="inline font-medium">URL: </dt><dd className="inline break-all">{job.source_url.startsWith("http") ? <a className="text-indigo-700 underline" href={job.source_url} target="_blank" rel="noopener noreferrer">{job.source_url}</a> : job.source_url}</dd></div>
          <div><dt className="inline font-medium">Salary: </dt><dd className="inline">{job.salary_min ? `${job.salary_min}–${job.salary_max} ${job.salary_currency}` : "not stated"}</dd></div>
          <div><dt className="inline font-medium">Posted: </dt><dd className="inline">{fmt(job.posted_at)}</dd></div>
        </dl>
      </Card>
      <Card title={`How the match score of ${match.score.toFixed(0)} is made`} id="match" actions={<Button variant="ghost" onClick={() => act(() => api.match(id))}>Recompute</Button>}>
        {match.stale && <Notice tone="warn">Your profile or preferences changed since this was computed. Press Recompute.</Notice>}
        <div className="overflow-x-auto">
          <table className="mt-2 w-full text-left text-sm">
            <caption className="sr-only">Match score breakdown</caption>
            <thead><tr className="border-b"><th className="py-1 pr-3">Component</th><th className="pr-3">Score</th><th className="pr-3">Weight</th><th>Why</th></tr></thead>
            <tbody>
              {match.components.map((c) => (
                <tr key={c.key} className="border-b border-slate-100 align-top">
                  <td className="py-2 pr-3 font-medium">{c.label}</td>
                  <td className="pr-3">{c.score === null || c.score === undefined ? <Badge title="Not enough information; excluded from the score">Unknown</Badge> : `${c.score.toFixed(0)}/100`}</td>
                  <td className="pr-3">{c.weight ? `${(c.weight * 100).toFixed(0)}%` : "—"}</td>
                  <td>{c.explanation}
                    {c.matched.length > 0 && <div className="text-emerald-800">Matched: {c.matched.join(", ")}</div>}
                    {c.gaps.length > 0 && <div className="text-red-800">Gaps: {c.gaps.join(", ")}</div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {match.unknowns.length > 0 && <p className="mt-2 text-sm text-slate-700">Not scored (unknown, not counted against you): {match.unknowns.join(", ")}.</p>}
        <p className="mt-2 text-xs text-slate-600">{match.disclaimer}</p>
      </Card>
      <Card title="Description" id="desc">
        {job.required_qualifications.length > 0 && <><h3 className="font-medium">Required</h3><ul className="list-disc pl-5 text-sm">{job.required_qualifications.map((r) => <li key={r}>{r}</li>)}</ul></>}
        {job.preferred_qualifications.length > 0 && <><h3 className="mt-2 font-medium">Preferred</h3><ul className="list-disc pl-5 text-sm">{job.preferred_qualifications.map((r) => <li key={r}>{r}</li>)}</ul></>}
        {job.responsibilities.length > 0 && <><h3 className="mt-2 font-medium">Responsibilities</h3><ul className="list-disc pl-5 text-sm">{job.responsibilities.map((r) => <li key={r}>{r}</li>)}</ul></>}
        <details className="mt-3"><summary className="cursor-pointer text-sm font-medium">Full text (untrusted content, shown as plain text)</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-xs">{job.description}</pre></details>
      </Card>
    </div>
  );
}
