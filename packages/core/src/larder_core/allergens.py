"""Allergen vocabulary: the 14 allergens EU/UK food law requires labelling (a superset of the
US "big 9"). Allergies are hard constraints; mapping allergens to USDA foods lands with the
solver (M3)."""

from enum import StrEnum


class Allergen(StrEnum):
    CELERY = "celery"
    GLUTEN = "gluten"  # cereals containing gluten
    CRUSTACEANS = "crustaceans"
    EGGS = "eggs"
    FISH = "fish"
    LUPIN = "lupin"
    MILK = "milk"
    MOLLUSCS = "molluscs"
    MUSTARD = "mustard"
    TREE_NUTS = "tree_nuts"
    PEANUTS = "peanuts"
    SESAME = "sesame"
    SOY = "soy"
    SULPHITES = "sulphites"


LABELS: dict[Allergen, str] = {
    Allergen.CELERY: "Celery",
    Allergen.GLUTEN: "Gluten (wheat, rye, barley, oats)",
    Allergen.CRUSTACEANS: "Crustaceans (prawns, crab, lobster)",
    Allergen.EGGS: "Eggs",
    Allergen.FISH: "Fish",
    Allergen.LUPIN: "Lupin",
    Allergen.MILK: "Milk",
    Allergen.MOLLUSCS: "Molluscs (mussels, squid, oysters)",
    Allergen.MUSTARD: "Mustard",
    Allergen.TREE_NUTS: "Tree nuts (almonds, walnuts, cashews…)",
    Allergen.PEANUTS: "Peanuts",
    Allergen.SESAME: "Sesame",
    Allergen.SOY: "Soy",
    Allergen.SULPHITES: "Sulphites",
}
