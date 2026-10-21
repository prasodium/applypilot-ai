import { useCallback, useState } from "react";
import { type RecordKind, type S, api, errorMessage, fieldErrors } from "../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Notice, TextInput, inputCls, useAsync } from "../components/ui";

type Item = { id: number; confirmed: boolean; source: string } & Record<string, unknown>;
type FieldSpec = { key: string; label: string; kind: "text" | "textarea" | "list" | "checkbox"; hint?: string };

const SECTIONS: { kind: RecordKind; title: string; fields: FieldSpec[]; summary: (i: Item) => string }[] = [
  { kind: "education", title: "Education", summary: (i) => `${i.degree || "Studies"}${i.major ? ` in ${i.major}` : ""}, ${i.institution}`,
    fields: [{ key: "institution", label: "Institution", kind: "text" }, { key: "degree", label: "Degree", kind: "text" }, { key: "major", label: "Major", kind: "text" },
      { key: "start_date", label: "Start (YYYY or YYYY-MM)", kind: "text" }, { key: "end_date", label: "End or expected end", kind: "text" },
      { key: "gpa", label: "GPA", kind: "text" }, { key: "gpa_scale", label: "GPA scale", kind: "text" }] },
  { kind: "experience", title: "Work experience", summary: (i) => `${i.title} at ${i.employer}`,
    fields: [{ key: "employer", label: "Employer", kind: "text" }, { key: "title", label: "Title", kind: "text" }, { key: "start_date", label: "Start (YYYY or YYYY-MM)", kind: "text" },
      { key: "end_date", label: "End (leave empty if current)", kind: "text" }, { key: "is_current", label: "I currently work here", kind: "checkbox" },
      { key: "responsibilities", label: "Responsibilities", kind: "list", hint: "One per line" },
      { key: "achievements", label: "Achievements", kind: "list", hint: "One per line. Only things that are true and that you can verify." },
      { key: "technologies", label: "Technologies", kind: "list", hint: "Comma or line separated" }] },
  { kind: "skills", title: "Skills", summary: (i) => `${i.name}${i.proficiency ? ` (${i.proficiency})` : ""}`,
    fields: [{ key: "name", label: "Skill", kind: "text" }, { key: "category", label: "Category", kind: "text" },
      { key: "proficiency", label: "Proficiency (optional)", kind: "text", hint: "Only if you want to state it" }, { key: "evidence", label: "Evidence (optional)", kind: "textarea" }] },
  { kind: "projects", title: "Projects", summary: (i) => String(i.name),
    fields: [{ key: "name", label: "Name", kind: "text" }, { key: "summary", label: "Summary", kind: "textarea" }, { key: "contribution", label: "Your individual contribution", kind: "textarea" },
      { key: "technologies", label: "Technologies", kind: "list", hint: "Comma or line separated" }, { key: "results", label: "Verified results", kind: "list", hint: "One per line; leave empty if none" },
      { key: "url", label: "Repository or demo URL", kind: "text" }] },
];

const toList = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

function RecordEditor({ fields, initial, onSave, onCancel }: { fields: FieldSpec[]; initial: Record<string, unknown>; onSave: (payload: Record<string, unknown>) => Promise<void>; onCancel: () => void }) {
  const [v, setV] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.kind === "list" ? ((initial[f.key] as string[] | undefined) ?? []).join("\n") : f.kind === "checkbox" ? !!initial[f.key] : String(initial[f.key] ?? "")])));
  const [err, setErr] = useState<unknown>();
  const [saving, setSaving] = useState(false);
  const fe = fieldErrors(err);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave(Object.fromEntries(fields.map((f) => [f.key, f.kind === "list" ? toList(String(v[f.key])) : v[f.key]])));
    } catch (x) {
      setErr(x);
    } finally {
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} className="mt-3 grid gap-3 rounded-md border border-indigo-200 bg-indigo-50/40 p-3 md:grid-cols-2">
      {fields.map((f) => {
        const id = `rec-${f.key}`;
        if (f.kind === "checkbox")
          return (
            <label key={f.key} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={!!v[f.key]} onChange={(e) => setV({ ...v, [f.key]: e.target.checked })} /> {f.label}
            </label>
          );
        if (f.kind === "text") return <TextInput key={f.key} id={id} label={f.label} value={String(v[f.key])} onChange={(x) => setV({ ...v, [f.key]: x })} error={fe[f.key]} hint={f.hint} />;
        return (
          <div key={f.key} className="md:col-span-2">
            <label htmlFor={id} className="block text-sm font-medium">{f.label}</label>
            <textarea id={id} rows={f.kind === "list" ? 3 : 2} className={inputCls} value={String(v[f.key])} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} />
            {f.hint && <p className="text-xs text-slate-600">{f.hint}</p>}
            {fe[f.key] && <p role="alert" className="text-xs text-red-700">{fe[f.key]}</p>}
          </div>
        );
      })}
      <div className="md:col-span-2">
        {err !== undefined && Object.keys(fe).length === 0 && <ErrorBox error={err} />}
        <div className="mt-2 flex gap-2">
          <Button variant="primary" type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    </form>
  );
}

function RecordSection({ spec, items, reload }: { spec: (typeof SECTIONS)[number]; items: Item[]; reload: () => Promise<void> }) {
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [error, setError] = useState<unknown>();
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(undefined);
      await reload();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Card title={spec.title} id={`sec-${spec.kind}`} actions={editing === null && <Button onClick={() => setEditing("new")}>Add</Button>}>
      <ErrorBox error={error} />
      {items.length === 0 && editing !== "new" && <Empty title={`No ${spec.title.toLowerCase()} yet`}>Add it manually or upload a résumé in the Résumé studio.</Empty>}
      <ul className="divide-y divide-slate-100">
        {items.map((i) => (
          <li key={i.id} className="py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium">{spec.summary(i)}</span>
              <span className="flex items-center gap-2">
                {i.confirmed ? <Badge tone="green">Confirmed</Badge> : <Badge tone="amber" title={i.source}>Unconfirmed</Badge>}
                {!i.confirmed && <Button variant="ghost" onClick={() => act(() => api.confirmFact(`${{ education: "edu", experience: "exp", skills: "skill", projects: "proj" }[spec.kind]}:${i.id}`))}>Confirm</Button>}
                <Button variant="ghost" onClick={() => setEditing(i.id)}>Edit</Button>
                <Button variant="ghost" onClick={() => { if (window.confirm("Delete this entry?")) void act(() => api.deleteRecord(spec.kind, i.id)); }}>Delete</Button>
              </span>
            </div>
            {editing === i.id && <RecordEditor fields={spec.fields} initial={i} onCancel={() => setEditing(null)} onSave={async (p) => { await api.updateRecord(spec.kind, i.id, p); setEditing(null); await reload(); }} />}
          </li>
        ))}
      </ul>
      {editing === "new" && <RecordEditor fields={spec.fields} initial={{}} onCancel={() => setEditing(null)} onSave={async (p) => { await api.addRecord(spec.kind, p); setEditing(null); await reload(); }} />}
    </Card>
  );
}

const PERSONAL: [keyof S["ProfileFields"], string, string?][] = [
  ["legal_name", "Legal name"], ["preferred_name", "Preferred name"], ["email", "Email", "email"], ["phone", "Phone"], ["city", "City"], ["country", "Country"],
  ["linkedin_url", "LinkedIn URL", "url"], ["github_url", "GitHub URL", "url"], ["portfolio_url", "Portfolio URL", "url"], ["website_url", "Website URL", "url"], ["headline", "Headline"],
];

function PersonalForm({ profile, onSaved }: { profile: S["ProfileOut"]; onSaved: () => Promise<void> }) {
  const [v, setV] = useState<Record<string, string>>(() => ({ ...Object.fromEntries(PERSONAL.map(([k]) => [k, String(profile[k] ?? "")])), summary: profile.summary, work_authorization: profile.work_authorization ?? "",
    requires_sponsorship: profile.requires_sponsorship === null || profile.requires_sponsorship === undefined ? "" : profile.requires_sponsorship ? "yes" : "no" }));
  const [err, setErr] = useState<unknown>();
  const [saved, setSaved] = useState(false);
  const fe = fieldErrors(err);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const { requires_sponsorship, work_authorization, ...rest } = v;
      await api.patchProfile({ ...rest, work_authorization: work_authorization || null, requires_sponsorship: requires_sponsorship === "" ? null : requires_sponsorship === "yes" } as S["ProfilePatch"]);
      setErr(undefined);
      setSaved(true);
      await onSaved();
    } catch (x) {
      setErr(x);
      setSaved(false);
    }
  };
  return (
    <Card title="Personal details" id="personal">
      <form onSubmit={save} className="grid gap-3 md:grid-cols-2">
        {PERSONAL.map(([k, label, type]) => <TextInput key={k} id={`p-${k}`} label={label} type={type} value={v[k]} onChange={(x) => { setV({ ...v, [k]: x }); setSaved(false); }} error={fe[k]} />)}
        <div className="md:col-span-2">
          <label htmlFor="p-summary" className="block text-sm font-medium">Summary</label>
          <textarea id="p-summary" rows={3} className={inputCls} value={v.summary} onChange={(e) => setV({ ...v, summary: e.target.value })} />
        </div>
        <fieldset className="md:col-span-2 rounded-md border border-slate-200 p-3">
          <legend className="px-1 text-sm font-medium">Optional and sensitive: only fill these in if you want ApplyPilot to use them</legend>
          <p className="mb-2 text-xs text-slate-600">Nothing here is ever guessed or inferred. Leave blank and ApplyPilot will always ask you.</p>
          <div className="grid gap-3 md:grid-cols-2">
            <TextInput id="p-wa" label="Work authorization (your own words)" value={v.work_authorization} onChange={(x) => setV({ ...v, work_authorization: x })} />
            <div>
              <label htmlFor="p-sp" className="block text-sm font-medium">Will you require visa sponsorship?</label>
              <select id="p-sp" className={inputCls} value={v.requires_sponsorship} onChange={(e) => setV({ ...v, requires_sponsorship: e.target.value })}>
                <option value="">Not provided (always ask me)</option>
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
            </div>
          </div>
        </fieldset>
        <div className="md:col-span-2 flex items-center gap-3">
          <Button variant="primary" type="submit">Save details</Button>
          {saved && <span role="status" className="text-sm text-emerald-800">Saved.</span>}
        </div>
        {err !== undefined && Object.keys(fe).length === 0 && <div className="md:col-span-2"><ErrorBox error={err} /></div>}
      </form>
    </Card>
  );
}

export default function Profile() {
  const load = useCallback(async () => ({ profile: await api.profile(), facts: await api.facts() }), []);
  const { data, error, loading, reload } = useAsync(load);
  const [msg, setMsg] = useState<string>();
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const { profile, facts } = data;
  const unconfirmed = facts.filter((f) => !f.confirmed);
  const confirmAll = async () => {
    try {
      for (const f of unconfirmed) await api.confirmFact(f.id);
      setMsg(`Confirmed ${unconfirmed.length} item(s).`);
      await reload();
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Candidate profile</h1>
      <Notice>Only <strong>confirmed</strong> facts are used for matching, résumés, cover letters and answers. Data extracted from a résumé stays <em>unconfirmed</em> until you confirm it.</Notice>
      {unconfirmed.length > 0 && (
        <Notice tone="warn">
          {unconfirmed.length} item(s) are unconfirmed and are being ignored. Review them below, then{" "}
          <Button variant="ghost" onClick={confirmAll}>confirm all</Button>
        </Notice>
      )}
      {msg && <p role="status" className="text-sm">{msg}</p>}
      <PersonalForm profile={profile} onSaved={reload} />
      {SECTIONS.map((s) => (
        <RecordSection key={s.kind} spec={s} items={(profile[s.kind === "skills" ? "skills" : s.kind === "projects" ? "projects" : s.kind] as unknown as Item[]) ?? []} reload={async () => { await reload(); }} />
      ))}
      <Card title="All facts and where they came from" id="facts">
        <ul className="divide-y divide-slate-100 text-sm">
          {facts.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span><span className="font-medium">{f.label}</span> <span className="text-slate-600">{f.text}</span></span>
              <span className="flex items-center gap-2"><Badge tone={f.confirmed ? "green" : "amber"}>{f.confirmed ? "Confirmed" : "Unconfirmed"}</Badge><Badge>{f.source.replaceAll("_", " ")}</Badge></span>
            </li>
          ))}
        </ul>
        {facts.length === 0 && <Empty title="No facts yet" />}
      </Card>
    </div>
  );
}
