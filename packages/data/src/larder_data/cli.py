"""Data pipeline CLI: `uv run larder-data --help`.

`pipeline` runs every step in order: import-usda -> import-fndds -> import-cofid ->
embed-foods -> link-generics (CoFID) -> import-mealdb -> import-curated -> resolve ->
embed-recipes -> report. `evaluate` scores the automatic matcher against the curated aliases.

Open Food Facts products (about 1.3 GB to download) are a separate step:
`import-off --countries ie,gb`, then `link-generics --sources off`.
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from larder_data import (
    cofid,
    curated,
    embeddings,
    evaluate,
    fndds,
    generics,
    local_foods,
    mealdb,
    off,
    report,
    resolve,
    usda,
)
from larder_db.engine import make_engine, make_sessionmaker
from larder_db.models import Food

DEFAULT_CACHE = Path("data/cache")

logger = logging.getLogger("larder_data")

type Step = Callable[[AsyncSession, argparse.Namespace], Awaitable[None]]


async def import_usda(session: AsyncSession, args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        for dataset in ("foundation", "sr_legacy"):
            path = await usda.download(dataset, args.cache / "usda", client)
            records = usda.read_dataset(path, dataset)
            await usda.load_foods(session, records)
            logger.info("%s: %d foods", dataset, len(records))


async def import_fndds(session: AsyncSession, args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        sr = await usda.download("sr_legacy", args.cache / "usda", client)
        path = await usda.download(fndds.DATASET, args.cache / "usda", client)
    have = set((await session.scalars(select(Food.id))).all())
    records = fndds.read_survey(path, fndds.read_sr_ndb(sr))
    for r in records:
        if r.generic_food_id not in have:
            r.generic_food_id = r.generic_method = None
    await usda.load_foods(session, records)
    linked = sum(r.generic_food_id is not None for r in records)
    logger.info("survey foods: %d foods, %d linked to a generic", len(records), linked)


async def import_cofid(session: AsyncSession, args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        path = await cofid.download(args.cache / "cofid", client)
    records = cofid.read_cofid(path)
    await local_foods.load_local_foods(session, records)
    logger.info("cofid: %d foods", len(records))


async def import_off(session: AsyncSession, args: argparse.Namespace) -> None:
    path = args.off_file
    if path is None:
        async with httpx.AsyncClient(timeout=120) as client:
            path = await off.download(args.cache / "off", client, refresh=args.refresh)
    count = await off.import_products(
        session, off.iter_products(path, args.countries), args.countries
    )
    logger.info("open food facts: %d products", count)


async def link_generics(session: AsyncSession, args: argparse.Namespace) -> None:
    sources = args.sources if args.step != "pipeline" else ["cofid"]
    stats = await generics.link_generics(
        session, embedder(args), sources, limit=args.limit, retry=args.retry
    )
    logger.info("linked %d of %d foods (%s)", stats.linked, stats.considered, ", ".join(sources))


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
    "import-fndds": import_fndds,
    "import-cofid": import_cofid,
    "embed-foods": embed_foods,
    "link-generics": link_generics,
    "import-mealdb": import_mealdb,
    "import-curated": import_curated,
    "resolve": resolve_lines,
    "embed-recipes": embed_recipes,
    "report": write_report,
}
# Not part of `pipeline` (a large download): run on its own.
EXTRA_STEPS: dict[str, Step] = {"import-off": import_off}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="larder-data", description=__doc__)
    parser.add_argument("step", choices=[*STEPS, *EXTRA_STEPS, "pipeline"])
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
    parser.add_argument(
        "--countries",
        type=_codes,
        default=list(off.DEFAULT_COUNTRIES),
        help="import-off: ISO codes of the countries whose products to keep (default: ie,gb)",
    )
    parser.add_argument("--off-file", type=Path, help="import-off: a local copy of the export")
    parser.add_argument(
        "--sources",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        default=["cofid", "off"],
        help="link-generics: which sources to link (default: cofid,off)",
    )
    parser.add_argument("--limit", type=int, help="link-generics: at most this many foods")
    parser.add_argument(
        "--retry", action="store_true", help="link-generics: retry foods that found no match"
    )
    return parser.parse_args(argv)


def _codes(value: str) -> list[str]:
    return [c.strip().upper() for c in value.split(",") if c.strip()]


async def run(args: argparse.Namespace) -> None:
    engine = make_engine()
    try:
        async with make_sessionmaker(engine)() as session:
            steps = list(STEPS) if args.step == "pipeline" else [args.step]
            for name in steps:
                logger.info("== %s", name)
                await (STEPS | EXTRA_STEPS)[name](session, args)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
