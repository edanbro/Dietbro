"""Data pipeline CLI: `uv run larder-data --help`.

Steps run in order by `pipeline`: import-usda -> embed-foods -> import-mealdb -> resolve -> report.
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from larder_data import mealdb, usda
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


STEPS: dict[str, Step] = {
    "import-usda": import_usda,
    "import-mealdb": import_mealdb,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="larder-data", description=__doc__)
    parser.add_argument("step", choices=[*STEPS, "pipeline"])
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="download cache dir")
    parser.add_argument("--refresh", action="store_true", help="re-fetch TheMealDB responses")
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
