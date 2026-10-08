import { createApiClient, type ApiClient } from "./client";

export type ApiHealth = "ok" | "unreachable";

const TIMEOUT_MS = 2000;

export async function getApiHealth(client: ApiClient = createApiClient()): Promise<ApiHealth> {
  try {
    const { data } = await client.GET("/healthz", { signal: AbortSignal.timeout(TIMEOUT_MS) });
    return data?.status === "ok" ? "ok" : "unreachable";
  } catch {
    return "unreachable";
  }
}
