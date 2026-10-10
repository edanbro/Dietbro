# ADR-0011: Allergen and diet tags from conservative rules, reviewed data and recipe text

- Status: Accepted
- Date: 2026-10-09

## Context

Allergies and diets are hard constraints (PLAN §6, §8). The planner needs to know which of the
EU/UK 14 allergens and which animal products each recipe contains. USDA FoodData Central has no
allergen data. TheMealDB ingredient lists are often incomplete: "Egg Drop Soup" has no egg line
(the egg is in the instructions), and a "Pork" recipe can list only spices. Our ingredient
matcher sometimes picks a nutritional stand-in ("thai red curry paste" → curry powder, which
loses the shrimp paste).

Options:

1. Store tags per food as a DB column, filled once.
2. Derive tags at runtime from pure rules plus reviewed data files.
3. Ask an LLM per recipe.

## Decision

Option 2, in `larder_core.tagging`. It is conservative: a false positive hides a recipe, a false
negative can hurt someone.

- `tag_food`: USDA category rules plus whole-word keyword rules (normalised text, inflections,
  a few compound suffixes; never raw substrings, so "coat" isn't "oats"). Explicit exceptions
  (coconut milk isn't dairy, nutmeg isn't a nut, buckwheat is gluten-free) remove only the tag
  they name. `food_tags.csv` adds per-food tags; removals need a note.
- `tag_text`: the same matcher over free text, with a normative table of compound foods (curry
  paste → crustaceans + fish; stock cube → gluten + celery; pastry → gluten + milk + eggs;
  sausage → gluten + sulphites; worcestershire → fish + gluten; …).
- `recipe_tags` is the single definition, used by the planner and the recipe page. It is the
  union of the matched foods' tags, the text of every ingredient line, the recipe name, the
  instructions, and category backstops (a "Seafood" recipe is fish + shellfish).
- Allergens and animal tags are coupled (`FoodTags.normalised`: milk ↔ dairy, eggs ↔ egg,
  fish ↔ fish, crustaceans/molluscs ↔ shellfish), so a diet rule can't miss an allergen rule
  or the reverse. Traditional rennet cheeses (parmesan, pecorino, …) are not vegetarian.
- A line matched approximately or automatically counts as *unresolved* until its name is
  reviewed in `line_tags.csv`, which records what the real ingredient adds. A recipe with
  unresolved lines is only planned for users with no allergies, diet or avoided foods. Every
  approximate or automatic match used by a plannable recipe has been reviewed.
- A snapshot of the tags of every food used by a plannable recipe is committed and diffed in
  tests, so a rule change can't silently change real data.

## Consequences

- Some safe recipes are hidden (for example, "walnut-sized" in instructions). Coverage tests
  make sure every common allergy and diet combination still has enough breakfasts and mains.
- New recipe sources (M4 generated recipes) get the same rules. Their unmatched or approximate
  lines are unresolved until reviewed, which is the safe default.
- The rennet list and "may contain" cases are brand-dependent. The recipe page says tags are
  derived from ingredients and may be incomplete, and shows "not medical advice".
