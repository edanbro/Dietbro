"""`uv run larder-evals --help`.

Free by default: the hybrid planner on synthetic scenarios (`--catalog synthetic`, no database)
or on the seeded real catalogue (`--catalog db`). The LLM-only baseline (`--llm`) calls Claude
and costs money: it prints an estimate first, runs only with `--yes`, and stops once
`--max-usd` (default $5) is spent. It needs ANTHROPIC_API_KEY in the environment.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from larder_evals.baseline import LLMPlanner, problem_json
from larder_evals.report import render
from larder_evals.run import (
    KINDS,
    Result,
    Scored,
    catalog_scenarios,
    hybrid,
    score,
    synthetic_scenarios,
)
from larder_llm.client import SONNET
from larder_llm.pricing import price_of

# What one baseline call is assumed to produce (answer + thinking), for the estimate.
_OUTPUT_TOKENS = 2_500


def estimate_usd(items: list[Scored], model: str) -> float:
    price = price_of(model)
    total = 0.0
    for item in items:
        tokens_in = len(problem_json(item.scenario.problem)) / 3.5  # JSON: ~3.5 chars/token
        total += float(price.input) * tokens_in + float(price.output) * _OUTPUT_TOKENS
    return total / 1e6


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="larder-evals", description=__doc__)
    parser.add_argument("--catalog", choices=["synthetic", "db"], default="synthetic")
    parser.add_argument("--n", type=int, default=50, help="scenarios per kind")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--kinds", default=None, help=f"default: {','.join(KINDS)} (+profiles on db)"
    )
    parser.add_argument("--planner", choices=["auto", "cpsat", "greedy"], default="auto")
    parser.add_argument("--llm", action="store_true", help="also run the LLM-only baseline (paid)")
    parser.add_argument("--llm-n", type=int, default=None, help="baseline scenarios per kind")
    parser.add_argument("--model", default=SONNET)
    parser.add_argument("--max-usd", type=float, default=5.0)
    parser.add_argument("--yes", action="store_true", help="confirm the paid baseline run")
    parser.add_argument("--database-url")
    parser.add_argument("--out", type=Path, default=Path("evals"), help="REPORT.md goes here")
    args = parser.parse_args(argv)

    if args.catalog == "db":
        from larder_api.bench import load

        full = asyncio.run(load(args.database_url))
        kinds = args.kinds.split(",") if args.kinds else [*KINDS, "profiles"]
        items = list(catalog_scenarios(full, args.n, args.seed, kinds))
        source = f"the seeded catalogue ({len(full.catalog.recipes)} plannable recipes)"
    else:
        kinds = args.kinds.split(",") if args.kinds else list(KINDS)
        items = list(synthetic_scenarios(args.n, args.seed, kinds))
        source = "the synthetic catalogue (300 recipes per seed)"

    planner = hybrid(args.planner)
    results: list[Result] = []
    for i, item in enumerate(items, 1):
        results.append(score(item, "hybrid", planner))
        if i % 25 == 0:
            print(f"hybrid: {i}/{len(items)}", file=sys.stderr)

    notes = [
        f"Hybrid planner mode `{args.planner}` (auto = CP-SAT, with the greedy baseline when "
        "it finds no plan in time)."
    ]
    if args.llm:
        llm_n = args.llm_n or args.n
        subset = [it for it in items if it.seed < args.seed + llm_n]
        cost = estimate_usd(subset, args.model)
        print(
            f"LLM baseline: {len(subset)} plans with {args.model}, about ${cost:.2f} "
            f"(stops at ${args.max_usd:.2f}).",
            file=sys.stderr,
        )
        if not args.yes:
            print("Not run: add --yes to confirm the paid run.", file=sys.stderr)
            notes.append("LLM-only baseline not run (it needs approval to spend on the API).")
        elif not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set.")
        else:
            import anthropic

            from larder_llm.client import AnthropicStructuredModel

            baseline = LLMPlanner(
                AnthropicStructuredModel(anthropic.AsyncAnthropic(), args.model, effort="medium")
            )
            done = 0
            for item in subset:
                if baseline.cost_micro_usd >= args.max_usd * 1e6:
                    print("Cost cap reached; stopping.", file=sys.stderr)
                    break
                results.append(score(item, "llm", lambda pr, _prev: baseline.plan(pr)))
                done += 1
            spent = baseline.cost_micro_usd / 1e6
            notes.append(
                f"LLM-only baseline: {args.model} on {done} scenarios "
                f"(the first {llm_n} seeds per kind), ${spent:.2f} spent."
            )
    else:
        notes.append("LLM-only baseline not run (`--llm --yes`, paid).")

    args.out.mkdir(parents=True, exist_ok=True)
    report = render(results, args.out, source=source, notes=notes)
    (args.out / "REPORT.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main(sys.argv[1:])
