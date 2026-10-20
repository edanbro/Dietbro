"use client";

import Link from "next/link";

import { ErrorAlert } from "@/components/form-bits";
import { Skeleton } from "@/components/ui/skeleton";
import { aisle } from "@/lib/aisles";
import { type Spending, useSpending } from "@/lib/api/hooks";
import { shortDate } from "@/lib/dates";
import { formatMoney } from "@/lib/format";

const W = 320;
const H = 140;
const PAD = { top: 10, right: 8, bottom: 22, left: 8 };

/**
 * Weekly spend as hand-drawn SVG bars (no chart library), with each week's plan estimate as a
 * saffron tick across its bar. A sentence summarises it for screen readers and everyone else.
 */
export function SpendingChart({ data }: { data: Spending }) {
  const weeks = data.weeks;
  const top = Math.max(1, ...weeks.map((w) => Math.max(w.spent_minor, w.planned_minor ?? 0)));
  const slot = (W - PAD.left - PAD.right) / weeks.length;
  const bar = Math.max(4, slot * 0.62);
  const y = (minor: number) => PAD.top + (1 - minor / top) * (H - PAD.top - PAD.bottom);
  const money = (minor: number) => formatMoney(minor, data.currency);
  const bought = weeks.filter((w) => w.spent_minor > 0);
  const average = bought.length
    ? Math.round(bought.reduce((sum, w) => sum + w.spent_minor, 0) / bought.length)
    : 0;
  const summary = `About ${money(average)} a week on groceries, over ${bought.length} ${
    bought.length === 1 ? "week" : "weeks"
  } with receipts.`;

  return (
    <figure className="flex flex-col gap-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={summary}>
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y(0)}
          y2={y(0)}
          className="stroke-border"
        />
        {weeks.map((w, i) => {
          const cx = PAD.left + slot * i + slot / 2;
          return (
            <g key={w.start}>
              {w.spent_minor > 0 ? (
                <rect
                  x={cx - bar / 2}
                  y={y(w.spent_minor)}
                  width={bar}
                  height={y(0) - y(w.spent_minor)}
                  rx={3}
                  className="fill-primary motion-safe:animate-rise"
                >
                  <title>{`Week of ${shortDate(w.start)}: ${money(w.spent_minor)}`}</title>
                </rect>
              ) : null}
              {w.planned_minor ? (
                <line
                  x1={cx - bar / 2 - 2}
                  x2={cx + bar / 2 + 2}
                  y1={y(w.planned_minor)}
                  y2={y(w.planned_minor)}
                  strokeWidth={2.5}
                  strokeLinecap="round"
                  className="stroke-brand-warm"
                >
                  <title>{`Plan estimate: ${money(w.planned_minor)}`}</title>
                </line>
              ) : null}
            </g>
          );
        })}
        <text x={PAD.left} y={H - 6} fontSize={10} className="fill-muted-foreground">
          {shortDate(weeks[0]!.start)}
        </text>
        <text
          x={W - PAD.right}
          y={H - 6}
          fontSize={10}
          textAnchor="end"
          className="fill-muted-foreground"
        >
          This week
        </text>
      </svg>
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>{summary}</span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block size-2.5 rounded-sm bg-primary" />
          Spent
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-0.5 w-3 rounded bg-brand-warm" />
          Plan estimate
        </span>
      </figcaption>
    </figure>
  );
}

/** Where the money went, by aisle, over the whole period. */
function TopAisles({ data }: { data: Spending }) {
  const byAisle = new Map<string, number>();
  for (const c of data.categories) {
    const name = aisle(c.category);
    byAisle.set(name, (byAisle.get(name) ?? 0) + c.spent_minor);
  }
  const rows = [...byAisle].sort((a, b) => b[1] - a[1]).slice(0, 5);
  const total = rows.reduce((sum, [, v]) => sum + v, 0) || 1;
  if (!rows.length) return null;
  return (
    <ul className="flex flex-col gap-2" aria-label="Most spent on">
      {rows.map(([name, minor]) => (
        <li key={name} className="flex flex-col gap-1 text-sm">
          <span className="flex justify-between gap-2">
            <span>{name}</span>
            <span className="tabular-nums">{formatMoney(minor, data.currency)}</span>
          </span>
          <span aria-hidden className="h-1.5 rounded-full bg-muted">
            <span
              className="block h-full origin-left rounded-full bg-primary/70 motion-safe:animate-grow-x"
              style={{ width: `${(minor / total) * 100}%` }}
            />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The diary's spending section: weekly bars and the top aisles, from confirmed receipts. */
export function SpendingSection() {
  const spending = useSpending(12);
  return (
    <section aria-labelledby="spending" className="flex flex-col gap-3">
      <h2 id="spending" className="text-xl font-semibold">
        Spending
      </h2>
      {spending.isPending ? (
        <Skeleton className="h-40" />
      ) : spending.error ? (
        <ErrorAlert error={spending.error} onRetry={() => void spending.refetch()} />
      ) : spending.data.weeks.some((w) => w.spent_minor > 0) ? (
        <>
          <SpendingChart data={spending.data} />
          <TopAisles data={spending.data} />
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Add your shopping receipts and you&apos;ll see what you spend each week next to what
          the plan expected.{" "}
          <Link href="/pantry/receipts" className="text-foreground underline underline-offset-4">
            Add a receipt
          </Link>
        </p>
      )}
    </section>
  );
}
