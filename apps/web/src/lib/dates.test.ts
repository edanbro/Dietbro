import { afterEach, describe, expect, it } from "vitest";

import {
  addDays,
  dateRange,
  daysBetween,
  formatWhen,
  localISODate,
  localTime,
  longDate,
  parseISODate,
} from "./dates";

const originalTZ = process.env.TZ;
afterEach(() => {
  if (originalTZ === undefined) delete process.env.TZ;
  else process.env.TZ = originalTZ;
});

describe("localISODate", () => {
  // 22:30 UTC on 9 Oct is already 10 Oct in Auckland and still 9 Oct in Los Angeles.
  const instant = new Date("2026-10-09T22:30:00Z");

  it.each([
    ["Pacific/Auckland", "2026-10-10"],
    ["America/Los_Angeles", "2026-10-09"],
    ["Europe/London", "2026-10-09"],
  ])("uses the local calendar in %s", (tz, expected) => {
    process.env.TZ = tz;
    expect(localISODate(instant)).toBe(expected);
  });

  it("differs from the UTC date when the zones disagree", () => {
    process.env.TZ = "Pacific/Auckland";
    expect(localISODate(instant)).not.toBe(instant.toISOString().slice(0, 10));
  });

  it("pads months and days", () => {
    expect(localISODate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("date arithmetic", () => {
  it("counts calendar days across DST changes", () => {
    process.env.TZ = "Europe/London";
    // Clocks go back on 25 Oct 2026 in the UK.
    expect(daysBetween("2026-10-24", "2026-10-26")).toBe(2);
    expect(addDays("2026-10-24", 2)).toBe("2026-10-26");
    expect(addDays("2026-03-28", 1)).toBe("2026-03-29");
    expect(addDays("2026-03-29", 1)).toBe("2026-03-30");
  });

  it("goes backwards and across years", () => {
    expect(daysBetween("2026-10-09", "2026-10-01")).toBe(-8);
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("parses to local midnight", () => {
    const d = parseISODate("2026-10-09");
    expect([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours()]).toEqual([2026, 9, 9, 0]);
  });
});

describe("labels", () => {
  it("formats dates in British English", () => {
    expect(longDate("2026-10-15")).toBe("Thursday 15 October");
    expect(dateRange("2026-10-09", "2026-10-15")).toBe("Fri 9 Oct – Thu 15 Oct");
    expect(dateRange("2026-10-09", "2026-10-09")).toBe("Fri 9 Oct");
  });
});

describe("local times", () => {
  it("sends the local wall-clock time", () => {
    expect(localTime(new Date(2026, 9, 9, 7, 5, 3))).toBe("07:05:03");
    process.env.TZ = "Pacific/Auckland";
    expect(localTime(new Date("2026-10-09T22:30:00Z"))).toBe("11:30:00");
  });

  it("says when something comes back, relative to now", () => {
    const now = new Date(2026, 9, 9, 10, 0);
    expect(formatWhen(new Date(2026, 9, 9, 14, 5).toISOString(), now)).toBe("14:05");
    expect(formatWhen(new Date(2026, 9, 10, 9, 12).toISOString(), now)).toBe("tomorrow at 09:12");
    expect(formatWhen(new Date(2026, 10, 1, 0, 0).toISOString(), now)).toBe("Sun 1 Nov at 00:00");
  });
});
