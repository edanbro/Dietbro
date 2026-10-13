import pytest

from larder_core.allergens import Allergen
from larder_core.off import allergens_from_tags, country_tags, normalise_barcode, parse_product
from larder_core.synonyms import rewrite, search_terms
from larder_core.tagging import FoodFacts, FoodTags, tag_any

CSV_ROW = {
    "code": "4006381333931",
    "product_name": "Irish Butter",
    "brands": "Kerrygold,Ornua",
    "countries_tags": "en:ireland,en:united-kingdom,en:germany,en:japan",
    "categories_tags": "en:dairies,en:fats,en:butters",
    "allergens": "en:milk",
    "traces_tags": "",
    "ingredients_text": "Butter (milk), salt",
    "energy-kj_100g": "3061",
    "proteins_100g": "0.5",
    "fat_100g": "82",
    "carbohydrates_100g": "0.5",
    "saturated-fat_100g": "54",
    "salt_100g": "1.5",
    "product_quantity": "227",
    "serving_quantity": "",
}


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("4006381333932", None),  # bad check digit
        ("4006381333931", "4006381333931"),
        ("5000159407236", "5000159407236"),
        ("036000291452", "0036000291452"),  # UPC-A -> EAN-13
        ("00036000291452", "0036000291452"),  # GTIN-14 with a leading 0
        ("96385074", "96385074"),  # EAN-8
        ("abc", None),
    ],
)
def test_normalise_barcode(code: str, expected: str | None) -> None:
    assert normalise_barcode(code) == expected


def test_csv_row_parses_with_fallbacks() -> None:
    p = parse_product(CSV_ROW, countries=["IE", "GB"])

    assert p is not None
    assert (p.name, p.brand) == ("Irish Butter", "Kerrygold")
    assert p.countries == ("GB", "IE")
    assert p.kcal == pytest.approx(3061 / 4.184, abs=0.1)  # from kJ
    assert p.sodium_mg == pytest.approx(600)  # 1.5 g salt
    assert p.allergens == {Allergen.MILK}
    assert p.portions == (("packet", 227.0),)


def test_api_json_gives_the_same_record() -> None:
    api = {
        "code": CSV_ROW["code"],
        "product_name": "Irish Butter",
        "brands": "Kerrygold",
        "countries_tags": ["en:ireland", "en:united-kingdom"],
        "categories_tags": ["en:dairies", "en:fats", "en:butters"],
        "allergens_tags": ["en:milk"],
        "traces_tags": [],
        "ingredients_text": "Butter (milk), salt",
        "product_quantity": 227,
        "nutriments": {
            "energy-kj_100g": 3061,
            "proteins_100g": 0.5,
            "fat_100g": 82,
            "carbohydrates_100g": 0.5,
            "saturated-fat_100g": 54,
            "salt_100g": 1.5,
        },
    }
    assert parse_product(api) == parse_product(CSV_ROW, countries=["IE", "GB"])


@pytest.mark.parametrize(
    "change",
    [
        {"product_name": ""},
        {"energy-kj_100g": ""},
        {"energy-kj_100g": "99999"},  # 23,900 kcal/100 g
    ],
)
def test_implausible_products_are_dropped(change: dict[str, str]) -> None:
    assert parse_product(CSV_ROW | change) is None


def test_impossible_macros_are_dropped_not_the_product() -> None:
    p = parse_product(CSV_ROW | {"fat_100g": "820"})
    assert p is not None
    assert p.fat_g is None


def test_allergen_tags() -> None:
    assert allergens_from_tags(["en:sulphur-dioxide-and-sulphites", "en:oats"]) == {
        Allergen.SULPHITES,
        Allergen.GLUTEN,
    }
    assert allergens_from_tags(["en:shellfish"]) == {Allergen.CRUSTACEANS, Allergen.MOLLUSCS}
    # Unknown tag: read as words.
    assert Allergen.TREE_NUTS in allergens_from_tags(["en:cashew-butter"])


def test_country_tags() -> None:
    assert country_tags(["ie", "GB"]) == {"en:ireland", "en:united-kingdom"}


def test_branded_food_is_tagged_at_least_like_its_generic() -> None:
    generic = FoodTags(frozenset({Allergen.MILK}))
    facts = FoodFacts(
        id=1_000_000_001,
        description="Chocolate digestives",
        category="Baked Products",
        source="off",
        ingredients="wheat flour, chocolate (milk), may contain nuts",
        traces=frozenset({Allergen.TREE_NUTS}),
    )
    tags = tag_any(facts, generic)

    assert {Allergen.GLUTEN, Allergen.MILK, Allergen.TREE_NUTS} <= tags.allergens


def test_unknown_category_still_gets_keyword_tags() -> None:
    facts = FoodFacts(id=1_000_000_002, description="Peanut butter", category=None, source="cofid")
    assert Allergen.PEANUTS in tag_any(facts).allergens


def test_usda_foods_keep_their_tags() -> None:
    from larder_core.tagging import tag_food

    facts = FoodFacts(id=173410, description="Butter, salted", category="Dairy and Egg Products")
    assert tag_any(facts) == tag_food(173410, "Butter, salted", "Dairy and Egg Products")


def test_search_synonyms_dont_change_the_resolver() -> None:
    assert rewrite("baby aubergine") == "baby eggplant"
    assert rewrite("crisps") == "crisps"  # search-only synonym
    assert search_terms("Tayto Crisps") == "tayto potato chips"
    assert search_terms("crispbread") == "crispbread"
