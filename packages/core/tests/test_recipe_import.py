import json

import pytest

from larder_core.recipe_import import find_recipe, split_line


def page(*blocks: object) -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks
    )
    return f"<html><head>{scripts}</head><body>Hello</body></html>"


RECIPE = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Irish stew &amp; dumplings",
    "recipeYield": ["4", "4 servings"],
    "recipeIngredient": ["800g lamb neck", "3 carrots, sliced", " "],
    "recipeInstructions": [
        {
            "@type": "HowToSection",
            "itemListElement": [{"@type": "HowToStep", "text": "Brown the <b>lamb</b>."}],
        },
        {"@type": "HowToStep", "text": "Simmer for 2 hours."},
    ],
    "recipeCategory": ["Main course"],
    "recipeCuisine": "Irish",
    "image": [{"@type": "ImageObject", "url": "https://example.com/stew.jpg"}],
}


def test_reads_a_recipe_from_its_json_ld() -> None:
    recipe = find_recipe(page({"@type": "WebSite", "name": "Food"}, RECIPE))
    assert recipe is not None
    assert recipe.name == "Irish stew & dumplings"
    assert recipe.servings == 4
    assert recipe.ingredients == ["800g lamb neck", "3 carrots, sliced"]
    assert recipe.instructions == "Brown the lamb.\n\nSimmer for 2 hours."
    assert (recipe.category, recipe.cuisine) == ("Main course", "Irish")
    assert recipe.image_url == "https://example.com/stew.jpg"


def test_finds_a_recipe_inside_a_graph_with_a_type_list() -> None:
    node = {**RECIPE, "@type": ["Recipe", "NewsArticle"], "recipeYield": "Serves 6"}
    recipe = find_recipe(
        page({"@context": "https://schema.org", "@graph": [{"@type": "Person"}, node]})
    )
    assert recipe is not None
    assert recipe.servings == 6


def test_no_recipe_on_the_page() -> None:
    assert find_recipe("<html>no data</html>") is None
    assert find_recipe('<script type="application/ld+json">{not json</script>') is None
    assert find_recipe(page({"@type": "Recipe", "name": "Empty"})) is None  # no ingredients


@pytest.mark.parametrize(
    ("line", "quantity", "name"),
    [
        ("2 tbsp olive oil, plus extra for drizzling", "2 tbsp", "olive oil"),
        ("400g tin chopped tomatoes", "400g tin", "chopped tomatoes"),
        ("2 x 400g cans chickpeas, drained", "2 x 400g cans", "chickpeas"),
        ("1 large onion, finely chopped", "1 large", "onion"),
        ("½ tsp ground cumin", "½ tsp", "ground cumin"),
        ("250ml (1 cup) whole milk", "250ml", "whole milk"),
        ("3 cloves of garlic", "3 cloves", "garlic"),
        ("a pinch of salt", "a", "pinch of salt"),
        ("salt and pepper", "", "salt and pepper"),
        ("1-2 red chillies", "1-2", "red chillies"),
        ("5 medium onions sliced", "5 medium", "onions"),
        ("900g stewing lamb cut into large chunks", "900g", "stewing lamb"),
        ("200g smoked bacon preferably in one piece, skinned", "200g", "smoked bacon"),
    ],
)
def test_splits_ingredient_lines(line: str, quantity: str, name: str) -> None:
    assert split_line(line) == (quantity, name)
