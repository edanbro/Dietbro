import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "./client";
import { getApiHealth } from "./health";

function clientReturning(fetchImpl: typeof fetch) {
  return createApiClient("http://api.test", fetchImpl);
}

describe("getApiHealth", () => {
  it("returns ok when /healthz answers ok", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => Response.json({ status: "ok" }));

    await expect(getApiHealth(clientReturning(fetchImpl))).resolves.toBe("ok");
    const request = fetchImpl.mock.calls[0]?.[0] as Request;
    expect(request.url).toBe("http://api.test/healthz");
  });

  it("returns unreachable on an error status", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => new Response("boom", { status: 500 }));

    await expect(getApiHealth(clientReturning(fetchImpl))).resolves.toBe("unreachable");
  });

  it("returns unreachable when the request fails", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });

    await expect(getApiHealth(clientReturning(fetchImpl))).resolves.toBe("unreachable");
  });
});
