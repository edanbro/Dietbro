import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/browser";

import { ErrorAlert } from "./form-bits";

describe("ErrorAlert", () => {
  it("lists the API's messages and offers a retry when asked", () => {
    const onRetry = vi.fn();
    render(<ErrorAlert error={new ApiError(503, ["The planner is busy."])} onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toHaveTextContent("The planner is busy.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("has no retry button for form errors", () => {
    render(<ErrorAlert error={new ApiError(400, ["Too low."])} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders nothing without an error", () => {
    const { container } = render(<ErrorAlert error={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
