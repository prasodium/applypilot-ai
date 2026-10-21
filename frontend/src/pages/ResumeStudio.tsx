import { useCallback, useState } from "react";
import { type S, api, errorMessage } from "../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, TextInput, fmt, inputCls, useAsync } from "../components/ui";

function ParsePreview({ doc, onDone }: { doc: S["DocumentDetail"]; onDone: () => void }) {
  const parsed = doc.parsed_data as unknown as S["ParsedResume"];
  const [p, setP] = useState<S["ParsedResume"]>(parsed);
  const [sel, setSel] = useState({
    edu: p.education.map(() => true), exp: p.experience.map(() => true), skills: p.skills.map(() => true), proj: p.projects.map(() => true),
  });
  const [err, setErr] = useState<unknown>();
  const [done, setDone] = useState<string>();
  const pick = <T,>(arr: T[], s: boolean[]) => arr.filter((_, i) => s[i]);
  const toggle = (k: keyof typeof sel, i: number) => setSel({ ...sel, [k]: sel[k].map((x, j) => (j === i ? !x : x)) });
  const apply = async (confirm: boolean) => {
    try {
      await api.applyParse(doc.id, {
        parsed: { ...p, education: pick(p.education, sel.edu), experience: pick(p.experience, sel.exp), skills: pick(p.skills, sel.skills), projects: pick(p.projects, sel.proj) },
        confirm, apply_profile_fields: true, replace_existing: false,
      });
      setDone(confirm ? "Saved and confirmed. A master résumé was generated from your confirmed facts." : "Saved as UNCONFIRMED. Review and confirm each item in your profile.");
      setErr(undefined);
      onDone();
    } catch (e) {
      setErr(e);
    }
  };
  const top: [keyof S["ProfileFields"], string][] = [["legal_name", "Name"], ["email", "Email"], ["phone", "Phone"], ["city", "City"], ["country", "Country"], ["headline", "Headline"], ["linkedin_url", "LinkedIn"], ["github_url", "GitHub"]];
  const check = (k: keyof typeof sel, i: number, label: string) => (
    <label className="flex items-start gap-2 py-1 text-sm"><input type="checkbox" className="mt-1" checked={sel[k][i]} onChange={() => toggle(k, i)} />{label}</label>
  );
  return (
    <Card title="Review what was extracted" id="parse">
      <Notice tone="warn">Extracted automatically, so it may be wrong. Correct the fields, untick anything that is not right, then save. <strong>Nothing is a verified fact until you confirm it.</strong></Notice>
      {p.warnings.length > 0 && <ul className="mt-2 list-disc pl-5 text-sm text-amber-900">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {top.map(([k, label]) => <TextInput key={k} id={`pp-${k}`} label={label} value={String(p.profile[k] ?? "")} onChange={(x) => setP({ ...p, profile: { ...p.profile, [k]: x } })} />)}
      </div>
      <h3 className="mt-4 font-medium">Education</h3>
      {p.education.map((e, i) => <div key={i}>{check("edu", i, `${e.degree} ${e.major ? "in " + e.major : ""}, ${e.institution} (${e.start_date || "?"} to ${e.end_date || "?"})`)}</div>)}
      <h3 className="mt-3 font-medium">Experience</h3>
      {p.experience.map((e, i) => <div key={i}>{check("exp", i, `${e.title} at ${e.employer} (${e.start_date || "?"} to ${e.is_current ? "present" : e.end_date || "?"}), ${e.responsibilities.length} bullet(s)`)}</div>)}
      <h3 className="mt-3 font-medium">Skills</h3>
      <div className="flex flex-wrap gap-x-4">{p.skills.map((s, i) => <div key={i}>{check("skills", i, s.name)}</div>)}</div>
      <h3 className="mt-3 font-medium">Projects</h3>
      {p.projects.map((j, i) => <div key={i}>{check("proj", i, `${j.name}${j.url ? " (" + j.url + ")" : ""}`)}</div>)}
      <ErrorBox error={err} />
      {done && <p role="status" className="mt-2 text-sm text-emerald-800">{done}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => apply(true)}>I checked it: confirm and save</Button>
        <Button onClick={() => apply(false)}>Save as unconfirmed</Button>
      </div>
    </Card>
  );
}

function DocViewer({ id }: { id: number }) {
  const load = useCallback(() => api.document(id), [id]);
  const { data } = useAsync(load);
  if (!data) return <Loading />;
  return (
    <div className="mt-2 space-y-2 text-sm">
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs">{data.text_content}</pre>
      {data.claims.length > 0 && (
        <details>
          <summary className="cursor-pointer font-medium">Where each claim comes from ({data.claims.length})</summary>
          <ul className="mt-1 list-disc pl-5 text-xs">{data.claims.slice(0, 80).map((c, i) => <li key={i}>{String(c.text).slice(0, 90)} <span className="text-slate-600">[{(c.source_fact_ids as string[]).join(", ") || "your edit"}]</span></li>)}</ul>
        </details>
      )}
    </div>
  );
}

export default function ResumeStudio() {
  const load = useCallback(async () => ({ docs: await api.documents(), jobs: (await api.jobs({ page_size: 100 })).items }), []);
  const { data, error, loading, reload } = useAsync(load);
  const [upload, setUpload] = useState<S["DocumentDetail"]>();
  const [err, setErr] = useState<unknown>();
  const [open, setOpen] = useState<number>();
  const [jobId, setJobId] = useState("");
  const [diffLines, setDiffLines] = useState<string[]>();
  const run = async (fn: () => Promise<unknown>) => {
    try { await fn(); setErr(undefined); await reload(); } catch (e) { setErr(e); }
  };
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const drafts = data.docs.filter((d) => d.kind !== "resume_upload");
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Résumé studio</h1>
      <Card title="Upload a résumé (PDF or DOCX)" id="upload">
        <label htmlFor="file" className="block text-sm font-medium">Choose a file (max 10 MB). It is read locally and never leaves this computer.</label>
        <input id="file" type="file" accept=".pdf,.docx" className="mt-2 block text-sm" onChange={async (e) => {
          const f = e.target.files?.[0];
          if (!f) return;
          try { setUpload(await api.upload(f)); setErr(undefined); await reload(); } catch (x) { setErr(x); setUpload(undefined); }
          e.target.value = "";
        }} />
        <div className="mt-2"><ErrorBox error={err} /></div>
      </Card>
      {upload && <ParsePreview doc={upload} onDone={reload} />}
      <Card title="Generate drafts" id="gen">
        <p className="mb-2 text-sm text-slate-700">Drafts only use your <strong>confirmed</strong> facts. They stay drafts until you review and approve them.</p>
        <div className="flex flex-wrap items-end gap-3">
          <Button onClick={() => run(() => api.generateResume())}>Rebuild master résumé</Button>
          <div>
            <label htmlFor="job" className="block text-sm font-medium">Tailor for a job</label>
            <select id="job" className={inputCls} value={jobId} onChange={(e) => setJobId(e.target.value)}>
              <option value="">Choose a job…</option>
              {data.jobs.map((j) => <option key={j.id} value={j.id}>{j.title} at {j.company}</option>)}
            </select>
          </div>
          <Button disabled={!jobId} onClick={() => run(() => api.generateResume(Number(jobId)))}>Tailored résumé</Button>
          <Button disabled={!jobId} onClick={() => run(() => api.generateCoverLetter(Number(jobId)))}>Cover letter</Button>
        </div>
      </Card>
      <Card title="Documents and versions" id="docs">
        {data.docs.length === 0 && <Empty title="No documents yet">Upload a résumé above.</Empty>}
        <ul className="divide-y divide-slate-100">
          {data.docs.map((d) => (
            <li key={d.id} className="py-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-medium">{d.filename || d.kind} <span className="text-slate-600">v{d.version}</span></span>
                <span className="flex flex-wrap items-center gap-2">
                  <Badge>{d.kind.replaceAll("_", " ")}</Badge>
                  {d.is_demo && <Badge tone="amber">DEMO</Badge>}
                  {d.kind !== "resume_upload" && <Badge tone={d.status === "approved" ? "green" : "slate"}>{d.status}</Badge>}
                  <time className="text-slate-600" dateTime={d.created_at}>{fmt(d.created_at)}</time>
                  <Button variant="ghost" onClick={() => setOpen(open === d.id ? undefined : d.id)}>{open === d.id ? "Hide" : "Preview"}</Button>
                  {d.kind !== "resume_upload" && <>
                    <a className="text-indigo-700 underline" href={api.downloadUrl(d.id, "docx")}>DOCX</a>
                    <a className="text-indigo-700 underline" href={api.downloadUrl(d.id, "pdf")}>PDF</a>
                    {d.status !== "approved" && <Button variant="ghost" onClick={() => run(() => api.approveDocument(d.id))}>Approve</Button>}
                  </>}
                  {d.parent_id && <Button variant="ghost" onClick={async () => { try { setDiffLines((await api.diff(d.id, d.parent_id!)).lines); } catch (e) { setErr(e); } }}>Compare with previous</Button>}
                  <Button variant="ghost" onClick={() => { if (window.confirm("Delete this document?")) void run(() => api.deleteDocument(d.id)); }}>Delete</Button>
                </span>
              </div>
              {open === d.id && <DocViewer id={d.id} />}
            </li>
          ))}
        </ul>
        {diffLines && (
          <div className="mt-3"><h3 className="font-medium">Changes</h3>
            <pre className="max-h-80 overflow-auto rounded-md bg-slate-50 p-3 text-xs" aria-label="Diff">{diffLines.length ? diffLines.map((l, i) => <span key={i} className={l.startsWith("+") ? "text-emerald-800" : l.startsWith("-") ? "text-red-800" : ""}>{l}{"\n"}</span>) : "No differences."}</pre>
            <Button variant="ghost" onClick={() => setDiffLines(undefined)}>Close</Button>
          </div>
        )}
        {drafts.length === 0 && data.docs.length > 0 && <p className="mt-2 text-sm text-slate-600">No generated drafts yet.</p>}
        {err !== undefined && !upload && <p className="sr-only">{errorMessage(err)}</p>}
      </Card>
    </div>
  );
}
