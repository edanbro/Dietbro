# ADR-0006: Seed recipes from TheMealDB; match ingredients with a curated table + hybrid retrieval

- Status: Accepted
- Date: 2026-10-08

## Context

Every recipe ingredient must resolve to a USDA food with a gram weight, or the planner can't
reason about nutrition and the safety story breaks. M1's target: ≥ 95% of seeded ingredient
lines resolve.

**Recipe source.** RecipeNLG is large but licensed for non-commercial use only. TheMealDB has
~800 meals with structured ingredient/measure pairs; its free API key is for development and
education, and production use needs a supporter key.

**Matching.** Options considered for name → food:

1. Embedding nearest neighbour only. Measured on our data: ~55% top-1 correct — "egg" → "Bread,
   egg", "cumin" → an emu cut, "milk" → human milk.
2. LLM for every name. Good accuracy, but costs money per import, isn't reproducible, and the
   plan reserves the LLM for ambiguous cases only.
3. Hand-curated table for frequent names + automatic matcher for the rest, with a confidence
   threshold and "unresolved" as a legitimate outcome.

## Decision

TheMealDB as the seed source (raw responses cached, so imports are repeatable), and option 3:

- `resources/aliases.csv`: 567 normalised names, each reviewed against the USDA description;
  nutritional stand-ins are marked `approximation`. Covers ~95% of lines.
- Automatic matcher for everything else: British → USDA synonym rewrite, pgvector + lexical
  candidates, a transparent rule-based rerank, accept at score ≥ 0.88.
- `larder-data report --evaluate` scores the matcher alone against the curated names (exact and
  "nutritionally equivalent"), so threshold and rerank changes are measured, not guessed.
- The M4 LLM tiebreak slots in where the matcher currently returns "unresolved".

## Consequences

- 99.6% of lines resolve (94.6% via the table); 84% of recipes have complete nutrition.
- The headline coverage depends on curation. That is honest only alongside the matcher's own
  numbers (87% equivalent precision at the threshold), which the report always prints.
- New recipes with unseen ingredients fall back to the matcher; low-confidence names stay
  unresolved and the recipe isn't plannable until resolved.
- Before a public deployment (M8): TheMealDB supporter key or a different licensed source.
