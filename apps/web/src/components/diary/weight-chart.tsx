import type { Weight } from "@/lib/api/hooks";
import { daysBetween, shortDate } from "@/lib/dates";
import { bodyUnit, bodyWeight, type Units } from "@/lib/units";

const W = 320;
const H = 140;
const PAD = { top: 12, right: 12, bottom: 22, left: 36 };

/**
 * Weigh-ins over time as a hand-drawn SVG line (no chart library): x by date, y scaled to the
 * range with a little headroom. Shows a short text summary for screen readers.
 */
export function WeightChart({ weights, units = "metric" }: { weights: Weight[]; units?: Units }) {
  if (weights.length < 2) {
    return (
      <p className="text-sm text-muted-foreground">
        Add a couple of weigh-ins to see your trend.
      </p>
    );
  }
  const first = weights[0]!;
  const last = weights.at(-1)!;
  const span = Math.max(1, daysBetween(first.measured_on, last.measured_on));
  const unit = bodyUnit(units);
  const shown = (w: Weight) => bodyWeight(w.weight_kg, units);
  const values = weights.map(shown);
  const lo = Math.floor(Math.min(...values) - 0.5);
  const hi = Math.ceil(Math.max(...values) + 0.5);
  const x = (iso: string) =>
    PAD.left + (daysBetween(first.measured_on, iso) / span) * (W - PAD.left - PAD.right);
  const y = (v: number) => PAD.top + ((hi - v) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const points = weights.map((w) => `${x(w.measured_on).toFixed(1)},${y(shown(w)).toFixed(1)}`);
  const change = Math.round((shown(last) - shown(first)) * 10) / 10;
  const moved =
    change === 0 ? "No change" : `${change > 0 ? "Up" : "Down"} ${Math.abs(change)} ${unit}`;
  const summary = `${moved} since ${shortDate(first.measured_on)}`;

  return (
    <figure className="flex flex-col gap-1">
      {/* Drawn for a phone; capped so its labels don't grow huge on a wide screen. */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full max-w-lg text-primary"
        role="img"
        aria-label={`Weight from ${shown(first)} ${unit} to ${shown(last)} ${unit}. ${summary}.`}
      >
        {[hi, (hi + lo) / 2, lo].map((v) => (
          <g key={v} className="text-muted-foreground">
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              stroke="currentColor"
              strokeOpacity={0.2}
            />
            <text x={PAD.left - 6} y={y(v) + 4} textAnchor="end" fontSize={10} fill="currentColor">
              {v}
            </text>
          </g>
        ))}
        <text
          x={PAD.left}
          y={H - 6}
          fontSize={10}
          className="fill-muted-foreground"
        >
          {shortDate(first.measured_on)}
        </text>
        <text
          x={W - PAD.right}
          y={H - 6}
          fontSize={10}
          textAnchor="end"
          className="fill-muted-foreground"
        >
          {shortDate(last.measured_on)}
        </text>
        <polyline
          points={points.join(" ")}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {weights.map((w) => (
          <circle
            key={w.measured_on}
            cx={x(w.measured_on)}
            cy={y(shown(w))}
            r={2.5}
            fill="currentColor"
          />
        ))}
      </svg>
      <figcaption className="text-xs text-muted-foreground">{summary}</figcaption>
    </figure>
  );
}
