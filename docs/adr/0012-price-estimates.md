# ADR-0012: Estimated prices from a curated GBP/kg table

- Status: Accepted
- Date: 2026-10-09

## Context

The planner minimises shopping cost and respects a weekly budget (PLAN §6), but USDA data has no
prices. The options were:

- live supermarket prices (scraping or a paid API: brittle, licensing, a new paid service);
- user-entered prices (too much friction);
- a curated estimate table;
- ignoring cost (no budget support).

## Decision

A curated table, `larder_core/data/prices.csv`. Each row is a USDA-category default, a keyword
rule or a per-food override, in GBP pence per kg (approximate 2025-26 UK supermarket averages).
Lookup order: food override, then keyword, then category, then a global default. `shop=false`
marks things nobody buys (tap water). EUR/USD use fixed, documented conversion factors.

Cost is pro rata: 37 g of flour costs 37 g's worth. Pack sizes are ignored, so the figure is a
lower-bound estimate. Store-cupboard staples (salt, spices, …) are not costed and appear on the
shopping list as "check you have".

## Consequences

- Budgets and cost comparisons are approximate. The UI labels costs "≈" and calls them
  estimates.
- Plans can't price in pack waste. That is a later improvement (pack sizes per food). Live
  prices would need a new paid service, which needs Eduard's sign-off.
- Prices are code-reviewed data: changing them changes plans, and tests bound them.

## Addendum (2026-10-13): regions

Users now have a region (`users.country`, see `larder_core.regions`). The UK table stays the
single source; other regions apply a food price-level factor per USDA category from
`data/price_regions.csv` (Ireland: CSO "Price Levels of Food, Beverages and Tobacco 2024",
relative to the EU27 average, with the UK taken as roughly that average since it left Eurostat's
comparison), then the fixed GBP rate. Planner objective weights are converted to the user's
currency so a repeat or a snack is worth about the same everywhere (`planning.weights_for`).
