import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

/** Renders a page inside a router at `path` so useParams works. */
export function renderAt(ui: ReactElement, path = "/", route = "*") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={route} element={ui} />
      </Routes>
    </MemoryRouter>,
  );
}

type Handler = (url: string, init?: RequestInit) => unknown | Promise<unknown>;

/** Replaces fetch with a router of fake API responses: [method, path-prefix, handler]. Unmatched calls fail the test loudly. */
export function mockApi(routes: [string, string, Handler][]) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^\/api/, "");
    const method = init?.method ?? "GET";
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const hit = routes.find(([m, p]) => m === method && url.startsWith(p));
    if (!hit) throw new Error(`Unexpected request: ${method} ${url}`);
    const out = await hit[2](url, init);
    if (out instanceof Response) return out;
    return new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  return calls;
}

export const errorResponse = (status: number, code: string, message: string, details: object = {}) =>
  new Response(JSON.stringify({ error: { code, message, details } }), { status, headers: { "Content-Type": "application/json" } });
