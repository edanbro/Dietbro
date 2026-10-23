"""evals/REPORT.md and its charts: plain Markdown tables and hand-drawn SVG bar charts (no
plotting library), light and dark friendly (they use currentColor for text and axes)."""

import statistics
from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path

from larder_evals.run import Result, p

__all__ = ["bar_chart", "render", "summary"]

COLOURS = {"hybrid": "#1d6b40", "llm": "#d9822b"}
LABELS = {"hybrid": "Hybrid (solver plans)", "llm": "LLM only"}


def _pct(k: int, n: int) -> float:
    return 100 * k / n if n else 0.0


def summary(results: Sequence[Result]) -> dict[str, float]:
    """Headline numbers for a set of runs (one planner)."""
    n = len(results)
    found = [r for r in results if r.found]
    pantry = [r.pantry_used_pct for r in found if r.pantry_used_pct is not None]
    churn = [r.churn for r in found if r.churn is not None]
    ms = [r.ms for r in results]
    return {
        "n": n,
        "valid_pct": _pct(sum(r.valid for r in results), n),
        "unsafe_pct": _pct(sum(r.safety_violations > 0 for r in found), n),
        "safety_per_100": 100 * sum(r.safety_violations for r in found) / n if n else 0.0,
        "made_up_pct": _pct(sum(r.unknown_recipes for r in found), sum(r.meals for r in found)),
        "no_plan_pct": _pct(n - len(found), n),
        "pantry_used_pct": statistics.fmean(pantry) if pantry else float("nan"),
        "waste_g": statistics.fmean(r.waste_g for r in found) if found else float("nan"),
        "churn": statistics.fmean(churn) if churn else float("nan"),
        "p50_ms": p(ms, 0.5),
        "p95_ms": p(ms, 0.95),
        "usd_per_plan": (sum(r.cost_micro_usd for r in results) / n / 1e6) if n else 0.0,
    }


def bar_chart(
    title: str, groups: Sequence[str], series: Mapping[str, Sequence[float]], unit: str = "%"
) -> str:
    """A grouped bar chart as an SVG string: one group per kind, one bar per planner."""
    width, height, left, bottom, top = 640, 260, 48, 40, 36
    plot_w, plot_h = width - left - 16, height - top - bottom
    peak = max([v for vs in series.values() for v in vs if v == v] + [1.0])
    scale = 100.0 if unit == "%" and peak <= 100 else peak * 1.15
    group_w = plot_w / max(len(groups), 1)
    bar_w = min(36.0, group_w * 0.7 / max(len(series), 1))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}" font-family="system-ui,sans-serif" '
        'font-size="12" fill="currentColor">',
        f'<text x="{left}" y="20" font-size="14" font-weight="600">{escape(title)}</text>',
    ]
    for tick in (0, 0.5, 1):
        y = top + plot_h * (1 - tick)
        parts.append(
            f'<line x1="{left}" x2="{width - 16}" y1="{y:.1f}" y2="{y:.1f}" '
            'stroke="currentColor" stroke-opacity="0.15"/>'
        )
        parts.append(
            f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" opacity="0.7">'
            f"{scale * tick:.0f}{unit if unit == '%' else ''}</text>"
        )
    for g, group in enumerate(groups):
        x0 = left + g * group_w + (group_w - bar_w * len(series)) / 2
        for s, (name, values) in enumerate(series.items()):
            value = values[g]
            if value != value:  # nan: no data
                continue
            h = plot_h * min(value / scale, 1)
            x = x0 + s * bar_w
            parts.append(
                f'<rect x="{x:.1f}" y="{top + plot_h - h:.1f}" width="{bar_w - 4:.1f}" '
                f'height="{h:.1f}" rx="3" fill="{COLOURS.get(name, "#888")}"/>'
            )
            label = f"{value:.0f}" if value >= 10 else f"{value:.1f}"
            parts.append(
                f'<text x="{x + (bar_w - 4) / 2:.1f}" y="{top + plot_h - h - 4:.1f}" '
                f'text-anchor="middle" font-size="11">{label}</text>'
            )
        parts.append(
            f'<text x="{left + g * group_w + group_w / 2:.1f}" y="{height - bottom + 18}" '
            f'text-anchor="middle">{escape(group)}</text>'
        )
    lx = left
    for name in series:
        parts.append(
            f'<rect x="{lx}" y="{height - 14}" width="10" height="10" rx="2" '
            f'fill="{COLOURS.get(name, "#888")}"/>'
        )
        parts.append(
            f'<text x="{lx + 14}" y="{height - 5}">{escape(LABELS.get(name, name))}</text>'
        )
        lx += 190
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _fmt(value: float, suffix: str = "", digits: int = 0) -> str:
    return "n/a" if value != value else f"{value:,.{digits}f}{suffix}"


def render(results: Sequence[Result], out_dir: Path, *, source: str, notes: Sequence[str]) -> str:
    """Write the charts next to REPORT.md and return the report's Markdown."""
    planners = [name for name in ("hybrid", "llm") if any(r.planner == name for r in results)]
    kinds = sorted({r.kind for r in results})
    charts = out_dir / "charts"
    charts.mkdir(parents=True, exist_ok=True)

    def per_kind(metric: str) -> dict[str, list[float]]:
        return {
            pl: [
                summary([r for r in results if r.planner == pl and r.kind == k])[metric]
                for k in kinds
            ]
            for pl in planners
        }

    (charts / "valid.svg").write_text(
        bar_chart("Plans with no hard violation", kinds, per_kind("valid_pct")), encoding="utf-8"
    )
    (charts / "unsafe.svg").write_text(
        bar_chart(
            "Plans with a safety violation (allergen, diet...)", kinds, per_kind("unsafe_pct")
        ),
        encoding="utf-8",
    )
    (charts / "latency.svg").write_text(
        bar_chart("Latency p95 (ms)", kinds, per_kind("p95_ms"), unit=""), encoding="utf-8"
    )

    lines = [
        "# Evals: hybrid planner vs LLM-only",
        "",
        f"Generated by `larder-evals` on {source}. Every plan is scored by the same independent "
        "validator (`larder_solver.validate`) and metrics, never by the planner itself.",
        "",
        "## Headline",
        "",
        "| Planner | Plans | Valid (no hard violation) | With a safety violation | "
        "Made-up recipes | No plan | Pantry used | Waste (g) | Churn (replans) | p50 / p95 (ms) "
        "| $ / plan |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for pl in planners:
        s = summary([r for r in results if r.planner == pl])
        lines.append(
            f"| {LABELS[pl]} | {s['n']:.0f} | {_fmt(s['valid_pct'], '%')} | "
            f"{_fmt(s['unsafe_pct'], '%')} | {_fmt(s['made_up_pct'], '%', 1)} | "
            f"{_fmt(s['no_plan_pct'], '%')} | {_fmt(s['pantry_used_pct'], '%')} | "
            f"{_fmt(s['waste_g'])} | {_fmt(s['churn'], '', 1)} | "
            f"{_fmt(s['p50_ms'])} / {_fmt(s['p95_ms'])} | ${s['usd_per_plan']:.4f} |"
        )
    lines += [
        "",
        "![Plans with no hard violation](charts/valid.svg)",
        "",
        "![Plans with a safety violation](charts/unsafe.svg)",
        "",
        "![Latency p95](charts/latency.svg)",
        "",
        "## By scenario kind",
        "",
        "| Kind | Planner | Plans | Valid | Unsafe | Made-up recipes | Pantry used | Churn "
        "| p95 (ms) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for k in kinds:
        for pl in planners:
            s = summary([r for r in results if r.planner == pl and r.kind == k])
            lines.append(
                f"| {k} | {LABELS[pl]} | {s['n']:.0f} | {_fmt(s['valid_pct'], '%')} | "
                f"{_fmt(s['unsafe_pct'], '%')} | {_fmt(s['made_up_pct'], '%', 1)} | "
                f"{_fmt(s['pantry_used_pct'], '%')} | {_fmt(s['churn'], '', 1)} | "
                f"{_fmt(s['p95_ms'])} |"
            )
    lines += [
        "",
        "## What the columns mean",
        "",
        "- **Valid**: a plan came back with no hard violation: every required meal, safe "
        "recipes, portions and repeats within limits, each day's kcal in its band and over the "
        "floor, the weekly bands and the budget.",
        "- **With a safety violation**: an allergen, the diet, an avoided or unknown food, an "
        "unverified recipe for a restricted user, or a day under the calorie floor. The app "
        "never shows such a plan, whichever planner made it.",
        "- **Made-up recipes**: meals naming a recipe that wasn't offered.",
        "- **Pantry used**: share of the pantry's grams the plan eats. **Waste**: grams left in "
        "food that expires during the plan. **Churn**: meals changed against the plan before a "
        "mid-week change (replans), lower is calmer.",
        "",
        "## Scenario kinds",
        "",
        "- **planted**: synthetic users with a known valid plan; 1-3 tempting but unsafe "
        "*decoy* recipes per slot.",
        "- **realistic**: user-like problems: allergens, diets, avoided foods, budgets, pantry.",
        "- **replans**: mid-week changes (a meal eaten out, one skipped) on a planted week.",
        "- **profiles** (real catalogue only): the API's ten fixed profiles through its own "
        "`make_problem`.",
        "",
        *[f"> {n}" for n in notes],
        "",
    ]
    return "\n".join(lines)
