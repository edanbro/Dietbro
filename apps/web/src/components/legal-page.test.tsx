import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AttributionsPage from "@/app/attributions/page";
import CookiesPage from "@/app/cookies/page";
import PrivacyPage from "@/app/privacy/page";
import TermsPage from "@/app/terms/page";
import { CONTACT_EMAIL } from "@/lib/legal";

const PAGES = [
  ["/privacy", PrivacyPage, "Privacy policy"],
  ["/terms", TermsPage, "Terms of use"],
  ["/cookies", CookiesPage, "Cookie policy"],
  ["/attributions", AttributionsPage, "Data sources"],
] as const;

describe("legal pages", () => {
  it.each(PAGES)("%s links to the others and marks itself", (href, Page, title) => {
    render(<Page />);

    expect(screen.getByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Legal" });
    expect(within(nav).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual(
      PAGES.map(([h]) => h),
    );
    expect(within(nav).getByRole("link", { current: "page" })).toHaveAttribute("href", href);
  });

  it.each([PAGES[0], PAGES[1]])("%s says who to contact", (_, Page) => {
    render(<Page />);

    for (const link of screen.getAllByRole("link", { name: CONTACT_EMAIL })) {
      expect(link).toHaveAttribute("href", `mailto:${CONTACT_EMAIL}`);
    }
  });

  it("names health data as needing explicit consent, and every company that handles it", () => {
    render(<PrivacyPage />);

    expect(screen.getByText(/Articles 9\(2\)\(a\)/)).toBeInTheDocument();
    for (const company of ["Clerk", "Vercel", "Render", "Neon", "Upstash", "Anthropic"]) {
      expect(screen.getByText(company)).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Data Protection Commission" })).toHaveAttribute(
      "href",
      "https://www.dataprotection.ie",
    );
  });

  it("lists only sign-in cookies, so there's no banner", () => {
    render(<CookiesPage />);

    const names = screen.getAllByRole("term").map((t) => t.textContent);
    expect(names).toEqual([
      "__session",
      "__client_uat",
      "__clerk_db_jwt",
      "clerk_active_context",
      "theme",
      "mw:…",
      "__clerk_environment",
      "Offline cache",
    ]);
  });

  it("is for adults, and keeps the liability nobody can sign away", () => {
    render(<TermsPage />);

    expect(screen.getByText(/You must be 18 or over/)).toBeInTheDocument();
    expect(screen.getByText(/death or personal injury caused by/)).toBeInTheDocument();
  });
});
