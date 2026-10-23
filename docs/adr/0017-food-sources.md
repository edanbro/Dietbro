# ADR 0017: More food sources (survey foods, CoFID, Open Food Facts)

Status: accepted (2026-10-13)

## Context

The catalogue was USDA Foundation + SR Legacy only: about 8,300 US-worded generic foods. Pantry
search felt thin, Irish and British grocery words ("rashers", "crisps") mostly missed, and
there were no brands or barcodes.

## Decision

- One `foods` table for every source. USDA rows keep `id` = FDC id; CoFID and Open Food Facts
  rows get ids from `foods_local_id_seq` (1e9 and up). `source` / `source_id` identify a row.
- Sources: USDA survey foods (FNDDS 2024, ~5,400 foods as eaten, with household portions);
  UK CoFID 2021 (~2,900 foods as sold and eaten in the UK and Ireland; OGL v3); Open Food Facts
  products sold in Ireland and the UK (~210,000, ODbL; nightly export, streamed, no images).
- `category` is always a USDA category name: WWEIA codes, CoFID groups and OFF tags are mapped
  through reviewed tables in `larder_core/data` (unknown WWEIA/CoFID codes stop the import), so
  allergen tags, prices, shelf life and aisles keep working.
- `generic_food_id` links a regional or branded food to the generic USDA food it counts as.
  Recipes only ever resolve to generic foods (the resolver and the receipt/chat matcher keep
  their candidate sets and measured accuracy). The planner, "mark eaten", chat and avoid/like
  lists key pantry items and picks on the generic, so a Kerrygold pack counts toward a recipe's
  butter. Links come from FNDDS ingredients, the reviewed vocabularies, then the matcher, behind
  plausibility rules (`larder_core.generic_links`); products are linked on demand when added to
  a pantry (batch linking of 200k products is too slow).
- Tags for non-USDA foods are the union of category rules, keyword rules on the name, source
  category and ingredient list, declared allergens and traces, and the generic's tags. Nothing
  is removed on a label's say-so. The UI says product data is crowdsourced: check the label.
- Search: curated names, then full-text (with brand) or trigram; every-word matches first,
  generics before products, names starting with the query, regional foods (CoFID for IE/GB);
  products only for 3+ characters and only when sold in the user's country. Paged.

## Consequences

- The database grows by ~230,000 rows (a few hundred MB with indexes). `import-off` is a
  separate step (a 1.3 GB download), not part of `pipeline`.
- ODbL: the Open Food Facts subset is a derivative database; attribution is on /attributions.
  Publishing the app means offering that subset under the ODbL on request.
- Barcode lookup for products not yet imported comes next (Open Food Facts API, rate limited).
