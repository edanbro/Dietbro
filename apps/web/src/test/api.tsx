/** Component-test helpers: a stubbed `fetch` routed by "METHOD /path", and a query client. */
import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { vi } from "vitest";

import { makeQueryClient } from "@/components/providers";

type Reply = Response | Promise<Response>;
export type Routes = Record<string, (req: Request) => Reply>;

export type Call = { method: string; path: string; body: unknown };

/**
 * Stub `fetch`. Keys are "GET /plans/current"; unknown routes answer 404.
 * Returns the calls made, with JSON bodies parsed.
 */
export function mockApi(routes: Routes): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname;
      const text = req.method === "GET" ? "" : await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const handler = routes[`${req.method} ${path}`];
      return handler ? handler(req) : Response.json({ detail: "Not Found" }, { status: 404 });
    }),
  );
  return calls;
}

export const json =
  (body: unknown, status = 200) =>
  () =>
    Response.json(body, { status });

/** A promise you resolve later, to observe pending states. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

export function renderWithClient(ui: React.ReactElement) {
  const client = makeQueryClient();
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}
