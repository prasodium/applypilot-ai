import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { type S, api } from "../api/client";
import { StateBadge } from "../components/StateBadge";
import { Badge, Button, Card, ConfirmButton, Empty, ErrorBox, Loading, Notice, fmt, inputCls, useAsync } from "../components/ui";

type Detail = S["ApplicationDetail"];
type Question = S["QuestionOut"];
type Decision = { allowed: boolean; reasons: string[]; messages: string[] };

const BUSY = new Set(["FORM_IN_PROGRESS", "SUBMISSION_IN_PROGRESS", "APPLICATION_PREPARING"]);
const CONF_TONE = { high: "green", medium: "amber", low: "red" } as const;

function QuestionRow({ q, facts, onSave, disabled }: { q: Question; facts: Map<string, string>; onSave: (id: number, p: S["AnswerPatch"]) => Promise<void>; disabled: boolean }) {
  const a = q.answer;
  const [val, setVal] = useState(a?.answer_text ?? "");
  const [busy, setBusy] = useState(false);
  const changed = val !== (a?.answer_text ?? "");
  const isFile = q.field_type === "file";
  const needs = !isFile && (!a || a.needs_user_input || !a.answer_text);
  const sensitive = q.sensitive_or_legal || a?.sensitive_or_legal;
  const save = async (p: S["AnswerPatch"]) => { setBusy(true); try { await onSave(q.id, p); } finally { setBusy(false); } };
  const id = `q-${q.id}`;
  const options = q.field_type === "checkbox" ? ["Yes"] : q.options;
  const limit = q.max_length ? ` (max ${q.max_length} characters)` : "";
  return (
    <li className={`rounded-md border p-3 ${needs && q.required ? "border-amber-400 bg-amber-50/40" : "border-slate-200"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-sm font-medium">{q.label}{q.required && <span aria-label="required"> *</span>}</label>
        <Badge>{q.question_type.replaceAll("_", " ")}</Badge>
        {q.is_legal && <Badge tone="red">Legal declaration: only you can answer</Badge>}
        {sensitive && !q.is_legal && <Badge tone="red">Sensitive: never assumed</Badge>}
        {a && !isFile && <Badge tone={CONF_TONE[a.confidence]}>{a.confidence} confidence</Badge>}
        {a?.origin === "user" && <Badge tone="blue">Written by you</Badge>}
        {a?.origin === "library" && <Badge tone="blue">From your saved answers</Badge>}
        {needs && <Badge tone="amber">Needs your input</Badge>}
        {a && a.review_status === "approved" && <Badge tone="green">You approved this</Badge>}
      </div>
      {isFile ? (
        <p className="mt-1 text-sm text-slate-700">Attached automatically from this application's {q.question_type === "cover_letter" ? "cover letter" : "résumé"}.</p>
      ) : options.length > 0 ? (
        <select id={id} className={inputCls} value={val} disabled={disabled} onChange={(e) => setVal(e.target.value)}>
          <option value="">{q.field_type === "checkbox" ? "Not ticked" : "Choose…"}</option>
          {options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : q.field_type === "textarea" ? (
        <textarea id={id} rows={4} className={inputCls} value={val} disabled={disabled} maxLength={q.max_length ?? undefined} onChange={(e) => setVal(e.target.value)} />
      ) : (
        <input id={id} className={inputCls} value={val} disabled={disabled} onChange={(e) => setVal(e.target.value)} />
      )}
      <p className="mt-1 text-xs text-slate-600">{a?.notes}{limit}</p>
      {a && a.source_fact_ids.length > 0 && <p className="text-xs text-slate-600">Based on: {a.source_fact_ids.map((f) => facts.get(f) ?? f).join("; ")}</p>}
      {!isFile && !disabled && (
        <div className="mt-2 flex flex-wrap gap-2">
          {changed && <Button variant="primary" disabled={busy} onClick={() => save({ answer_text: val })}>Save answer</Button>}
          {!changed && a && a.answer_text && sensitive && a.review_status !== "approved" && a.review_status !== "edited" && (
            <Button variant="primary" disabled={busy} onClick={() => save({ review_status: "approved" })}>I have reviewed this: approve answer</Button>
          )}
        </div>
      )}
    </li>
  );
}

function DocPreview({ title, id }: { title: string; id: number | null | undefined }) {
  const load = useCallback(async () => (id ? api.document(id) : undefined), [id]);
  const { data } = useAsync(load);
  if (!id) return <p className="text-sm text-slate-600">No {title.toLowerCase()} attached.</p>;
  if (!data) return <Loading />;
  return (
    <details className="rounded-md border border-slate-200 p-2">
      <summary className="cursor-pointer text-sm font-medium">{title} v{data.version} <Badge tone={data.status === "approved" ? "green" : "slate"}>{data.status}</Badge> {data.is_demo && <Badge tone="amber">DEMO</Badge>}</summary>
      <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-xs">{data.text_content}</pre>
      <p className="mt-1 text-xs"><a className="text-indigo-700 underline" href={api.downloadUrl(data.id, "pdf")}>PDF</a> · <a className="text-indigo-700 underline" href={api.downloadUrl(data.id, "docx")}>DOCX</a></p>
    </details>
  );
}

function WorkflowPanel({ appId, state, onChange }: { appId: number; state: string; onChange: () => Promise<void> }) {
  const load = useCallback(async () => {
    const runs = await api.workflows(appId);
    return runs[0] ? await api.workflow(runs[0].id) : undefined;
  }, [appId]);
  const { data: run, reload } = useAsync(load);
  const [err, setErr] = useState<unknown>();
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); setErr(undefined); await reload(); await onChange(); } catch (e) { setErr(e); } };
  if (!run) return <Empty title="No browser run yet" />;
  const live = run.status === "running" || run.status === "queued";
  return (
    <div className="space-y-2 text-sm">
      <p><strong>Browser run #{run.id}</strong> ({run.kind}): <Badge tone={live ? "blue" : run.status === "failed" ? "red" : run.status === "succeeded" ? "green" : "amber"}>{run.status.replaceAll("_", " ")}</Badge></p>
      {run.last_completed_action && <p>Last step: {run.last_completed_action} <span className="text-slate-600">({run.last_verified_outcome})</span></p>}
      {run.next_action && <p>{run.next_action}</p>}
      <ErrorBox error={err} />
      <div className="flex flex-wrap gap-2">
        {live && run.kind === "fill" && <Button onClick={() => act(() => api.pause(run.id))}>Pause</Button>}
        {live && <ConfirmButton message="Cancel this browser run?" onConfirm={() => act(() => api.cancelWorkflow(run.id))}>Cancel run</ConfirmButton>}
        {run.kind === "fill" && ["paused", "interrupted", "waiting_user"].includes(run.status) && state !== "SUBMITTED" && <Button onClick={() => act(() => api.resume(run.id))}>Resume</Button>}
      </div>
      <details><summary className="cursor-pointer">Step log ({run.events.length})</summary>
        <ol className="mt-1 max-h-48 list-decimal overflow-auto pl-5 text-xs">{run.events.map((e) => <li key={e.id}>{e.action}{e.detail ? ` — ${e.detail}` : ""} {!e.ok && <strong>(failed)</strong>}</li>)}</ol></details>
      {state === "SUBMISSION_IN_PROGRESS" && <Notice tone="warn">Submitting. Do not refresh or retry: the result will be verified from the page.</Notice>}
    </div>
  );
}

export default function ApplicationReview() {
  const id = Number(useParams().id);
  const load = useCallback(async () => ({ app: await api.application(id), facts: await api.facts() }), [id]);
  const { data, error, loading, reload } = useAsync(load);
  const [err, setErr] = useState<unknown>();
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState<"submitted" | "failed">("submitted");
  const state = data?.app.state;
  useEffect(() => {
    if (!state || !BUSY.has(state)) return;
    const t = setInterval(() => void reload(), 1500);
    return () => clearInterval(t);
  }, [state, reload]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data) return null;
  const a: Detail = data.app;
  const facts = new Map(data.facts.map((f) => [f.id, f.label]));
  const decision = a.submit_decision as Decision | null;
  const editable = !["SUBMITTED", "SUBMISSION_IN_PROGRESS", "SUBMISSION_UNCONFIRMED", "APPLICATION_WITHDRAWN", "JOB_CLOSED"].includes(a.state);
  const mock = a.target_kind === "mock";
  const run = async (fn: () => Promise<unknown>) => { try { await fn(); setErr(undefined); await reload(); } catch (e) { setErr(e); await reload(); } };
  const saveAnswer = async (qid: number, p: S["AnswerPatch"]) => { await api.patchApplication(id, { answers: { [qid]: p } }); await reload(); };
  const reasons = (err as { details?: { messages?: string[] } } | undefined)?.details?.messages;
  return (
    <div className="space-y-6">
      <p><Link className="text-sm text-indigo-700 underline" to="/applications">← Applications</Link></p>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{a.title}</h1>
          <p className="text-slate-700">{a.company} · {a.location || "—"} · <Link className="underline" to={`/jobs/${a.job_id}`}>job details</Link></p>
          <p className="mt-1 flex flex-wrap items-center gap-2"><StateBadge state={a.state} /> <span className="text-sm text-slate-600">Version {a.version}{a.approved_version ? `, approved v${a.approved_version}` : ""}</span>
            {a.is_demo && <Badge tone="amber">DEMO</Badge>} {mock && <Badge tone="amber">Mock employer: not a real application</Badge>}</p>
        </div>
      </div>
      <div aria-live="polite" className="space-y-2">
        <Notice tone={a.state === "SUBMITTED" ? "ok" : a.state === "SUBMISSION_UNCONFIRMED" || a.state === "APPLICATION_FAILED" ? "warn" : "info"}><strong>Next:</strong> {a.next_action}</Notice>
        {a.last_error && <Notice tone="warn">{a.last_error}</Notice>}
        {a.state === "SUBMITTED" && (
          <Notice tone="ok">
            {a.outcome === "user_attested" ? "You recorded this as submitted. It was not verified by ApplyPilot." : `Confirmed by the site. Reference: ${a.confirmation_reference}.`}
            {mock && " (This was the local mock employer, so no real application was sent.)"}
          </Notice>
        )}
        {a.state === "SUBMISSION_UNCONFIRMED" && <Notice tone="warn"><strong>The result is unclear.</strong> ApplyPilot will <strong>not</strong> retry. Check the employer's site or your email, then record what you found below.</Notice>}
        <ErrorBox error={err} />
        {reasons && <ul className="list-disc pl-5 text-sm text-red-900">{reasons.map((m) => <li key={m}>{m}</li>)}</ul>}
      </div>

      {!mock && (
        <Card title="Manual handoff" id="manual">
          <p className="text-sm">ApplyPilot has no authorized automation for this site, so it will not fill or submit the form. Download the prepared documents, apply on the employer's site yourself, then record the result below.</p>
          {a.application_url.startsWith("http") && <p className="mt-2 text-sm"><a className="text-indigo-700 underline" href={a.application_url} target="_blank" rel="noopener noreferrer">Open the application page</a></p>}
        </Card>
      )}

      <Card title={`Checklist ${a.ready_for_approval ? "(complete)" : ""}`} id="check">
        {a.issues.length === 0 ? <p className="text-sm">✓ No unanswered or unreviewed items.{mock && a.state === "READY_FOR_REVIEW" && a.ready_for_approval ? " The form was filled and every value verified in the browser for this version." : ""}</p> : (
          <ul className="space-y-1 text-sm">{a.issues.map((i, k) => <li key={k}><span aria-hidden="true">✕ </span>{i.message}</li>)}</ul>
        )}
      </Card>

      {mock && (
        <Card title="Questions and answers" id="qa">
          {a.questions.length === 0 ? <Empty title="No form questions yet">{BUSY.has(a.state) ? "The browser is reading the form…" : "Press “Check form in browser” to read and fill the form."}</Empty> : (
            <ul className="space-y-3">{a.questions.map((q) => <QuestionRow key={`${q.id}-${q.answer?.answer_text}-${q.answer?.review_status}`} q={q} facts={facts} onSave={saveAnswer} disabled={!editable} />)}</ul>
          )}
        </Card>
      )}

      <Card title="Documents" id="docs">
        <div className="grid gap-3 md:grid-cols-2"><DocPreview title="Résumé" id={a.resume_document_id} /><DocPreview title="Cover letter" id={a.cover_letter_document_id} /></div>
        <p className="mt-2 text-xs text-slate-600">Approving the application approves these exact drafts. Edit them in the Résumé studio; any change invalidates your approval.</p>
      </Card>

      {mock && <Card title="Browser" id="browser"><WorkflowPanel appId={id} state={a.state} onChange={reload} /></Card>}

      <Card title="Decide" id="decide">
        {decision && !decision.allowed && a.state !== "SUBMITTED" && a.state !== "APPLICATION_WITHDRAWN" && (
          <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
            <p className="font-medium">Submission is currently blocked because:</p>
            <ul className="list-disc pl-5">{decision.messages.map((m) => <li key={m}>{m}</li>)}</ul>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {mock && <Button disabled={BUSY.has(a.state) || !editable} onClick={() => run(() => api.fill(id))}>Check form in browser</Button>}
          {mock && <ConfirmButton variant="primary" disabled={!a.ready_for_approval} message={`Approve version ${a.version} of this application? Any later change will cancel the approval.`} onConfirm={() => run(() => api.approve(id, a.version))}>Approve this version</ConfirmButton>}
          {mock && <ConfirmButton variant="danger" disabled={!decision?.allowed} message="Submit this application now? This sends it to the MOCK employer test site (not a real employer). The result is verified from the page and never retried automatically." onConfirm={() => run(() => api.submit(id))}>Submit</ConfirmButton>}
          {a.state !== "SUBMITTED" && a.state !== "APPLICATION_WITHDRAWN" && a.state !== "SUBMISSION_IN_PROGRESS" && <ConfirmButton message="Withdraw this application?" onConfirm={() => run(() => api.cancelApplication(id))}>Withdraw</ConfirmButton>}
        </div>
        {(a.state === "SUBMISSION_UNCONFIRMED" || (!mock && a.state === "READY_FOR_REVIEW")) && (
          <fieldset className="mt-4 rounded-md border border-slate-200 p-3">
            <legend className="px-1 text-sm font-medium">Record what happened (your own report)</legend>
            <label className="mr-4 text-sm"><input type="radio" name="o" checked={outcome === "submitted"} onChange={() => setOutcome("submitted")} /> I submitted it / it went through</label>
            <label className="text-sm"><input type="radio" name="o" checked={outcome === "failed"} onChange={() => setOutcome("failed")} /> It was not submitted</label>
            <label htmlFor="note" className="mt-2 block text-sm">Note (optional)</label>
            <input id="note" className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
            <Button className="mt-2" variant="primary" onClick={() => run(() => api.attest(id, { outcome, note }))}>Record</Button>
            <p className="mt-1 text-xs text-slate-600">This is stored as “reported by you”. It is not machine-verified.</p>
          </fieldset>
        )}
      </Card>
      <p className="text-xs text-slate-600">Created {fmt(a.created_at)} · updated {fmt(a.updated_at)}</p>
    </div>
  );
}
