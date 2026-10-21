import { useCallback, useState } from "react";
import { type S, api } from "../api/client";
import { Badge, Button, Card, ConfirmButton, Empty, ErrorBox, Loading, Notice, TextInput, inputCls, useAsync } from "../components/ui";

const MODES: [S["PreferencesOut"]["submission_mode"], string, string][] = [
  ["research_only", "Research only", "Discover and analyze jobs. No applications are prepared."],
  ["prepare_only", "Prepare only", "Generate documents and fill drafts, but never submit."],
  ["review_before_submission", "Review before submission (default)", "You approve each final application. Nothing is submitted without your explicit approval of that exact version."],
  ["authorized_auto_submit", "Authorized auto-submit", "Submits on its own only when EVERY condition holds: the site permits it, all answers are verified, sensitive and legal answers are reviewed by you, documents are approved, limits are respected and no verification is needed."],
];

const split = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

export default function Settings() {
  const load = useCallback(async () => ({ s: await api.settings(), lib: await api.answerLibrary() }), []);
  const { data, error, loading, reload } = useAsync(load);
  const [err, setErr] = useState<unknown>();
  const [msg, setMsg] = useState<string>();
  const [lib, setLib] = useState({ question_type: "start_date", answer_text: "", sensitive: false });
  const [confirmDelete, setConfirmDelete] = useState("");
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const { s, lib: library } = data;
  const p = s.preferences;
  const save = async (patch: S["PreferencesPatch"], okMsg = "Saved.") => { try { await api.patchSettings({ preferences: patch }); setErr(undefined); setMsg(okMsg); await reload(); } catch (e) { setErr(e); setMsg(undefined); } };
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>
      <ErrorBox error={err} />
      {msg && <p role="status" className="text-sm text-emerald-800">{msg}</p>}

      <Card title="Submission mode" id="mode">
        <fieldset>
          <legend className="sr-only">Submission mode</legend>
          <div className="space-y-2">
            {MODES.map(([v, label, desc]) => (
              <label key={v} className={`flex gap-3 rounded-md border p-3 ${p.submission_mode === v ? "border-indigo-600 bg-indigo-50" : "border-slate-200"}`}>
                <input type="radio" name="mode" checked={p.submission_mode === v} onChange={() => save({ submission_mode: v }, `Mode set to “${label}”.`)} className="mt-1" />
                <span><span className="block text-sm font-medium">{label}</span><span className="text-sm text-slate-700">{desc}</span></span>
              </label>
            ))}
          </div>
        </fieldset>
        {p.submission_mode === "authorized_auto_submit" && <div className="mt-3"><Notice tone="warn"><strong>Auto-submit is on.</strong> Applications can be sent without a final click from you, only when all the safety conditions are met. Only the local mock employer can be submitted to today. Switch back to “Review before submission” any time.</Notice></div>}
      </Card>

      <Card title="Limits and preferences" id="prefs">
        <div className="grid gap-3 md:grid-cols-3">
          <TextInput id="mt" type="number" label="Match threshold (0-100)" value={String(p.match_threshold)} onChange={(v) => save({ match_threshold: Number(v) })} />
          <TextInput id="md" type="number" label="Max applications per day" value={String(p.max_applications_per_day)} onChange={(v) => save({ max_applications_per_day: Number(v) })} />
          <TextInput id="rd" type="number" label="Keep data (days)" value={String(p.retention_days)} onChange={(v) => save({ retention_days: Number(v) })} />
          <TextInput id="tr" label="Target roles (comma separated)" value={p.target_roles.join(", ")} onChange={(v) => save({ target_roles: split(v) })} />
          <TextInput id="lo" label="Locations (comma separated)" value={p.locations.join(", ")} onChange={(v) => save({ locations: split(v) })} />
          <div><label htmlFor="rp" className="block text-sm font-medium">Remote preference</label>
            <select id="rp" className={inputCls} value={p.remote_preference} onChange={(e) => save({ remote_preference: e.target.value as S["PreferencesPatch"]["remote_preference"] })}>
              <option value="any">Any</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></select></div>
          <TextInput id="smin" type="number" label="Salary minimum" value={String(p.salary_min ?? "")} onChange={(v) => save({ salary_min: v === "" ? null : Number(v) })} />
          <TextInput id="smax" type="number" label="Salary maximum" value={String(p.salary_max ?? "")} onChange={(v) => save({ salary_max: v === "" ? null : Number(v) })} />
          <TextInput id="scur" label="Currency" value={p.salary_currency} onChange={(v) => save({ salary_currency: v })} />
          <TextInput id="rel" label="Relocation preference" value={p.relocation_preference} onChange={(v) => save({ relocation_preference: v })} hint="Used only if you fill it in" />
          <TextInput id="sd" label="Start date (YYYY-MM-DD)" value={p.start_date} onChange={(v) => save({ start_date: v })} hint="Used only if you fill it in" />
          <div><label htmlFor="ev" className="block text-sm font-medium">Evidence captured after submission</label>
            <select id="ev" className={inputCls} value={p.evidence_capture} onChange={(e) => save({ evidence_capture: e.target.value as "minimal" | "none" })}>
              <option value="minimal">Minimal (outcome, reference, page path)</option><option value="none">None</option></select></div>
        </div>
      </Card>

      <Card title="Job sources" id="sources">
        <ul className="divide-y divide-slate-100">
          {s.job_sources.map((j) => (
            <li key={String(j.name)} className="py-3 text-sm">
              <label className="flex items-start gap-3">
                <input type="checkbox" className="mt-1" checked={!!j.enabled} onChange={async (e) => { try { await api.patchSettings({ job_source_enabled: { [String(j.name)]: e.target.checked } }); await reload(); } catch (x) { setErr(x); } }} />
                <span>
                  <span className="font-medium">{String(j.display_name)}</span>{" "}
                  {j.is_demo ? <Badge tone="amber">Synthetic demo data</Badge> : null} {j.automated_apply ? <Badge tone="blue">Automation tested</Badge> : <Badge>Manual handoff</Badge>}
                  <span className="block text-slate-700">{String(j.notes)}</span>
                  {j.docs_url ? <a className="text-indigo-700 underline" href={String(j.docs_url)} target="_blank" rel="noopener noreferrer">Documentation</a> : null}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Sites ApplyPilot may fill and submit" id="sites">
        {s.site_capabilities.length === 0 ? <Empty title="None" /> : (
          <ul className="space-y-2 text-sm">{s.site_capabilities.map((c) => (
            <li key={String(c.name)}><strong>{String(c.name)}</strong> <span className="text-slate-600">{String(c.origin)}</span><br />
              Fill forms: {c.form_filling ? "yes" : "no"} · Submit: {c.submission ? "yes" : "no"} · Account creation: never · {String(c.restrictions)}</li>
          ))}</ul>
        )}
        <p className="mt-2 text-sm text-slate-700">Every other site is a manual handoff: documents are prepared, but ApplyPilot never fills or submits the form for you.</p>
      </Card>

      <Card title="AI provider" id="ai">
        <p className="text-sm">Provider: <strong>{s.ai_provider}</strong>{s.ai_model && <> · model {s.ai_model}</>} · API key: {s.ai_api_key_set ? "set (hidden)" : "not set"}</p>
        {s.ai_demo_mode && <p className="mt-1 text-sm text-amber-900">Demo mode: the deterministic mock provider writes all drafts and they are labelled DEMO.</p>}
        <p className="mt-1 text-xs text-slate-600">Configured with environment variables in backend/.env (see .env.example). Keys are never shown or stored in the database. Browser: {s.browser_headless ? "headless" : "visible"}.</p>
      </Card>

      <Card title="Your approved answers" id="library">
        <p className="mb-2 text-sm text-slate-700">Reusable answers you have approved. Sensitive answers are used only for the matching question type, and still need your review on each application. Legal declarations are never pre-filled.</p>
        <ul className="divide-y divide-slate-100 text-sm">
          {library.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 py-1.5"><span><Badge>{a.question_type.replaceAll("_", " ")}</Badge> {a.sensitive && <Badge tone="red">sensitive</Badge>} {a.answer_text}</span>
              <Button variant="ghost" onClick={async () => { await api.deleteLibraryAnswer(a.id); await reload(); }}>Delete</Button></li>
          ))}
        </ul>
        {library.length === 0 && <Empty title="No saved answers" />}
        <form className="mt-3 grid gap-3 md:grid-cols-4" onSubmit={async (e) => { e.preventDefault(); try { await api.addLibraryAnswer(lib as S["ApprovedAnswerIn"]); setLib({ ...lib, answer_text: "" }); await reload(); } catch (x) { setErr(x); } }}>
          <div><label htmlFor="lt" className="block text-sm font-medium">Question type</label>
            <select id="lt" className={inputCls} value={lib.question_type} onChange={(e) => setLib({ ...lib, question_type: e.target.value })}>
              {["start_date", "salary_expectation", "relocation", "referral", "work_authorization", "sponsorship", "motivation", "behavioral", "other"].map((t) => <option key={t} value={t}>{t.replaceAll("_", " ")}</option>)}</select></div>
          <div className="md:col-span-2"><TextInput id="la" label="Answer" value={lib.answer_text} onChange={(v) => setLib({ ...lib, answer_text: v })} /></div>
          <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={lib.sensitive} onChange={(e) => setLib({ ...lib, sensitive: e.target.checked })} /> This is a sensitive answer</label>
          <div className="md:col-span-4"><Button type="submit" disabled={!lib.answer_text}>Add answer</Button></div>
        </form>
      </Card>

      <Card title="Your data" id="data">
        <p className="text-sm">Everything is stored only on this computer. You can export or delete all of it.</p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <a className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-100" href="/api/data/export">Export everything (JSON)</a>
          <TextInput id="del" label="Type DELETE to enable permanent deletion" value={confirmDelete} onChange={setConfirmDelete} />
          <ConfirmButton variant="danger" disabled={confirmDelete !== "DELETE"} message="Permanently delete ALL ApplyPilot data on this computer? This cannot be undone." onConfirm={async () => { try { await api.deleteAllData(); setConfirmDelete(""); setMsg("All data deleted."); await reload(); } catch (x) { setErr(x); } }}>Delete all my data</ConfirmButton>
        </div>
      </Card>
    </div>
  );
}
