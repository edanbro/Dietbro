import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GradeBadge, ProductThumb } from "./food-bits";

describe("GradeBadge", () => {
  it("names the grade for screen readers", () => {
    render(<GradeBadge grade="B" />);
    expect(screen.getByText("Nutrition grade B")).toBeInTheDocument();
  });

  it("shows nothing without a grade", () => {
    const { container } = render(<GradeBadge grade={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ProductThumb", () => {
  it("shows the photo only when there is one", () => {
    const url = "https://images.openfoodfacts.org/images/products/1/front.200.jpg";
    const { container, rerender } = render(<ProductThumb url={url} />);
    expect(container.querySelector("img")).toHaveAttribute("src", url);
    rerender(<ProductThumb url={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
