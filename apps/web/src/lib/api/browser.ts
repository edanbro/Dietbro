"use client";

import { useAuth } from "@clerk/nextjs";
import createClient from "openapi-fetch";
import { useMemo } from "react";

import type { ApiClient } from "./client";
import type { paths } from "./schema";

/** Browser API base URL (inlined at build time). */
export const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Typed API client that sends the signed-in user's Clerk session token. */
export function useApi(): ApiClient {
  const { getToken } = useAuth();
  return useMemo(() => {
    const client = createClient<paths>({ baseUrl: PUBLIC_API_URL });
    client.use({
      async onRequest({ request }) {
        const token = await sessionToken(getToken);
        if (token) request.headers.set("Authorization", `Bearer ${token}`);
        return request;
      },
    });
    return client;
  }, [getToken]);
}

export const AUTH_UNREACHABLE =
  "Couldn't reach the sign-in service. If an ad or tracker blocker is on, allow this site and try again.";

/**
 * The session token for an API call. Fails after `timeoutMs` instead of hanging when Clerk's
 * servers are blocked (ad blockers, strict tracking prevention), and waits up to `graceMs` for
 * a session that is still being set up right after sign-in instead of sending no token (401).
 */
export async function sessionToken(
  getToken: () => Promise<string | null>,
  { timeoutMs = 10_000, graceMs = 2_000, pollMs = 200 } = {},
): Promise<string | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new ApiError(0, [AUTH_UNREACHABLE])), timeoutMs);
  });
  const fetchToken = async () => {
    const deadline = Date.now() + graceMs;
    let token = await getToken();
    while (!token && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, pollMs));
      token = await getToken();
    }
    return token;
  };
  try {
    return await Promise.race([fetchToken(), timeout]);
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly messages: string[],
  ) {
    super(messages.join("; ") || `request failed (${status})`);
  }
}

type Detail = string | { msg?: string; loc?: (string | number)[] };

/** Flatten FastAPI error bodies (`{detail: "..."}`, `{detail: ["..."]}`, validation errors). */
export function errorMessages(body: unknown): string[] {
  const detail = (body as { detail?: Detail | Detail[] } | undefined)?.detail;
  if (detail === undefined) return [];
  const items = Array.isArray(detail) ? detail : [detail];
  return items.map((d) => {
    if (typeof d === "string") return d;
    const field = d.loc?.filter((p) => p !== "body").join(".");
    return field ? `${field}: ${d.msg ?? "invalid"}` : (d.msg ?? "invalid");
  });
}

/** Unwrap an openapi-fetch result: data, or throw ApiError with readable messages. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, errorMessages(result.error));
  }
  return result.data as T;
}
