"""Data pipeline CLI: `uv run larder-data --help`.

`pipeline` runs every step in order: import-usda -> embed-foods -> import-mealdb ->
import-curated -> resolve -> embed-recipes -> report. `evaluate` scores the automatic matcher
against the curated aliases.
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from larder_data import curated, embeddings, evaluate, mealdb, report, resolve, usda
from larder_db.engine import make_engine, make_sessionmaker

DEFAULT_CACHE = Path("data/cache")

logger = logging.getLogger("larder_data")

type Step = Callable[[AsyncSession, argparse.Namespace], Awaitable[None]]


async def import_usda(session: AsyncSession, args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        for dataset in usda.DATASETS:
            path = await usda.download(dataset, args.cache / "usda", client)
            records = usda.read_dataset(path, dataset)
            await usda.load_foods(session, records)
            logger.info("%s: %d foods", dataset, len(records))


async def import_mealdb(session: AsyncSession, args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        meals = await mealdb.fetch_meals(client, args.cache / "mealdb", refresh=args.refresh)
    count = await mealdb.load_recipes(session, [mealdb.parse_meal(m) for m in meals])
    logger.info("mealdb: %d recipes", count)


async def import_curated(session: AsyncSession, args: argparse.Namespace) -> None:
    count = await mealdb.load_recipes(session, curated.load(), source=curated.SOURCE)
    logger.info("curated: %d recipes", count)


def embedder(args: argparse.Namespace) -> embeddings.FastEmbedder:
    return embeddings.FastEmbedder(args.cache / "models")


async def embed_foods(session: AsyncSession, args: argparse.Namespace) -> None:
    logger.info("embedded %d foods", await embeddings.embed_foods(session, embedder(args)))


async def resolve_lines(session: AsyncSession, args: argparse.Namespace) -> None:
    model = None if args.aliases_only else embedder(args)
    stats = await resolve.resolve_all(session, model, use_cache=not args.rematch)
    logger.info("%s", stats)


async def embed_recipes(session: AsyncSession, args: argparse.Namespace) -> None:
    logger.info("embedded %d recipes", await embeddings.embed_recipes(session, embedder(args)))


async def write_report(session: AsyncSession, args: argparse.Namespace) -> None:
    r = await report.build_report(session)
    text = report.render(r)
    if args.evaluate:
        text += "\n" + evaluate.render(await evaluate.evaluate(session, embedder(args)))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    print(text)
    if r.food_coverage < args.min_coverage:
        raise SystemExit(
            f"food coverage {100 * r.food_coverage:.1f}% < required {100 * args.min_coverage:.1f}%"
        )


STEPS: dict[str, Step] = {
    "import-usda": import_usda,
    "embed-foods": embed_foods,
    "import-mealdb": import_mealdb,
    "import-curated": import_curated,
    "resolve": resolve_lines,
    "embed-recipes": embed_recipes,
    "report": write_report,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="larder-data", description=__doc__)
    parser.add_argument("step", choices=[*STEPS, "pipeline"])
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="download cache dir")
    parser.add_argument("--refresh", action="store_true", help="re-fetch TheMealDB responses")
    parser.add_argument("--rematch", action="store_true", help="ignore cached name matches")
    parser.add_argument(
        "--aliases-only",
        action="store_true",
        help="resolve: curated aliases and cached matches only (no embedding model; fast seed)",
    )
    parser.add_argument("--out", type=Path, help="report: also write Markdown here")
    parser.add_argument(
        "--evaluate", action="store_true", help="report: add matcher accuracy vs curated aliases"
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        help="report: exit non-zero if the share of lines resolved to a food is below this",
    )
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> None:
    engine = make_engine()
    try:
        async with make_sessionmaker(engine)() as session:
            steps = list(STEPS) if args.step == "pipeline" else [args.step]
            for name in steps:
                logger.info("== %s", name)
                await STEPS[name](session, args)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
