import { type ButtonHTMLAttributes, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../api/client";

export function useAsync<T>(fn: () => Promise<T>) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fn();
      if (alive.current) {
        setData(d);
        setError(undefined);
      }
    } catch (e) {
      if (alive.current) setError(e);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [fn]);
  useEffect(() => {
    alive.current = true;
    void reload();
    return () => {
      alive.current = false;
    };
  }, [reload]);
  return { data, error, loading, reload, setData };
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" };
export function Button({ variant = "secondary", className = "", ...p }: BtnProps) {
  const base = "inline-flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50";
  const v = {
    primary: "bg-indigo-700 text-white hover:bg-indigo-800",
    secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-100",
    danger: "bg-red-700 text-white hover:bg-red-800",
    ghost: "text-indigo-700 hover:bg-indigo-50",
  }[variant];
  return <button type="button" className={`${base} ${v} ${className}`} {...p} />;
}

export function Card({ title, children, actions, id }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <section id={id} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby={id ? `${id}-t` : undefined}>
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && (
            <h2 id={id ? `${id}-t` : undefined} className="text-base font-semibold">
              {title}
            </h2>
          )}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p role="status" className="text-sm text-slate-600">
      {label}…
    </p>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
      {errorMessage(error)}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "ok"; children: ReactNode }) {
  const c = { info: "border-sky-300 bg-sky-50 text-sky-900", warn: "border-amber-400 bg-amber-50 text-amber-950", ok: "border-emerald-300 bg-emerald-50 text-emerald-900" }[tone];
  return (
    <div role="status" className={`rounded-md border p-3 text-sm ${c}`}>
      {children}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 p-6 text-center">
      <p className="font-medium">{title}</p>
      {children && <p className="mt-1 text-sm text-slate-600">{children}</p>}
    </div>
  );
}

export function Badge({ tone = "slate", children, title }: { tone?: "slate" | "green" | "amber" | "red" | "blue" | "violet"; children: ReactNode; title?: string }) {
  const c = {
    slate: "bg-slate-100 text-slate-800 ring-slate-300",
    green: "bg-emerald-50 text-emerald-900 ring-emerald-300",
    amber: "bg-amber-50 text-amber-900 ring-amber-400",
    red: "bg-red-50 text-red-900 ring-red-300",
    blue: "bg-sky-50 text-sky-900 ring-sky-300",
    violet: "bg-violet-50 text-violet-900 ring-violet-300",
  }[tone];
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${c}`}>
      {children}
    </span>
  );
}

export const inputCls = "mt-1 block w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm shadow-sm focus:border-indigo-600";

export function Field({ label, error, hint, children, htmlFor }: { label: string; error?: string; hint?: string; children: ReactNode; htmlFor: string }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-800">
        {label}
      </label>
      {children}
      {hint && <p className="mt-0.5 text-xs text-slate-600">{hint}</p>}
      {error && (
        <p role="alert" className="mt-0.5 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextInput({ id, label, value, onChange, error, hint, type = "text", required }: {
  id: string; label: string; value: string; onChange: (v: string) => void; error?: string; hint?: string; type?: string; required?: boolean;
}) {
  return (
    <Field label={label} htmlFor={id} error={error} hint={hint}>
      <input id={id} type={type} className={inputCls} value={value} required={required} aria-invalid={!!error} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function ConfirmButton({ children, message, onConfirm, variant = "secondary", disabled }: {
  children: ReactNode; message: string; onConfirm: () => void; variant?: BtnProps["variant"]; disabled?: boolean;
}) {
  return (
    <Button variant={variant} disabled={disabled} onClick={() => { if (window.confirm(message)) onConfirm(); }}>
      {children}
    </Button>
  );
}

export function fmt(d?: string | null): string {
  return d ? new Date(d).toLocaleString() : "—";
}
