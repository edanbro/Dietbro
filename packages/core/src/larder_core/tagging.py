"""Allergen and animal-product tags for USDA foods, ingredient text and whole recipes.

Safety rule: tagging is conservative. A false positive hides a recipe; a false negative can hurt
someone, so when in doubt, tag. Tags are derived at runtime from these rules plus reviewed data
files (no stored column to go stale):

- `data/food_tags.csv`: per-USDA-food additions (and rare, noted removals) on top of the rules.
- `data/line_tags.csv`: reviewed ingredient names whose matched food is an approximation or an
  automatic (embedding) match: the extra tags the real ingredient carries ('-' = reviewed, none).

Text matching (`tag_text`) normalises (NFKD, strip accents, casefold, non-alphanumerics -> space)
and matches whole tokens or phrases, with plural/inflection variants and a short list of compound
suffixes (saltfish, buttermilk, shortbread), never raw substrings ("coat" is not oats).
Exceptions (coconut milk is not milk) only remove the tags they name, only from matches lying
wholly inside them, and in free text never across punctuation ("vegan, chicken stock" keeps the
chicken).
"""

import csv
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib import resources

from larder_core.aliases import load_alias_rows
from larder_core.allergens import Allergen
from larder_core.names import normalise_name


class AnimalTag(StrEnum):
    MEAT = "meat"  # incl. poultry, game, offal, lard, suet, meat stock, frog
    FISH = "fish"  # incl. anchovy in sauces, fish sauce
    SHELLFISH = "shellfish"  # crustaceans and molluscs
    DAIRY = "dairy"
    EGG = "egg"
    HONEY = "honey"
    GELATIN = "gelatin"  # gelatine, isinglass and other slaughter by-products
    RENNET = "rennet"  # traditional hard cheeses made with animal rennet (parmesan, pecorino…)


class Diet(StrEnum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    PESCATARIAN = "pescatarian"


FORBIDDEN: dict[Diet, frozenset[AnimalTag]] = {
    Diet.VEGAN: frozenset(AnimalTag),
    Diet.VEGETARIAN: frozenset(
        {AnimalTag.MEAT, AnimalTag.FISH, AnimalTag.SHELLFISH, AnimalTag.GELATIN, AnimalTag.RENNET}
    ),
    Diet.PESCATARIAN: frozenset({AnimalTag.MEAT, AnimalTag.GELATIN}),
}


def diet_allows(diet: Diet | None, animal: frozenset[AnimalTag]) -> bool:
    return diet is None or not (animal & FORBIDDEN[diet])


@dataclass(frozen=True, slots=True)
class FoodTags:
    allergens: frozenset[Allergen] = frozenset()
    animal: frozenset[AnimalTag] = frozenset()

    def __or__(self, other: "FoodTags") -> "FoodTags":
        return FoodTags(self.allergens | other.allergens, self.animal | other.animal)

    def normalised(self) -> "FoodTags":
        """Couple allergens and animal tags so neither side can be forgotten: milk <-> dairy,
        eggs <-> egg, fish <-> fish, crustaceans/molluscs -> shellfish, and shellfish with
        neither allergen -> both. Every function here returns normalised tags."""
        a, t = set(self.allergens), set(self.animal)
        if Allergen.MILK in a or AnimalTag.DAIRY in t:
            a.add(Allergen.MILK)
            t.add(AnimalTag.DAIRY)
        if Allergen.EGGS in a or AnimalTag.EGG in t:
            a.add(Allergen.EGGS)
            t.add(AnimalTag.EGG)
        if Allergen.FISH in a or AnimalTag.FISH in t:
            a.add(Allergen.FISH)
            t.add(AnimalTag.FISH)
        if Allergen.CRUSTACEANS in a or Allergen.MOLLUSCS in a:
            t.add(AnimalTag.SHELLFISH)
        elif AnimalTag.SHELLFISH in t:
            a |= {Allergen.CRUSTACEANS, Allergen.MOLLUSCS}
        return FoodTags(frozenset(a), frozenset(t))


@dataclass(frozen=True, slots=True)
class Line:
    """One recipe ingredient line, as far as tagging is concerned."""

    raw_name: str
    food: FoodTags | None  # tags of the matched food; None = no food matched
    # True when the match is exact (a non-approximation curated alias). Approximate and
    # automatic matches only count as known once their name is reviewed in line_tags.csv.
    exact: bool


@dataclass(frozen=True, slots=True)
class RecipeTags:
    allergens: frozenset[Allergen]
    animal: frozenset[AnimalTag]
    unresolved: int  # lines whose allergen content isn't established

    @property
    def complete(self) -> bool:
        return self.unresolved == 0

    def suitable_for(self) -> list[Diet]:
        return [d for d in Diet if self.complete and diet_allows(d, self.animal)]


def tag_food(fdc_id: int, description: str, category: str | None) -> FoodTags:
    """Tags for a USDA food: category rules | keyword rules on the description | food_tags.csv
    additions, minus noted removals."""
    text = _text(description)
    # USDA descriptions are comma-separated qualifiers ("Nuts, almonds"; "Sauce, oyster"), so
    # exceptions may span commas here.
    tags = _category_tags(text.words, category) | _scan(text, across_punctuation=True)
    if _gluten_free(text.words, category):
        tags = _minus(tags, _GLUTEN)
    add, remove = load_food_tags().get(fdc_id, (_NONE, _NONE))
    return _minus((tags | add).normalised(), remove).normalised()


def tag_text(text: str) -> FoodTags:
    """Tags implied by free text: an ingredient line ("soy sauce", "worcestershire sauce"), a
    recipe name ("Egg Drop Soup") or instructions ("add 1 egg"). Utensil phrases ("fish slice",
    "butter knife") and "<x>-sized" don't count."""
    return _scan(_text(text), across_punctuation=False).normalised()


def recipe_tags(
    name: str, category: str | None, instructions: str, lines: Iterable[Line]
) -> RecipeTags:
    """The single definition of a recipe's tags, used by the planner catalog and the recipe page:
    union of matched foods' tags, `tag_text` of every raw name, the name and the instructions,
    reviewed line tags, and category backstops (Beef/Chicken/Pork/Lamb/Goat -> meat; Seafood ->
    fish + shellfish, plus all three allergens when no ingredient carries one)."""
    ingredients = _NONE
    unresolved = 0
    for line in lines:
        reviewed = line_tags(line.raw_name)
        ingredients |= tag_text(line.raw_name) | (line.food or _NONE) | (reviewed or _NONE)
        if line.food is None or (not line.exact and reviewed is None):
            unresolved += 1
    tags = ingredients | tag_text(name) | tag_text(instructions)
    if category in _MEAT_RECIPE_CATEGORIES:
        tags |= _tags("meat")
    elif category == "Seafood":
        # The animal backstop always applies (normalised: shellfish without a named crustacean
        # or mollusc means both); all three allergens when no ingredient names any of them.
        tags |= FoodTags(animal=frozenset({AnimalTag.FISH, AnimalTag.SHELLFISH}))
        if not ingredients.normalised().allergens & _SEAFOOD.allergens:
            tags |= _SEAFOOD
    tags = tags.normalised()
    return RecipeTags(tags.allergens, tags.animal, unresolved)


# --- Reviewed data files ---------------------------------------------------------------------


def line_tags(raw_name: str) -> FoodTags | None:
    """Reviewed extra tags for an approximately or automatically matched ingredient name
    (normalised like the resolver does); None when the name hasn't been reviewed."""
    return load_line_tags().get(normalise_name(raw_name))


def make_line(raw_name: str, food_id: int | None, food: FoodTags | None) -> Line:
    """A recipe line as resolved. Exact only when the normalised name has a curated,
    non-approximate alias to this very food, so a stale or automatic match needs review."""
    exact = food is not None and _exact_aliases().get(normalise_name(raw_name)) == food_id
    return Line(raw_name, food, exact)


@cache
def load_food_tags() -> dict[int, tuple[FoodTags, FoodTags]]:
    """fdc_id -> (additions, removals) from data/food_tags.csv."""
    out: dict[int, tuple[FoodTags, FoodTags]] = {}
    for row in _read_csv("food_tags.csv"):
        fdc_id = int(row["fdc_id"])
        remove = parse_tags(row["remove_allergens"], row["remove_animal"])
        if fdc_id in out:
            raise ValueError(f"food_tags.csv: duplicate fdc_id {fdc_id}")
        if remove != _NONE and not row["note"].strip():
            raise ValueError(f"food_tags.csv: removal for {fdc_id} needs a note")
        out[fdc_id] = (parse_tags(row["add_allergens"], row["add_animal"]), remove)
    return out


@cache
def load_line_tags() -> dict[str, FoodTags]:
    """Normalised ingredient name -> reviewed tags from data/line_tags.csv."""
    out: dict[str, FoodTags] = {}
    for row in _read_csv("line_tags.csv"):
        if row["name"] in out:
            raise ValueError(f"line_tags.csv: duplicate name {row['name']!r}")
        out[row["name"]] = parse_tags(row["allergens"], row["animal"])
    return out


def parse_tags(allergens: str, animal: str) -> FoodTags:
    """Pipe-separated enum values ('' or '-' = none), as stored in the data files."""
    a = [Allergen(v) for v in _values(allergens)]
    t = [AnimalTag(v) for v in _values(animal)]
    return FoodTags(frozenset(a), frozenset(t)).normalised()


def format_tags(values: Iterable[StrEnum]) -> str:
    """Inverse of one `parse_tags` column: sorted, pipe-separated, '-' when empty."""
    return "|".join(sorted(str(v) for v in values)) or "-"


def _values(column: str) -> list[str]:
    column = column.strip()
    return [] if column in ("", "-") else [v.strip() for v in column.split("|")]


def _read_csv(name: str) -> list[dict[str, str]]:
    path = resources.files("larder_core") / "data" / name
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@cache
def _exact_aliases() -> dict[str, int]:
    return {a.name: a.fdc_id for a in load_alias_rows() if not a.approximation}


# --- Keyword rules ---------------------------------------------------------------------------
#
# (phrases, tags): each comma-separated phrase adds every tag. Phrase words are singular and in
# canonical spelling (see _SPELLING); plurals and variants match automatically. A few phrases
# repeat in USDA word order ("sauce oyster" for "Sauce, oyster").

_RULES: tuple[tuple[str, str], ...] = (
    # Crustaceans and molluscs
    (
        "prawn, shrimp, crab, lobster, crayfish, langoustine, langostino, scampi, krill, "
        "crustacean, gamba, camaron",
        "crustaceans",
    ),
    ("bisque", "crustaceans milk"),
    ("shellfish, sea urchin", "shellfish"),
    (
        "clam, mussel, oyster, scallop, squid, calamari, octopus, cuttlefish, snail, escargot, "
        "whelk, abalone, conch, cockle, winkle, periwinkle, limpet, vongole, mollusc",
        "molluscs",
    ),
    (
        "curry paste, chilli jam, nam prik, nam phrik, shrimp paste, prawn paste, belacan, "
        "belachan, blachan, terasi, trassi, kapi, dried shrimp, kimchi, laksa, tom yum, tom yam",
        "crustaceans fish",
    ),
    ("seafood, sea food, fruit de mer, frutti di mare, xo sauce", "fish crustaceans molluscs"),
    ("oyster sauce, sauce oyster", "molluscs soy gluten"),
    # Fish
    (
        "fish, anchovy, cod, lingcod, salmon, tuna, haddock, mackerel, sardine, pilchard, trout, "
        "herring, kipper, sprat, whitebait, sole, plaice, halibut, hake, pollock, pollack, coley, "
        "bass, seabass, bream, snapper, tilapia, mahi, barramundi, perch, pike, carp, eel, "
        "gurnard, dory, turbot, brill, skate, mullet, grouper, whiting, pomfret, kingfish, hilsa, "
        "basa, pangasius, branzino, sturgeon, marlin, rollmop, roe, caviar, taramasalata, ikura, "
        "tobiko, bottarga, lox, gravlax, gravadlax, bacalao, bacalhau, baccala, dashi, bonito, "
        "katsuobushi, nam pla, nuoc mam, colatura, garum, gentleman s relish",
        "fish",
    ),
    ("surimi, crab stick, seafood stick", "fish crustaceans eggs gluten"),
    ("kedgeree", "fish eggs milk"),
    ("worcestershire, worchestershire, worcester sauce", "fish gluten"),
    ("caesar", "fish eggs milk"),
    ("furikake", "sesame fish"),
    ("ponzu, tsuyu, mentsuyu", "soy gluten fish"),
    # Eggs
    (
        "egg, eggwash, eggwhite, eggy, yolk, albumen, meringue, frittata, omelette, souffle, "
        "pavlova, zabaglione, sabayon, shakshuka, huevo, oeuf, tamago, tamagoyaki, "
        "spanish tortilla",
        "eggs",
    ),
    (
        "mayonnaise, mayonaise, mayo, aioli, remoulade, tartare sauce, tartar sauce, salad cream, "
        "coleslaw, thousand island",
        "eggs mustard",
    ),
    (
        "custard, hollandaise, bearnaise, eggnog, carbonara, creme brulee, creme anglaise, "
        "creme caramel, creme patissiere, lemon curd, quorn, mousse, ranch dressing",
        "eggs milk",
    ),
    ("egg noodle, egg roll, egg pasta, fresh pasta, wonton, challah", "eggs gluten"),
    ("scotch egg", "eggs gluten meat sulphites"),
    ("toad in the hole", "meat gluten eggs milk sulphites"),
    (
        "quiche, french toast, eggy bread, pancake, crepe, waffle, yorkshire pudding, popover, "
        "blini, brownie, doughnut, eclair, profiterole, choux, trifle, ladyfinger, savoiardi, "
        "sponge finger, flan",
        "eggs milk gluten",
    ),
    ("tagliatelle, tagliolini, pappardelle, fettuccine, fettuccini", "eggs gluten"),
    ("ravioli, tortellini, tortelloni, cappelletti, agnolotti", "eggs milk gluten"),
    ("macaron, macaroon", "eggs tree_nuts"),
    # Milk
    (
        "milk, dairy, cheese, cheesy, butter, cream, creme, creamer, yogurt, whey, casein, "
        "caseinate, ghee, lactose, curd, kefir, quark, skyr, paneer, ricotta, mozzarella, "
        "mascarpone, burrata, stracciatella, scamorza, feta, halloumi, brie, camembert, cheddar, "
        "stilton, gouda, edam, jarlsberg, havarti, fontina, raclette, reblochon, wensleydale, "
        "red leicester, double gloucester, caerphilly, monterey jack, colby, cotija, queso, "
        "labneh, labne, fromage, chevre, kaymak, smetana, tvorog, bryndza, malai, makhani, khoa, "
        "khoya, rabri, kulfi, lassi, latte, cappuccino, milkshake, icecream, raita, tzatziki, "
        "dulce de leche, milk powder, gelato, fudge, toffee, caramel, butterscotch, buttercream, "
        "ganache, bechamel, alfredo, mornay, gratin, dauphinoise, fondue, rarebit, pudding, "
        "margarine",
        "milk",
    ),
    (
        "parmesan, parmigiano, parmigiana, grana padano, pecorino, romano, gorgonzola, roquefort, "
        "gruyere, emmental, emmentaler, comte, manchego, asiago, provolone, taleggio",
        "milk rennet",
    ),
    ("pesto", "tree_nuts milk rennet"),
    ("chocolate", "milk soy"),
    ("ice cream", "eggs milk"),
    ("cheesecake, tiramisu", "milk eggs gluten"),
    ("cheeseburger", "milk meat gluten sulphites"),
    ("white sauce", "milk gluten"),
    ("panna cotta", "milk gelatin"),
    ("paratha, bhatura, kulcha", "gluten milk"),
    # Gelatin
    (
        "gelatin, jelly, jellied, jello, gummy, marshmallow, isinglass, jelly bean, wine gum",
        "gelatin",
    ),
    ("aspic", "gelatin meat"),
    # Gluten: cereals and what is made from them
    (
        "gluten, wheat, wholewheat, wheatgerm, flour, barley, rye, oat, oatmeal, porridge, spelt, "
        "kamut, triticale, einkorn, emmer, farro, freekeh, frikeh, bulgur, bulgar, bulghur, "
        "burghul, couscous, cous cous, semolina, durum, farina, seitan, bran, graham, malt, "
        "malted, multigrain, cereal, beer, ale, stout, lager, porter, bread, loaf, breadcrumb, "
        "crumb, panko, rusk, crouton, stuffing, tempura, batter, dough, biscuit, digestive, "
        "cracker, cookie, wafer, cake, muffin, scone, crumpet, bagel, baguette, ciabatta, "
        "focaccia, sourdough, smorrebrod, pumpernickel, breadstick, grissini, pretzel, matzo, "
        "matzah, pita, chapati, roti, puri, lavash, khobz, injera, tortilla, wrap, pizza, calzone, "
        "empanada, samosa, spring roll, gyoza, dumpling, bao, pierogi, pierogy, halusky, spaetzle, "
        "spatzle, gnocchi, strudel, churro, crumble, flapjack, granola, muesli, bun, pie, pasty, "
        "tart, tarte, tartlet, galette, pithivier, vol au vent, croquette, katsu, kiev, schnitzel, "
        "tabbouleh, tabouleh, tabouli, fattoush, panzanella, ribollita, gazpacho, gozleme, "
        "lahmacun, pide, kataifi, pasta, noodle, udon, ramen, soba, chow mein, lo mein, "
        "vermicelli, spaghetti, spaghettini, penne, linguine, fusilli, lasagne, macaroni, "
        "maccheroni, orzo, cannelloni, manicotti, rigatoni, paccheri, farfalle, conchiglie, "
        "orecchiette, ziti, bucatini, capellini, ditalini, gemelli, cavatappi, casarecce, "
        "strozzapreti, trofie, mafaldine, radiatori, campanelle, lumache, tortiglioni, anelli, "
        "stelline, pastina, angel hair, gravy, bouillon, stock cube, roux, brown sauce, hp sauce, "
        "on toast, slice of toast, buttered toast, melba toast, toast soldier, vegemite",
        "gluten",
    ),
    (
        "pastry, puff, shortcrust, filo, naan, brioche, croissant, spanakopita, tiropita, borek, "
        "burek",
        "gluten milk eggs",
    ),
    ("shortbread, pizza, calzone, knafeh, kunafa, kanafeh", "gluten milk"),
    ("simit", "gluten sesame"),
    ("kibbeh, kibbe", "gluten meat"),
    ("falafel", "gluten sesame"),
    (
        "soy sauce, shoyu, teriyaki, black bean sauce, sauce black bean, miso, gochujang, "
        "doenjang, ssamjang, kecap, yellow bean sauce",
        "soy gluten",
    ),
    ("hoisin", "soy gluten sesame"),
    ("maggi, knorr, bisto", "gluten celery"),
    ("oxo, bovril", "meat gluten celery"),
    ("enchilada sauce, sauce enchilada", "gluten"),
    ("marmite", "gluten"),
    ("biscotti", "gluten eggs tree_nuts"),
    ("baklava", "gluten tree_nuts milk"),
    ("shaoxing, shaohsing, hsing, rice wine, cooking wine", "gluten sulphites"),
    # Celery
    (
        "celery, celeriac, celery salt, celery seed, stock, stockpot, broth, bouillon, gravy, "
        "ketchup, mirepoix, soffritto",
        "celery",
    ),
    ("barbecue sauce, sauce barbecue", "celery mustard"),
    ("consomme, demi glace, jus", "celery meat"),
    ("curry powder", "mustard celery"),
    # Mustard
    ("mustard, piccalilli, kasundi, panch phoron", "mustard"),
    ("dijon, vinaigrette", "mustard sulphites"),
    # Sesame
    (
        "sesame, tahini, hummus, za atar, zaatar, zahtar, halva, halvah, halwa, gomasio, gomashio, "
        "benne, gingelly, gingili, baba ganoush, baba ghanoush, baba ganouj",
        "sesame",
    ),
    ("dukkah, tarator", "sesame tree_nuts"),
    # Soy
    (
        "soy, soybean, tofu, tempeh, edamame, tamari, natto, yuba, bean curd, beancurd, okara, "
        "tvp, textured vegetable protein, fermented black bean, salted black bean, douchi, "
        "lecithin, kinako",
        "soy",
    ),
    # Peanuts and tree nuts (an unnamed "nut" may be either)
    ("peanut, groundnut, arachis, satay, monkey nut, gado gado", "peanuts"),
    ("nut, mixed nut, trail mix", "tree_nuts peanuts"),
    (
        "almond, walnut, pecan, cashew, hazelnut, pistachio, macadamia, brazil nut, brazilnut, "
        "pine nut, pignoli, pinoli, pinon, chestnut, marzipan, frangipane, frangipan, praline, "
        "gianduja, gianduia, amaretti, amaretto, frangelico, orgeat, romesco, bakewell, turron, "
        "muhammara, korma, pasanda, hickorynut, beechnut, candlenut",
        "tree_nuts",
    ),
    ("nougat", "tree_nuts eggs"),
    ("nutella", "tree_nuts milk soy"),
    # Lupin
    ("lupin, lupine, lupini", "lupin"),
    # Sulphites
    (
        "wine, sherry, port, vermouth, madeira, marsala, champagne, prosecco, cider, sake, "
        "balsamic, raisin, sultana, currant, dried apricot, dried mango, dried peach, dried pear, "
        "dried apple, dried fruit, sun dried tomato, glace, candied, mixed peel, maraschino, "
        "bottled lemon, bottled lime, sulphite, sulphur dioxide, sulphured, metabisulphite, "
        "desiccated coconut",
        "sulphites",
    ),
    # Meat
    (
        "meat, beef, steak, pork, lamb, mutton, hogget, veal, venison, chicken, turkey, duck, "
        "goose, poultry, fowl, rabbit, hare, goat, pheasant, partridge, quail, pigeon, grouse, "
        "boar, bison, buffalo, ostrich, kangaroo, deer, elk, moose, reindeer, caribou, whale, "
        "walrus, beaver, squirrel, frog, turtle, alligator, crocodile, carne, pollo, poulet, "
        "boeuf, porc, cerdo, jambon, lardon, lard, dripping, tallow, schmaltz, liver, kidney, "
        "tripe, offal, oxtail, tongue, sweetbread, giblet, gizzard, foie gra, pate, rillette, "
        "brawn, headcheese, bone marrow, bone broth, mince, sirloin, ribeye, brisket, tenderloin, "
        "short rib, spare rib, shank, pork belly, trotter, hock, knuckle, corned beef, salt beef, "
        "pastrami, bresaola, biltong, jerky, pulled pork, carnitas, char siu, schnitzel, "
        "crackling, scratching, chicharron, doner, shawarma, souvlaki, kebab, kofta, kofte, "
        "bolognese, ragu",
        "meat",
    ),
    (
        "bacon, ham, gammon, salami, chorizo, pepperoni, prosciutto, pancetta, guanciale, jamon, "
        "nduja, saucisson, coppa, speck, mortadella, sobrasada",
        "meat sulphites",
    ),
    (
        "sausage, black pudding, white pudding, blood pudding, haggis, burger, hamburger, hot dog, "
        "frankfurter, wiener, wurst, bratwurst, liverwurst, kielbasa, kabanos, kabano, merguez, "
        "cotechino, andouille, boudin, morcilla, boerewors, lap cheong, lap chong, chipolata, "
        "saveloy, banger",
        "meat gluten sulphites",
    ),
    ("suet", "meat gluten"),
    ("meatball, meatloaf", "meat"),
    ("mincemeat, christmas pudding, mince pie", "meat gluten eggs tree_nuts sulphites"),
    ("mince pie", "milk"),
    # Honey
    ("honey, honeycomb", "honey"),
)

# Flours (and USDA "Flour, rice") with no gluten.
_GLUTEN_FREE_FLOURS = (
    "rice, brown rice, corn, maize, gram, chickpea, chick pea, besan, buckwheat, potato, "
    "tapioca, cassava, coconut, almond, quinoa, soy, lupin, arrowroot, sorghum, teff, millet, "
    "amaranth, chestnut"
)

# (phrases, tags removed from matches lying wholly inside the phrase; '*' = every tag). A '*'
# word in a phrase matches any one word. In free text an exception never spans punctuation.
_EXCEPTIONS: tuple[tuple[str, str], ...] = (
    # Not milk (the other tags stay: oat milk is gluten, soy milk soy, almond milk tree nuts).
    (
        "coconut milk, almond milk, soy milk, oat milk, rice milk, cashew milk, hemp milk, "
        "nut milk, pea milk, coconut cream, cream of coconut, cocoa butter, peanut butter, "
        "shea butter, nut butter, almond butter, cashew butter, apple butter, sesame butter, "
        "seed butter, sunflower butter, butter bean, butter lettuce, cream of tartar, "
        "cream cracker, bean curd, black pudding, white pudding, blood pudding, dairy free, "
        "dairy free *",
        "milk",
    ),
    # Not tree nuts or peanuts.
    (
        "water chestnut, grape nut, tiger nut, kola nut, cola nut, betel nut, nut coconut, "
        "nut free, nut free *",
        "tree_nuts peanuts",
    ),
    ("monkey nut, chestnut mushroom", "tree_nuts"),
    # A named tree nut is not a peanut.
    (
        "pine nut, brazil nut, cashew nut, pecan nut, macadamia nut, hazel nut, pistachio nut, "
        "almond nut, candle nut, nut almond, nut walnut, nut pecan, nut cashew, nut hazelnut, "
        "nut pistachio, nut macadamia, nut brazilnut, nut pine, nut chestnut, nut beechnut, "
        "nut butternut, nut hickorynut, nut ginkgo, nut acorn",
        "peanuts",
    ),
    ("egg plant, egg free, egg free *, flax egg, chia egg", "eggs"),
    (
        ", ".join(f"{q} flour, flour {q}" for q in _GLUTEN_FREE_FLOURS.split(", "))
        + ", rice noodle, glass noodle, cellophane noodle, mung bean noodle, bean thread noodle, "
        "kelp noodle, sweet potato noodle, rice stick noodle, rice stick, rice vermicelli, "
        "rice vermicelli noodle, rice pasta, corn pasta, corn tortilla, maize tortilla, "
        "spanish tortilla, rice cake, rice porridge, corn porridge, cornmeal porridge, "
        "maize porridge, millet porridge, sorghum porridge, buckwheat porridge, quinoa porridge, "
        "pasta sauce, pizza sauce, a la pizza, poulet roti, ginger beer, ginger ale, root beer, "
        "ginger bread spice, gluten free, gluten free *, flourless *, no gluten, any gluten, "
        "without gluten",
        "gluten",
    ),
    ("pizza sauce, a la pizza", "milk"),
    (
        "beef tomato, lamb lettuce, lamb s lettuce, kidney bean, duck sauce, sauce duck, "
        "bean kidney, pigeon pea, chicken egg, duck egg, quail egg, goose egg, "
        "chicken of the wood, goat cheese, goat s cheese, cheese goat, goat milk, goat s milk, "
        "goat yogurt, goat butter, buffalo mozzarella, expressed from grated meat, buffalo milk, "
        "coconut meat, crab meat, lobster meat, clam meat, nut meat, walnut meat, pecan meat, "
        "fish meat, shrimp meat, prawn meat, crayfish meat, langoustine meat, mussel meat, "
        "oyster meat, scallop meat, squid meat, whelk meat, snail meat, conch meat, abalone meat, "
        "soy mince, quorn mince, poultry seasoning, meat free, meat free *, meatless *, "
        "vegetable suet, mince garlic, mince ginger, mince the garlic, mince the ginger, "
        "mince the onion, mince the shallot, tuna steak, salmon steak, fish steak, cod steak, "
        "halibut steak, cauliflower steak, celeriac steak, cabbage steak, mushroom steak, "
        "tofu steak, aubergine steak, burger bun, burger roll, hamburger bun, hamburger roll, "
        "roll hamburger, hot dog bun, hot dog roll",
        "meat",
    ),
    (
        "burger bun, burger roll, hamburger bun, hamburger roll, roll hamburger, hot dog bun, "
        "hot dog roll",
        "sulphites",
    ),
    ("romano pepper, romano bean", "milk rennet"),
    ("oyster mushroom, mushroom oyster, vegetable oyster, oyster cracker", "molluscs"),
    ("crab apple", "crustaceans"),
    ("madeira cake, port royal", "sulphites"),
    # Dough rolled "into a sausage".
    ("sausage shape, into a sausage, dough sausage", "meat gluten sulphites"),
    # Vegan / vegetarian products: the next word is free of animal products.
    ("vegan *", "meat fish shellfish dairy egg honey gelatin rennet"),
    ("vegetarian *, veggie *, plant based *", "meat fish shellfish gelatin rennet"),
    # Utensils and sizes say nothing about the food.
    (
        "fish slice, fish kettle, butter knife, egg slice, ice cream scoop, egg cup, egg timer, "
        "egg beater, egg poacher, cake tin, cake pan, cake stand, cake case, cake rack, loaf tin, "
        "loaf pan, bread pan, bread knife, bread board, muffin tin, muffin case, muffin cup, "
        "muffin liner, bun tin, pie dish, pie tin, pie plate, tart tin, tart pan, flan tin, "
        "flan dish, custard cup, pastry brush, pastry cutter, pastry bag, pastry wheel, "
        "pizza stone, pizza cutter, pizza pan, cheese grater, milk pan, cookie cutter, "
        "cookie sheet, biscuit cutter, biscuit tin, meat grinder, meat mallet, meat hammer, "
        "meat thermometer, meat tenderiser, meat tenderizer, meat fork, nut cracker, nut brown, "
        "puff up, * sized, * shaped, size of a *, size of a * *, size of an *, size of *, "
        "thickness of a *, thickness of a * *, as thick as a *, as thick as a * *",
        "*",
    ),
    # "Wrap" as a verb ("wrap in foil", "wrap and chill").
    (
        "wrap in, wrap it, wrap the, wrap them, wrap each, wrap tightly, wrap loosely, wrap well, "
        "wrap up, wrap around, wrap securely",
        "gluten",
    ),
)

_SPELLING = {
    "mollusk": "mollusc",
    "yoghurt": "yogurt",
    "yoghourt": "yogurt",
    "yogourt": "yogurt",
    "chili": "chilli",
    "chile": "chilli",
    "soya": "soy",
    "soyabean": "soybean",
    "gelatine": "gelatin",
    "gray": "grey",
    "eggplant": "aubergine",
    "catsup": "ketchup",
    "hazlenut": "hazelnut",
    "filbert": "hazelnut",
    "cobnut": "hazelnut",
    "barbeque": "barbecue",
    "bbq": "barbecue",
    "omelet": "omelette",
    "phyllo": "filo",
    "fillo": "filo",
    "pitta": "pita",
    "chapatti": "chapati",
    "lasagna": "lasagne",
    "fettucine": "fettuccine",
    "linguini": "linguine",
    "houmous": "hummus",
    "humous": "hummus",
    "hommus": "hummus",
    "hoummos": "hummus",
    "hummous": "hummus",
    "tahina": "tahini",
    "mozarella": "mozzarella",
    "sulfite": "sulphite",
    "sulfur": "sulphur",
    "sulfured": "sulphured",
    "metabisulfite": "metabisulphite",
    "ketjap": "kecap",
    "crawfish": "crayfish",
    "donut": "doughnut",
}
_IRREGULAR = {"loaves": "loaf", "geese": "goose", "calves": "calf", "knives": "knife"}
# Compound words read as two: saltfish = salt + fish, buttermilk, shortbread, cupcake...
_SUFFIXES = ("fish", "milk", "bread", "cake", "meat", "nut")
# ...but not these, whose last part isn't the food (a water chestnut is not a nut).
_NO_SPLIT = frozenset({"jellyfish", "starfish", "selfish", "elfish", "waterchestnut"})
# Letters NFKD doesn't decompose (chr(0x131) is the dotless i).
_LETTERS = str.maketrans(
    {"ø": "o", "œ": "oe", "æ": "ae", "ł": "l", "đ": "d", "ð": "d", "þ": "th", chr(0x131): "i"}
)
_TOKEN = re.compile(r"[a-z0-9]+")
# What may sit between two words without separating them: spaces, or one hyphen or apostrophe
# ("walnut-sized", "lamb's lettuce"). Anything else (comma, full stop, newline...) is a break.
_JOINERS = frozenset({"-", "'", chr(0x2019), chr(0x2018)})  # hyphen, straight and curly apostrophes


@dataclass(frozen=True, slots=True)
class _Phrase:
    words: tuple[str, ...]
    tags: FoodTags


@dataclass(frozen=True, slots=True)
class _Text:
    words: list[frozenset[str]]  # one set of forms per word (compounds split)
    breaks: frozenset[int]  # i in breaks: punctuation between words i-1 and i


_NONE = FoodTags()
_EVERYTHING = FoodTags(frozenset(Allergen), frozenset(AnimalTag))
_ALLERGEN_NAMES = frozenset(a.value for a in Allergen)


def _tags(spec: str) -> FoodTags:
    """'gluten milk meat' -> FoodTags (allergen names first: 'fish' is both)."""
    allergens: set[Allergen] = set()
    animal: set[AnimalTag] = set()
    for word in spec.split():
        if word in _ALLERGEN_NAMES:
            allergens.add(Allergen(word))
        else:
            animal.add(AnimalTag(word))
    return FoodTags(frozenset(allergens), frozenset(animal)).normalised()


def _phrases(table: tuple[tuple[str, str], ...]) -> tuple[_Phrase, ...]:
    out: list[_Phrase] = []
    for phrases, spec in table:
        tags = _EVERYTHING if spec == "*" else _tags(spec)
        out.extend(_Phrase(tuple(p.split()), tags) for p in phrases.split(", "))
    return tuple(out)


def _index(phrases: tuple[_Phrase, ...]) -> dict[str, tuple[_Phrase, ...]]:
    by_first: dict[str, list[_Phrase]] = {}
    for p in phrases:
        by_first.setdefault(p.words[0], []).append(p)
    return {k: tuple(v) for k, v in by_first.items()}


RULES = _phrases(_RULES)
EXCEPTIONS = _phrases(_EXCEPTIONS)
_RULE_INDEX = _index(RULES)
_EXCEPTION_INDEX = _index(EXCEPTIONS)
_VOCAB = frozenset(w for p in RULES + EXCEPTIONS for w in p.words)

_GLUTEN = _tags("gluten")
_SEAFOOD = _tags("fish crustaceans molluscs")
_MEAT_RECIPE_CATEGORIES = frozenset({"Beef", "Chicken", "Pork", "Lamb", "Goat"})


def forms(word: str) -> frozenset[str]:
    """The canonical forms a lower-case word may stand for: itself, its singulars (s/es, ies->y)
    and canonical spellings (yoghurt -> yogurt, chili -> chilli)."""
    out = {word, _IRREGULAR.get(word, word)}
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        out.add(word[:-1])
        if word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh", "o", "i")):
            out.add(word[:-2])
        if word.endswith("ies"):
            out.add(word[:-3] + "y")
    return frozenset(_SPELLING.get(f, f) for f in out)


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", text.casefold().translate(_LETTERS))
    return "".join(c for c in s if not unicodedata.combining(c))


def _text(text: str) -> _Text:
    """Text -> one set of forms per word, splitting compounds (saltfish -> salt fish), and where
    punctuation separates words."""
    s = _fold(text)
    words: list[frozenset[str]] = []
    breaks: set[int] = set()
    end = 0
    for m in _TOKEN.finditer(s):
        gap = s[end : m.start()]
        if words and gap.strip(" ") and gap not in _JOINERS:
            breaks.add(len(words))
        end = m.end()
        f = forms(m.group())
        words.extend(_split(f) if f.isdisjoint(_VOCAB) else [f])
    return _Text(words, frozenset(breaks))


def _split(f: frozenset[str]) -> list[frozenset[str]]:
    if f & _NO_SPLIT:
        return [f]
    for form in sorted(f):
        for suffix in _SUFFIXES:
            if form.endswith(suffix) and len(form) >= len(suffix) + 2:
                return [forms(form[: -len(suffix)]), frozenset({suffix})]
    return [f]


def _matches(
    words: list[frozenset[str]], index: dict[str, tuple[_Phrase, ...]]
) -> Iterator[tuple[int, int, FoodTags]]:
    for i, here in enumerate(words):
        candidates = {p for f in here for p in index.get(f, ())} | set(index.get("*", ()))
        for p in candidates:
            end = i + len(p.words)
            if end <= len(words) and all(
                w == "*" or w in words[i + k] for k, w in enumerate(p.words)
            ):
                yield i, end, p.tags


def _scan(text: _Text, *, across_punctuation: bool) -> FoodTags:
    """Union of rule matches, each minus the exceptions whose span contains it."""
    cuts = [
        (start, end, tags)
        for start, end, tags in _matches(text.words, _EXCEPTION_INDEX)
        if across_punctuation or not any(start < b < end for b in text.breaks)
    ]
    out = _NONE
    for start, end, tags in _matches(text.words, _RULE_INDEX):
        for cut_start, cut_end, cut in cuts:
            if cut_start <= start and end <= cut_end:
                tags = _minus(tags, cut)
        out |= tags
    return out


def _minus(tags: FoodTags, removed: FoodTags) -> FoodTags:
    return FoodTags(tags.allergens - removed.allergens, tags.animal - removed.animal)


def _has(words: list[frozenset[str]], phrase: str) -> bool:
    target = phrase.split()
    return any(
        all(w in words[i + k] for k, w in enumerate(target))
        for i in range(len(words) - len(target) + 1)
    )


# --- USDA category rules ---------------------------------------------------------------------

_MEAT_CATEGORIES = frozenset(
    {
        "Beef Products",
        "Pork Products",
        "Poultry Products",
        "Lamb, Veal, and Game Products",
        "Sausages and Luncheon Meats",
    }
)
_CRUSTACEAN_WORDS = frozenset(
    {"crustacean", "shrimp", "prawn", "crab", "lobster", "crayfish", "langoustine"}
)
_MOLLUSC_WORDS = frozenset(
    {
        "mollusc",
        "clam",
        "mussel",
        "oyster",
        "scallop",
        "squid",
        "calamari",
        "octopus",
        "cuttlefish",
        "snail",
        "whelk",
        "abalone",
        "conch",
    }
)
_GLUTEN_FREE_GRAINS = frozenset(
    {
        "rice",
        "corn",
        "maize",
        "buckwheat",
        "quinoa",
        "millet",
        "sorghum",
        "amaranth",
        "teff",
        "tapioca",
        "arrowroot",
        "cornstarch",
        "cornmeal",
        "cornflour",
        "hominy",
        "masa",
        "polenta",
        "grit",
        "grits",
        "cassava",
    }
)
_GLUTEN_GRAINS = frozenset(
    {
        "wheat",
        "barley",
        "rye",
        "oat",
        "oatmeal",
        "spelt",
        "semolina",
        "durum",
        "bulgur",
        "couscous",
        "triticale",
        "malt",
        "malted",
        "kamut",
        "farina",
        "einkorn",
        "emmer",
        "farro",
        "freekeh",
        "seitan",
        "gluten",
    }
)


def _union(words: list[frozenset[str]]) -> frozenset[str]:
    return frozenset(f for w in words for f in w)


def _category_tags(words: list[frozenset[str]], category: str | None) -> FoodTags:
    every = _union(words)
    first = words[0] if words else frozenset[str]()
    match category:
        case "Dairy and Egg Products":
            return _tags("eggs") if "egg" in first else _tags("milk")
        case "Finfish and Shellfish Products":
            tags = _NONE
            if every & _CRUSTACEAN_WORDS:
                tags |= _tags("crustaceans")
            if every & _MOLLUSC_WORDS:
                tags |= _tags("molluscs")
            if every & {"frog", "turtle", "alligator"}:
                tags |= _tags("meat")
            return tags if tags != _NONE else _tags("fish")
        case c if c in _MEAT_CATEGORIES:
            return _tags("meat")
        case "Nut and Seed Products":
            tags = _NONE
            if "nut" in first and "coconut" not in every:
                tags |= _tags("tree_nuts")
            if "mixed" in every and "nut" in every:
                tags |= _tags("peanuts")
            if "sesame" in every:
                tags |= _tags("sesame")
            return tags
        case "Legumes and Legume Products":
            tags = _NONE
            if every & {"peanut", "groundnut"}:
                tags |= _tags("peanuts")
            if every & {"soy", "soybean", "tofu", "edamame", "tempeh", "miso", "natto"}:
                tags |= _tags("soy")
            if every & {"lupin", "lupine", "lupini"}:
                tags |= _tags("lupin")
            return tags
        case "Cereal Grains and Pasta" | "Baked Products" | "Breakfast Cereals":
            return _GLUTEN
        case "Soups, Sauces, and Gravies":
            stocks = {"stock", "broth", "bouillon", "soup", "gravy"}
            return _tags("celery") if every & stocks else _NONE
        case _:
            return _NONE


def _gluten_free(words: list[frozenset[str]], category: str | None) -> bool:
    """Whether a cereal-like USDA food is free of gluten, overriding generic product words
    (pasta, noodle, tortilla). Baked goods mix flours, so only an explicit 'gluten-free' or a
    corn tortilla/tostada counts there; breakfast cereals also need no malt or flavouring."""
    if _has(words, "gluten free"):
        return True
    every = _union(words)
    plain_grain = bool(every & _GLUTEN_FREE_GRAINS) and not every & _GLUTEN_GRAINS
    match category:
        case "Cereal Grains and Pasta":
            return plain_grain
        case "Breakfast Cereals":
            return plain_grain and not every & {"ready", "flavor", "flavored", "flavour"}
        case "Baked Products":
            first = words[0] if words else frozenset[str]()
            return bool(first & {"tortilla", "tostada"}) and plain_grain and "flour" not in every
        case _:
            return False
