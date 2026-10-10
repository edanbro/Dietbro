"""Golden cases for allergen and diet tags (larder_core.tagging).

Expected tags are written as space-separated names: allergen names first ("fish" is the allergen,
which couples to the animal tag), then animal tags. They are compared after normalisation, so
"milk" stands for milk + dairy and "crustaceans" for crustaceans + shellfish.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_core.aliases import load_alias_rows
from larder_core.allergens import Allergen
from larder_core.tagging import (
    EXCEPTIONS,
    FORBIDDEN,
    RULES,
    AnimalTag,
    Diet,
    FoodTags,
    Line,
    diet_allows,
    format_tags,
    forms,
    line_tags,
    load_food_tags,
    load_line_tags,
    make_line,
    parse_tags,
    recipe_tags,
    tag_food,
    tag_text,
)

_ALLERGENS = frozenset(a.value for a in Allergen)


def tags(spec: str) -> FoodTags:
    """'gluten milk meat' -> normalised FoodTags."""
    a = frozenset(Allergen(w) for w in spec.split() if w in _ALLERGENS)
    t = frozenset(AnimalTag(w) for w in spec.split() if w not in _ALLERGENS)
    return FoodTags(a, t).normalised()


def covers(big: FoodTags, small: FoodTags) -> bool:
    return big.allergens >= small.allergens and big.animal >= small.animal


def show(t: FoodTags) -> str:
    return f"{format_tags(t.allergens)} / {format_tags(t.animal)}"


# --- tag_text: the normative keyword table (spec §3.3), one case per entry ---------------------

NORMATIVE = [
    ("Thai red curry paste", "crustaceans fish"),
    ("chilli jam", "crustaceans fish"),
    ("nam prik pao", "crustaceans fish"),
    ("shrimp paste", "crustaceans fish"),
    ("belacan", "crustaceans fish"),
    ("dried shrimp", "crustaceans fish"),
    ("frozen seafood mix", "fish crustaceans molluscs"),
    ("hoisin sauce", "soy gluten sesame"),
    ("teriyaki marinade", "soy gluten"),
    ("black bean sauce", "soy gluten"),
    ("white miso paste", "soy gluten"),
    ("oyster sauce", "molluscs soy gluten"),
    ("dark soy sauce", "soy gluten"),
    ("tamari", "soy"),
    ("chicken stock cube", "gluten celery meat"),
    ("vegetable bouillon powder", "gluten celery"),
    ("gravy granules", "gluten celery"),
    ("vegetable stock", "celery"),
    ("vegetable broth", "celery"),
    ("chicken stock", "celery meat"),
    ("beef broth", "celery meat"),
    ("lamb stock", "celery meat"),
    ("pork stock", "celery meat"),
    ("ham stock", "celery meat sulphites"),
    ("fish stock", "celery fish"),
    ("shortcrust pastry", "gluten milk eggs"),
    ("ready-rolled puff pastry", "gluten milk eggs"),
    ("filo pastry", "gluten milk eggs"),
    ("phyllo dough", "gluten milk eggs"),
    ("naan", "gluten milk eggs"),
    ("brioche buns", "gluten milk eggs"),
    ("croissants", "gluten milk eggs"),
    ("crusty bread", "gluten"),
    ("dried breadcrumbs", "gluten"),
    ("panko", "gluten"),
    ("rusk", "gluten"),
    ("croutons", "gluten"),
    ("sage and onion stuffing", "gluten"),
    ("tempura", "gluten"),
    ("beer batter", "gluten"),
    ("digestive biscuits", "gluten"),
    ("cream crackers", "gluten"),
    ("sponge cake", "gluten"),
    ("pitta bread", "gluten"),
    ("chapati", "gluten"),
    ("roti", "gluten"),
    ("flour tortillas", "gluten"),
    ("corn tortillas", ""),
    ("tortilla wraps", "gluten"),
    ("couscous", "gluten"),
    ("bulgur wheat", "gluten"),
    ("freekeh", "gluten"),
    ("spelt flour", "gluten"),
    ("semolina", "gluten"),
    ("durum wheat", "gluten"),
    ("farro", "gluten"),
    ("seitan", "gluten"),
    ("plain flour", "gluten"),
    ("self-raising flour", "gluten"),
    ("rice flour", ""),
    ("corn flour", ""),
    ("cornflour", ""),
    ("maize flour", ""),
    ("gram flour", ""),
    ("chickpea flour", ""),
    ("besan flour", ""),
    ("buckwheat flour", ""),
    ("potato flour", ""),
    ("tapioca flour", ""),
    ("cassava flour", ""),
    ("coconut flour", ""),
    ("almond flour", "tree_nuts"),
    ("quinoa flour", ""),
    ("pasta", "gluten"),
    ("spaghetti", "gluten"),
    ("penne", "gluten"),
    ("linguine", "gluten"),
    ("fusilli", "gluten"),
    ("lasagne sheets", "gluten"),
    ("macaroni", "gluten"),
    ("orzo", "gluten"),
    ("gnocchi", "gluten"),
    ("tagliatelle", "gluten eggs"),
    ("spinach ravioli", "gluten eggs milk"),
    ("tortellini", "gluten eggs milk"),
    ("vermicelli", "gluten"),
    ("rice vermicelli", ""),
    ("noodles", "gluten"),
    ("rice noodles", ""),
    ("glass noodles", ""),
    ("mung bean noodles", ""),
    ("kelp noodles", ""),
    ("udon noodles", "gluten"),
    ("ramen", "gluten"),
    ("egg noodles", "gluten eggs"),
    ("fresh pasta", "gluten eggs"),
    ("pork sausages", "meat gluten sulphites"),
    ("black pudding", "meat gluten sulphites"),
    ("haggis", "meat gluten sulphites"),
    ("beef burgers", "meat gluten sulphites"),
    ("chorizo", "meat sulphites"),
    ("salami", "meat sulphites"),
    ("smoked bacon", "meat sulphites"),
    ("ham", "meat sulphites"),
    ("prosciutto", "meat sulphites"),
    ("pancetta", "meat sulphites"),
    ("jamón serrano", "meat sulphites"),
    ("dark chocolate", "milk soy"),
    ("cocoa powder", ""),
    ("margarine", "milk"),
    ("custard", "eggs milk"),
    ("vanilla ice cream", "eggs milk"),
    ("meringue nests", "eggs"),
    ("hollandaise", "eggs milk"),
    ("béarnaise sauce", "eggs milk"),
    ("aioli", "eggs mustard"),
    ("mayonnaise", "eggs mustard"),
    ("marshmallows", "gelatin"),
    ("strawberry jelly", "gelatin"),
    ("gelatine leaves", "gelatin"),
    ("mincemeat", "gluten eggs tree_nuts sulphites meat"),
    ("christmas pudding", "gluten eggs tree_nuts sulphites meat milk"),
    ("red wine", "sulphites"),
    ("dry sherry", "sulphites"),
    ("port", "sulphites"),
    ("dry vermouth", "sulphites"),
    ("cider", "sulphites"),
    ("balsamic vinegar", "sulphites"),
    ("white wine vinegar", "sulphites"),
    ("cider vinegar", "sulphites"),
    ("dried apricots", "sulphites"),
    ("raisins", "sulphites"),
    ("sultanas", "sulphites"),
    ("currants", "sulphites"),
    ("glacé cherries", "sulphites"),
    ("beer", "gluten"),
    ("brown ale", "gluten"),
    ("stout", "gluten"),
    ("malt vinegar", "gluten"),
    ("rolled oats", "gluten"),
    ("medium oatmeal", "gluten"),
    ("porridge", "gluten"),
    ("tomato ketchup", "celery"),
    ("BBQ sauce", "celery mustard"),
    ("barbecue sauce", "celery mustard"),
    ("vinaigrette", "mustard sulphites"),
    ("dijon mustard", "mustard sulphites"),
    ("wholegrain mustard", "mustard"),
    ("mild curry powder", "mustard celery"),
    ("worcestershire sauce", "fish gluten"),
    ("caesar dressing", "fish eggs milk"),
    ("basil pesto", "tree_nuts milk rennet"),
    ("hummus", "sesame"),
    ("tahini", "sesame"),
    ("za'atar", "sesame"),
    ("halva", "sesame"),
    ("gomasio", "sesame"),
    ("satay sauce", "peanuts"),
    ("groundnut oil", "peanuts"),
    ("arachis oil", "peanuts"),
    ("nougat", "tree_nuts eggs"),
    ("gianduja", "tree_nuts"),
    ("amaretti biscuits", "tree_nuts gluten"),
    ("nutella", "tree_nuts milk soy"),
    ("marzipan", "tree_nuts"),
    ("praline", "tree_nuts"),
    ("frangipane", "tree_nuts"),
    ("saltfish", "fish"),
    ("bacalao", "fish"),
    ("surimi", "fish crustaceans eggs gluten"),
    ("cod roe", "fish"),
    ("dashi", "fish"),
    ("bonito flakes", "fish"),
    ("anchovy fillets", "fish"),
    ("fish sauce", "fish"),
    ("celeriac", "celery"),
    ("celery salt", "celery"),
    ("celery seed", "celery"),
    ("firm tofu", "soy"),
    ("tempeh", "soy"),
    ("edamame beans", "soy"),
    ("soya mince", "soy"),
    ("lamb mince", "meat"),
    ("honey", "honey"),
    ("lard", "meat"),
    ("beef suet", "meat gluten"),
    ("beef dripping", "meat"),
    ("parmesan", "milk rennet"),
    ("Parmigiano Reggiano", "milk rennet"),
    ("grana padano", "milk rennet"),
    ("pecorino", "milk rennet"),
    ("pecorino romano", "milk rennet"),
    ("gorgonzola", "milk rennet"),
    ("roquefort", "milk rennet"),
    ("gruyère", "milk rennet"),
    ("emmental", "milk rennet"),
    ("comté", "milk rennet"),
    ("manchego", "milk rennet"),
    ("cheddar cheese", "milk"),
    ("unsalted butter", "milk"),
    ("double cream", "milk"),
    ("natural yogurt", "milk"),
    ("greek yoghurt", "milk"),
    ("semi-skimmed milk", "milk"),
    ("whey protein", "milk"),
    ("sodium caseinate", "milk"),
    ("ghee", "milk"),
]

# --- exceptions: each removes only the tag it names -------------------------------------------

EXCEPTION_CASES = [
    ("coconut milk", ""),
    ("almond milk", "tree_nuts"),
    ("soy milk", "soy"),
    ("soya milk", "soy"),
    ("oat milk", "gluten"),
    ("rice milk", ""),
    ("coconut cream", ""),
    ("cream of coconut", ""),
    ("cocoa butter", ""),
    ("peanut butter", "peanuts"),
    ("shea butter", ""),
    ("nut butter", "tree_nuts peanuts"),
    ("almond butter", "tree_nuts"),
    ("butternut squash", ""),
    ("butter beans", ""),
    ("cream of tartar", ""),
    ("cream crackers", "gluten"),
    ("grated nutmeg", ""),
    ("water chestnuts", ""),
    ("waterchestnuts", ""),
    ("desiccated coconut", "sulphites"),
    ("coconut", ""),
    ("doughnuts", "gluten eggs milk"),
    ("donut", "gluten eggs milk"),
    ("eggplant", ""),
    ("egg plant", ""),
    ("aubergine", ""),
    ("buckwheat", ""),
    ("buckwheat groats", ""),
    ("fish slice", ""),
    ("butter knife", ""),
    ("egg slice", ""),
    ("ice cream scoop", ""),
    ("egg cup", ""),
    ("roll into walnut-sized balls", ""),
    ("egg-sized pieces", ""),
    ("the size of a walnut", ""),
    ("beef tomatoes", ""),
    ("lamb's lettuce", ""),
    ("red kidney beans", ""),
    ("pigeon peas", ""),
    ("duck eggs", "eggs"),
    ("goat's cheese", "milk"),
    ("buffalo mozzarella", "milk"),
    ("crab meat", "crustaceans"),
    ("crabmeat", "crustaceans"),
    ("poultry seasoning", ""),
    ("oyster mushrooms", ""),
    ("crab apples", ""),
    ("chestnut mushrooms", ""),
    ("madeira cake", "gluten"),
    ("romano peppers", ""),
    ("hamburger buns", "gluten"),
    ("pizza sauce", ""),
    ("pasta sauce", ""),
    ("ginger beer", ""),
    ("pine nuts", "tree_nuts"),
    ("brazil nuts", "tree_nuts"),
    ("monkey nuts", "peanuts"),
    ("ground nuts", "tree_nuts peanuts"),
    ("tiger nuts", ""),
    ("flax egg", ""),
    ("mince the garlic", ""),
    ("tuna steaks", "fish"),
    ("cauliflower steak", ""),
    ("wrap in foil and chill", ""),
    ("roll the dough into a sausage", "gluten"),
    ("vegan cheese", ""),
    ("vegan mayo", "mustard"),
    ("vegan butter", ""),
    ("vegetarian sausages", "gluten sulphites"),
    ("veggie burgers", "gluten sulphites"),
    ("vegetarian parmesan", "milk"),
    ("dairy-free chocolate", "soy"),
    ("gluten-free flour", ""),
    ("gluten free pasta", ""),
    ("meat-free mince", ""),
    ("egg-free mayonnaise", "mustard"),
    ("nut-free pesto", "milk rennet"),
]

# --- inflections, accents, spelling variants and compounds ------------------------------------

FORMS = [
    ("EGGS", "eggs"),
    ("Free-Range Eggs", "eggs"),
    ("egg yolks", "eggs"),
    ("king prawns", "crustaceans"),
    ("anchovies", "fish"),
    ("mussels", "molluscs"),
    ("molluscs", "molluscs"),
    ("mollusks", "molluscs"),
    ("baby squid", "molluscs"),
    ("loaves", "gluten"),
    ("cherry tomatoes", ""),
    ("berries", ""),
    ("pastries", "gluten milk eggs"),
    ("yoghurt", "milk"),
    ("yogurt", "milk"),
    ("chilli jam", "crustaceans fish"),
    ("chili jam", "crustaceans fish"),
    ("chile jam", "crustaceans fish"),
    ("soya sauce", "soy gluten"),
    ("soya beans", "soy"),
    ("gelatin", "gelatin"),
    ("grey mullet", "fish"),
    ("gray mullet", "fish"),
    ("crème fraîche", "milk"),
    ("Crème Brûlée", "eggs milk"),
    ("pâté", "meat"),
    ("Jamón", "meat sulphites"),
    ("Smørrebrød", "gluten"),
    ("halloumi", "milk"),
    ("houmous", "sesame"),
    ("catsup", "celery"),
    ("monkfish", "fish"),
    ("catfish", "fish"),
    ("swordfish steaks", "fish"),
    ("shellfish", "crustaceans molluscs"),
    ("crayfish", "crustaceans"),
    ("crawfish", "crustaceans"),
    ("cuttlefish", "molluscs"),
    ("jellyfish salad", ""),
    ("starfish", ""),
    ("buttermilk", "milk"),
    ("soymilk", "soy"),
    ("shortbread", "gluten milk"),
    ("sweetbreads", "meat"),
    ("gingerbread", "gluten"),
    ("flatbreads", "gluten"),
    ("cupcakes", "gluten"),
    ("fishcakes", "fish gluten"),
    ("oatcakes", "gluten"),
    ("sausagemeat", "meat gluten sulphites"),
    ("cobnuts", "tree_nuts"),
    ("hickorynuts", "tree_nuts"),
    ("cheeseburger", "milk meat gluten sulphites"),
    ("milkshake", "milk"),
    ("wholewheat pasta", "gluten"),
    ("malted milk", "gluten milk"),
]

# --- substrings and look-alikes must not match -------------------------------------------------

NOT_SUBSTRINGS = [
    ("coat with breadcrumbs", "gluten"),
    ("coat the fillets", ""),
    ("simmer for 5 minutes", ""),
    ("goats", "meat"),
    ("a bunch of parsley", ""),
    ("pineapple chunks", ""),
    ("kale", ""),
    ("pale ale", "gluten"),
    ("a portion of rice", ""),
    ("orange peel", ""),
    ("fresh basil", ""),
    ("start the timer", ""),
    ("a piece of ginger", ""),
    ("flank steak", "meat"),
    ("chickpeas", ""),
    ("hamper", ""),
    ("graham crackers", "gluten"),
    ("scrambled tofu", "soy"),
    ("shallots", ""),
    ("peas", ""),
    ("stockpot", "celery"),
    ("nutritional yeast", ""),
    ("eggless sponge", ""),
    ("caramelised onions", ""),
    ("creamy texture", ""),
    ("buttery", ""),
    ("salt", ""),
    ("saltines", ""),
]

# --- punctuation: an exception never reaches across it ----------------------------------------

PUNCTUATION = [
    ("vegan chicken pieces", ""),
    ("if not vegan, chicken stock", "meat celery"),
    ("vegetarian. Chicken stock works too", "meat celery"),
    ("rice, flour and eggs", "gluten eggs"),
    ("coconut, milk", "milk"),
    ("peanut; butter", "peanuts milk"),
    ("egg, plant pots", "eggs"),
    ("gluten free (flour)", "gluten"),
    ("dairy-free\nbutter", "milk"),
]

GOLDEN = NORMATIVE + EXCEPTION_CASES + FORMS + NOT_SUBSTRINGS + PUNCTUATION


@pytest.mark.parametrize(("text", "expected"), GOLDEN)
def test_tag_text(text: str, expected: str) -> None:
    assert show(tag_text(text)) == show(tags(expected))


def test_enough_golden_cases() -> None:
    assert len(GOLDEN) + len(FOODS) >= 150


# --- tag_food: USDA category rules -------------------------------------------------------------

D, F, N, L = (
    "Dairy and Egg Products",
    "Finfish and Shellfish Products",
    "Nut and Seed Products",
    "Legumes and Legume Products",
)
C, B, BC, S = "Cereal Grains and Pasta", "Baked Products", "Breakfast Cereals", "Sweets"
SOUPS = "Soups, Sauces, and Gravies"

FOODS = [
    ("Cheese, cottage, creamed", D, "milk"),
    ("Milk, whole, 3.25% milkfat", D, "milk"),
    ("Dessert topping, powdered", D, "milk"),
    ("Egg, whole, raw, fresh", D, "eggs"),
    ("Egg, white, dried", D, "eggs"),
    ("Egg substitute, powder", D, "eggs"),
    ("Eggnog", D, "eggs milk"),
    ("Cheese, parmesan, hard", D, "milk rennet"),
    ("Fish, cod, Atlantic, raw", F, "fish"),
    ("Roe, mixed species, raw", F, "fish"),
    ("Crustaceans, shrimp, mixed species, raw", F, "crustaceans"),
    ("Crustaceans, crayfish, mixed species, farmed, raw", F, "crustaceans"),
    ("Mollusks, squid, mixed species, raw", F, "molluscs"),
    ("Mollusks, snail, raw", F, "molluscs"),
    ("Frog legs, raw", F, "meat"),
    ("Turtle, green, raw", F, "meat"),
    ("Beef, ground, 85% lean meat / 15% fat, raw", "Beef Products", "meat"),
    ("Pork, fresh, loin, raw", "Pork Products", "meat"),
    ("Chicken, broilers or fryers, breast, raw", "Poultry Products", "meat"),
    ("Lamb, ground, raw", "Lamb, Veal, and Game Products", "meat"),
    ("Bologna, beef", "Sausages and Luncheon Meats", "meat"),
    ("Nuts, almonds", N, "tree_nuts"),
    ("Nuts, pine nuts, dried", N, "tree_nuts"),
    ("Nuts, coconut meat, raw", N, ""),
    ("Nuts, coconut milk, canned (liquid expressed from grated meat and water)", N, ""),
    ("Nuts, mixed nuts, dry roasted, with peanuts", N, "tree_nuts peanuts"),
    ("Seeds, sesame seeds, whole, dried", N, "sesame"),
    ("Seeds, sesame butter, tahini", N, "sesame"),
    ("Seeds, sunflower seed kernels, dried", N, ""),
    ("Seeds, pumpkin and squash seed kernels", N, ""),
    ("Peanuts, all types, raw", L, "peanuts"),
    ("Peanut butter, smooth style, with salt", L, "peanuts"),
    ("Tofu, raw, firm, prepared with calcium sulfate", L, "soy"),
    ("Miso", L, "soy gluten"),
    ("Soy sauce made from soy (tamari)", L, "soy gluten"),
    ("Lupins, mature seeds, raw", L, "lupin"),
    ("Beans, kidney, red, mature seeds, raw", L, ""),
    ("Chickpea flour (besan)", L, ""),
    ("Hummus, commercial", L, "sesame"),
    ("Wheat flour, white, all-purpose, enriched", C, "gluten"),
    ("Rice, white, long-grain, regular, raw", C, ""),
    ("Rice, white, glutinous, unenriched, uncooked", C, ""),
    ("Rice noodles, dry", C, ""),
    ("Noodles, chinese, cellophane or long rice (mung beans), dehydrated", C, ""),
    ("Noodles, egg, dry, enriched", C, "eggs gluten"),
    ("Noodles, japanese, soba, dry", C, "gluten"),
    ("Pasta, gluten-free, corn, dry", C, ""),
    ("Pasta, dry, enriched", C, "gluten"),
    ("Couscous, dry", C, "gluten"),
    ("Bulgur, dry", C, "gluten"),
    ("Oats", C, "gluten"),
    ("Barley, pearled, raw", C, "gluten"),
    ("Buckwheat", C, ""),
    ("Buckwheat groats, roasted, dry", C, ""),
    ("Quinoa, uncooked", C, ""),
    ("Millet, raw", C, ""),
    ("Sorghum grain", C, ""),
    ("Amaranth grain, uncooked", C, ""),
    ("Teff, uncooked", C, ""),
    ("Wild rice, raw", C, ""),
    ("Tapioca, pearl, dry", C, ""),
    ("Cornstarch", C, ""),
    ("Corn flour, masa, enriched, white", C, ""),
    ("Hominy, canned, white", C, ""),
    ("Bread, white, commercially prepared", B, "gluten"),
    ("Bread, gluten-free, white, made with rice flour, corn starch, and/or tapioca", B, ""),
    ("Tortillas, ready-to-bake or -fry, corn", B, ""),
    ("Tortillas, ready-to-bake or -fry, flour, refrigerated", B, "gluten"),
    ("Taco shells, baked", B, "gluten"),
    ("Leavening agents, baking powder, double-acting", B, "gluten"),
    ("Croissants, butter", B, "gluten milk eggs"),
    ("Cereals, corn grits, white, regular and quick, enriched, dry", BC, ""),
    ("Cereals ready-to-eat, rice, puffed, fortified", BC, "gluten"),
    ("Cereals, oats, regular and quick, not fortified, dry", BC, "gluten"),
    ("Cereals, MALT-O-MEAL, original, plain, dry", BC, "gluten"),
    ("Soup, stock, chicken, home-prepared", SOUPS, "celery meat"),
    ("Soup, vegetable broth, ready to serve", SOUPS, "celery"),
    ("Soup, cream of mushroom, canned, condensed", SOUPS, "celery milk"),
    ("Gravy, instant beef, dry", SOUPS, "celery gluten meat"),
    ("Sauce, hoisin, ready-to-serve", SOUPS, "soy gluten sesame"),
    ("Sauce, oyster, ready-to-serve", SOUPS, "molluscs soy gluten"),
    ("Sauce, worcestershire", SOUPS, "fish gluten"),
    ("Sauce, pesto, ready-to-serve, refrigerated", SOUPS, "tree_nuts milk rennet"),
    ("Sauce, duck, ready-to-serve", SOUPS, ""),
    ("Sauce, salsa, ready-to-serve", SOUPS, ""),
    ("Candies, milk chocolate", S, "milk soy"),
    ("Cocoa, dry powder, unsweetened", S, ""),
    ("Honey", S, "honey"),
    ("Gelatins, dry powder, unsweetened", S, "gelatin"),
    ("Oil, peanut, salad or cooking", "Fats and Oils", "peanuts"),
    ("Oil, sesame, salad or cooking", "Fats and Oils", "sesame"),
    ("Oil, olive, salad or cooking", "Fats and Oils", ""),
    ("Lard", "Fats and Oils", "meat"),
    ("Margarine, regular, 80% fat, composite, stick, with salt", "Fats and Oils", "milk"),
    ("Salad dressing, mayonnaise, regular", "Fats and Oils", "eggs mustard"),
    ("Spices, celery seed", "Spices and Herbs", "celery"),
    ("Spices, mustard seed, ground", "Spices and Herbs", "mustard"),
    ("Spices, curry powder", "Spices and Herbs", "mustard celery"),
    ("Spices, poultry seasoning", "Spices and Herbs", ""),
    ("Spices, nutmeg, ground", "Spices and Herbs", ""),
    ("Eggplant, raw", "Vegetables and Vegetable Products", ""),
    ("Celery, raw", "Vegetables and Vegetable Products", "celery"),
    ("Mushrooms, oyster, raw", "Vegetables and Vegetable Products", ""),
    ("Squash, winter, butternut, raw", "Vegetables and Vegetable Products", ""),
    ("Waterchestnuts, chinese, (matai), raw", "Vegetables and Vegetable Products", ""),
    ("Salsify, (vegetable oyster), raw", "Vegetables and Vegetable Products", ""),
    ("Raisins, dark, seedless", "Fruits and Fruit Juices", "sulphites"),
    ("Apricots, dried, sulfured, uncooked", "Fruits and Fruit Juices", "sulphites"),
    ("Alcoholic beverage, wine, table, red", "Beverages", "sulphites"),
    ("Alcoholic beverage, beer, regular, all", "Beverages", "gluten"),
    ("Beverages, almond milk, unsweetened, shelf stable", "Beverages", "tree_nuts"),
    ("Beverages, coconut milk, sweetened, fortified", "Beverages", ""),
    ("Beverages, water, tap, drinking", "Beverages", ""),
    ("Kielbasa, fully cooked, unheated", "Sausages and Luncheon Meats", "meat gluten sulphites"),
    ("Restaurant, Chinese, egg rolls, assorted", "Restaurant Foods", "eggs gluten"),
    ("Fast foods, cheeseburger; single, regular patty", "Fast Foods", "milk meat gluten sulphites"),
    ("Something new", None, ""),
]


@pytest.mark.parametrize(("description", "category", "expected"), FOODS)
def test_tag_food(description: str, category: str | None, expected: str) -> None:
    # fdc_id 1 has no food_tags.csv row: rules only.
    assert show(tag_food(1, description, category)) == show(tags(expected))


def test_food_tags_csv_adds_and_removes() -> None:
    # Fresh currants: the dried-currant sulphite rule is removed (with a note).
    assert tag_food(173964, "Currants, red and white, raw", "Fruits and Fruit Juices") == tags("")
    assert tag_food(1, "Currants, red and white, raw", "Fruits and Fruit Juices") == tags(
        "sulphites"
    )
    # Traditional refried beans are made with lard.
    refried = "Refried beans, canned, traditional style"
    assert tag_food(172438, refried, L) == tags("meat")
    assert tag_food(1, refried, L) == tags("")


def test_food_tags_csv_is_well_formed() -> None:
    rows = load_food_tags()
    assert rows
    for add, remove in rows.values():
        assert add == add.normalised()
        assert remove == remove.normalised()
        assert add != FoodTags() or remove != FoodTags()
        assert not add.allergens & remove.allergens
        assert not add.animal & remove.animal


# --- forms of every rule stem ------------------------------------------------------------------


def _plural(word: str) -> str:
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


_ACCENTS = {"a": "à", "e": "é", "i": "î", "o": "ô", "u": "ü", "c": "ç", "n": "ñ"}
_STEMS = sorted({" ".join(p.words) for p in RULES})


def test_every_stem_matches_in_plural() -> None:
    wrong: list[tuple[str, ...]] = []
    for stem in _STEMS:
        *head, last = stem.split()
        plural = " ".join([*head, _plural(last)])
        if tag_text(plural) != tag_text(stem):
            wrong.append((stem, plural, show(tag_text(stem)), show(tag_text(plural))))
    assert wrong == []


def test_every_stem_matches_accented_and_capitalised() -> None:
    wrong: list[tuple[str, ...]] = []
    for stem in _STEMS:
        accented = "".join(_ACCENTS.get(c, c) for c in stem)
        for variant in (accented, stem.upper(), stem.title()):
            if tag_text(variant) != tag_text(stem):
                wrong.append((stem, variant))
    assert wrong == []


def test_every_stem_tags_something() -> None:
    assert [s for s in _STEMS if tag_text(s) == FoodTags()] == []


def test_exception_words_never_hide_a_compound() -> None:
    # A word known only from an exception is never split into parts, so an exception must not
    # mention a compound food (adding "swordfish steak" would hide the fish in "swordfish").
    rule_words = {w for p in RULES for w in p.words}
    exception_only = {w for p in EXCEPTIONS for w in p.words} - rule_words
    compounds = {w for w in exception_only if len(w) > 4 and w.endswith(("fish", "milk", "bread"))}
    compounds |= {w for w in exception_only if len(w) > 4 and w.endswith(("cake", "meat", "nut"))}
    assert compounds == {"butternut"}


def test_forms() -> None:
    assert forms("anchovies") >= {"anchovy"}
    assert forms("tomatoes") >= {"tomato"}
    assert forms("chillies") >= {"chilli"}
    assert forms("yoghurts") >= {"yogurt"}
    assert forms("glass") == frozenset({"glass"})
    assert forms("eggplant") == frozenset({"aubergine"})


# --- properties ----------------------------------------------------------------------------------

_WORDS = sorted({w for p in RULES + EXCEPTIONS for w in p.words if w != "*"})
_FILLERS = ["the", "and", "with", "fresh", "chopped", "2", "tbsp", "of", "a", "into", "sauce"]
_SEPARATORS = [" ", ", ", ". ", "; ", "\n", " - ", "-", " (", ") "]
_phrase = st.lists(st.sampled_from(_WORDS + _FILLERS), min_size=1, max_size=8).map(" ".join)
_text = st.lists(st.tuples(_phrase, st.sampled_from(_SEPARATORS)), max_size=4).map(
    lambda parts: "".join(p + s for p, s in parts)
)
_tags_strategy = st.builds(
    FoodTags,
    st.frozensets(st.sampled_from(list(Allergen))),
    st.frozensets(st.sampled_from(list(AnimalTag))),
)


@given(_text)
def test_tag_text_is_deterministic_and_normalised(text: str) -> None:
    result = tag_text(text)
    assert result == tag_text(text)
    assert result == result.normalised()


@given(_phrase, _phrase, st.sampled_from([". ", ", ", "; ", "\n", " / "]))
def test_more_text_never_hides_a_tag(first: str, second: str, sep: str) -> None:
    # Exceptions can't reach across punctuation, so appending a sentence only adds tags.
    both = tag_text(first + sep + second)
    alone = tag_text(first) | tag_text(second)
    assert covers(both, alone)


@given(_phrase, st.one_of(st.none(), st.sampled_from(sorted({f[1] for f in FOODS if f[1]}))))
def test_tag_food_is_normalised(description: str, category: str | None) -> None:
    result = tag_food(1, description, category)
    assert result == result.normalised() == tag_food(1, description, category)


@given(_tags_strategy)
def test_normalised_is_idempotent_and_coupled(t: FoodTags) -> None:
    n = t.normalised()
    assert n.normalised() == n
    assert covers(n, t)
    assert (Allergen.MILK in n.allergens) == (AnimalTag.DAIRY in n.animal)
    assert (Allergen.EGGS in n.allergens) == (AnimalTag.EGG in n.animal)
    assert (Allergen.FISH in n.allergens) == (AnimalTag.FISH in n.animal)
    shellfish = bool(n.allergens & {Allergen.CRUSTACEANS, Allergen.MOLLUSCS})
    assert shellfish == (AnimalTag.SHELLFISH in n.animal)


@given(st.lists(st.tuples(_phrase, st.one_of(st.none(), _tags_strategy), st.booleans())), _text)
def test_recipe_tags_are_normalised_and_cover_every_line(
    raw: list[tuple[str, FoodTags | None, bool]], instructions: str
) -> None:
    lines = [Line(name, food, exact) for name, food, exact in raw]
    result = recipe_tags("Dish", None, instructions, lines)
    t = FoodTags(result.allergens, result.animal)
    assert t == t.normalised()
    for line in lines:
        part = tag_text(line.raw_name) | (line.food or FoodTags())
        assert covers(t, part)
    assert result.unresolved <= len(lines)


# --- recipe_tags ---------------------------------------------------------------------------------


def test_recipe_tags_unions_foods_text_name_and_instructions() -> None:
    lines = [
        Line("Chicken thighs", tags("meat"), exact=True),
        Line("Soy sauce", tags("soy gluten"), exact=True),
    ]
    r = recipe_tags("Egg Drop Soup", "Starter", "Whisk in 1 egg. Garnish with sesame seeds.", lines)
    assert FoodTags(r.allergens, r.animal) == tags("meat soy gluten eggs sesame")
    assert r.complete
    assert r.suitable_for() == []


def test_recipe_tags_unresolved_lines() -> None:
    reviewed = "Thai red curry paste"  # an approximation alias, reviewed in line_tags.csv
    assert line_tags(reviewed) == tags("crustaceans fish")
    lines = [
        Line("Mystery spice", None, exact=False),  # nothing matched
        Line("Unreviewed thing", tags(""), exact=False),  # automatic match, not reviewed
        Line(reviewed, tags("mustard celery"), exact=False),  # reviewed: resolved
        Line("Onion", tags(""), exact=True),
    ]
    r = recipe_tags("Curry", None, "", lines)
    assert r.unresolved == 2
    assert not r.complete
    assert r.suitable_for() == []
    assert {Allergen.CRUSTACEANS, Allergen.FISH, Allergen.MUSTARD} <= r.allergens


def test_recipe_tags_category_backstops() -> None:
    spices = [Line("Ground cumin", tags(""), exact=True)]
    beef = recipe_tags("Spiced thing", "Beef", "", spices)
    assert FoodTags(beef.allergens, beef.animal) == tags("meat")
    seafood = recipe_tags("Spiced thing", "Seafood", "", spices)
    assert FoodTags(seafood.allergens, seafood.animal) == tags("fish crustaceans molluscs")
    # With a named crustacean the allergen backstop isn't needed, but fish/shellfish stay.
    prawns = [Line("King prawns", tags("crustaceans"), exact=True)]
    r = recipe_tags("Garlic prawns", "Seafood", "", prawns)
    assert FoodTags(r.allergens, r.animal) == tags("crustaceans fish")
    assert recipe_tags("Garlic prawns", "Seafood", "", prawns).suitable_for() == [Diet.PESCATARIAN]
    # A MealDB "Vegetarian" category is never a diet claim on its own.
    stock = [Line("Chicken stock cube", tags("meat gluten celery"), exact=True)]
    assert recipe_tags("Borscht", "Vegetarian", "", stock).suitable_for() == []


def test_suitable_for_diets() -> None:
    def diets(spec: str) -> list[Diet]:
        t = tags(spec)
        return recipe_tags("x", None, "", [Line("x", t, exact=True)]).suitable_for()

    assert diets("") == [Diet.VEGETARIAN, Diet.VEGAN, Diet.PESCATARIAN]
    assert diets("milk eggs honey") == [Diet.VEGETARIAN, Diet.PESCATARIAN]
    assert diets("milk rennet") == [Diet.PESCATARIAN]
    assert diets("fish") == [Diet.PESCATARIAN]
    assert diets("gelatin") == []
    assert diets("meat") == []
    assert diet_allows(None, frozenset(AnimalTag))
    assert FORBIDDEN[Diet.VEGAN] == frozenset(AnimalTag)


# --- data files ----------------------------------------------------------------------------------


def test_make_line_is_exact_only_for_curated_non_approximate_aliases() -> None:
    onion = tags("")
    assert make_line("Onions", 170000, onion).exact  # alias "onion" -> 170000
    assert not make_line("Onions", 170001, onion).exact  # stale or different food
    assert not make_line("Onions", None, None).exact
    assert not make_line("Thai red curry paste", 170924, onion).exact  # approximation
    assert not make_line("Something unseen", 1, onion).exact


def test_line_tags_cover_every_approximation_alias() -> None:
    reviewed = load_line_tags()
    approximations = {a.name for a in load_alias_rows() if a.approximation}
    assert approximations - reviewed.keys() == set()


def test_line_tags_are_keyed_by_normalised_name() -> None:
    from larder_core.names import normalise_name

    reviewed = load_line_tags()
    assert len(reviewed) >= 360
    assert [n for n in reviewed if normalise_name(n) != n] == []
    assert line_tags("Thai Red Curry Paste") == line_tags("thai red curry paste")
    assert line_tags("Galangal") == FoodTags()  # reviewed, none
    assert line_tags("never reviewed") is None


def test_parse_and_format_tags() -> None:
    assert parse_tags("milk|eggs", "-") == tags("milk eggs")
    assert parse_tags("-", "") == FoodTags()
    assert parse_tags("", "shellfish") == tags("crustaceans molluscs")
    assert format_tags(tags("milk eggs").allergens) == "eggs|milk"
    assert format_tags(frozenset[Allergen]()) == "-"
    with pytest.raises(ValueError, match="nuts"):
        parse_tags("nuts", "")
