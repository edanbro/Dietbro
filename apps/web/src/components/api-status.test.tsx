import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiStatus } from "./api-status";

describe("ApiStatus", () => {
  it.each([
    ["checking", "API: checking…"],
    ["ok", "API: ok"],
    ["unreachable", "API: unreachable"],
  ] as const)("renders %s", (status, text) => {
    render(<ApiStatus status={status} />);

    const el = screen.getByText(text);
    expect(el).toBeInTheDocument();
    expect(el).toHaveAttribute("data-api-status", status);
  });
});
