# Ingredient resolution report

| Metric | Value |
|---|---|
| Ingredient lines | 8152 |
| Lines resolved to a USDA food | 8122 (99.6%) |
| Lines with a gram weight | 8023 (98.4%) |
| Recipes | 790 |
| Recipes with complete nutrition | 667 (84.4%) |

Lines by match method: alias 7713, embedding 409, unmatched 30

## Most frequent unmatched names

- chimichurri sauce (3)
- grand marnier (2)
- achiote seed (1)
- corn arepa filled with mozarella cheese (1)
- bouquet garni (1)
- juniper berry (1)
- alinos sauce (1)
- cafe la llave (1)
- rice krispy (1)
- sumac (1)
- salsa lizano (1)
- gochujang (1)
- knafeh (1)
- ground mahleb (1)
- doubanjiang (1)
- pickled scallion head (1)
- pickled scallion head brine (1)
- pandan leaf (1)
- ground oat (1)
- sevaiiya (1)
- achiote paste (1)
- prahok (1)
- petit poi (1)
- toffee popcorn (1)
- ackee (1)

## Most frequent matched lines without grams

- yeast: `2 parts` (2)
- beef stock: `1` (2)
- challot: `5` (2)
- chicken stock: `1` (2)
- lemon zest: `1` (2)
- celeriac: `1` (2)
- russet potato: `1 large` (2)
- pork: `2` (2)
- ginger: `large piece` (2)
- meringue nest: `1` (1)
- turkish delight: `2 pieces` (1)
- pico de gallo sauce: `1` (1)
- walnut: `4` (1)
- squid: `3 medium` (1)
- challot: `16` (1)
- cayenne pepper: `8` (1)
- cumin: `1 1/2` (1)
- pigs trotter: `2` (1)
- oyster: `8` (1)
- beef stock concentrate: `1` (1)
- broccoli: `12 florets` (1)
- red potato: `2 large` (1)
- iceberg lettuce: `1/4` (1)
- allspice berry: `4` (1)
- salsa: `1 x 300ml` (1)

## Matcher accuracy without the alias table

Scored on 463 hand-curated names (approximations excluded). Top-1: 54.0% the curated food, 73.7% the curated food or a nutritional equivalent (same USDA category, energy within 25%).

| Threshold | Accepted | Exact precision | Equivalent precision | Coverage |
|---|---|---|---|---|
| 0.80 | 416 | 59.1% | 80.0% | 89.8% |
| 0.84 | 390 | 61.3% | 82.1% | 84.2% |
| 0.86 | 358 | 63.1% | 83.2% | 77.3% |
| 0.88 | 320 | 66.9% | 87.2% | 69.1% |
| 0.90 | 306 | 67.0% | 87.3% | 66.1% |
| 0.92 | 293 | 67.6% | 88.1% | 63.3% |
| 0.95 | 272 | 68.0% | 87.5% | 58.7% |
| 1.00 | 231 | 67.5% | 87.4% | 49.9% |
