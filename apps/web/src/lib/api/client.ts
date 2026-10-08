import createClient from "openapi-fetch";

import type { paths } from "./schema";

export type ApiClient = ReturnType<typeof createClient<paths>>;

/** Server-side API client. `API_URL` is read at request time, never inlined into the bundle. */
export function createApiClient(
  baseUrl: string = process.env.API_URL ?? "http://localhost:8000",
  fetchImpl?: typeof fetch,
): ApiClient {
  return createClient<paths>({ baseUrl, fetch: fetchImpl });
}
