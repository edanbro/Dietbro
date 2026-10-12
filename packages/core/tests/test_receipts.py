"""Receipt text -> item lines (larder_core.receipts): junk filtering, prices, quantity tokens,
abbreviations, follow-on quantity/weight lines, and amounts from USDA portions."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_core.quantities import Portion
from larder_core.receipts import (
    Amount,
    ReceiptItem,
    clean_name,
    estimate_amount,
    load_receipt_foods,
    match_names,
    parse_receipt,
)
from larder_core.units import Measure

EGG = [Portion(1, "small", None, 38), Portion(1, "large", None, 50), Portion(1, "medium", None, 44)]
ONION = [Portion(1, "cup", "chopped", 160), Portion(1, "medium", None, 110)]
MILK = [Portion(1, "cup", None, 244), Portion(1, "fl_oz", None, 30.5)]
FLOUR = [Portion(1, "cup", None, 125)]


def one(line: str) -> ReceiptItem:
    items = parse_receipt(line)
    assert len(items) == 1, items
    return items[0]


# --- lines ------------------------------------------------------------------------------------


def test_drops_headers_totals_payments_and_savings() -> None:
    text = """TESCO
Tesco Stores Ltd
VAT No: GB 123 4567 89
TSC CHKN BRST FLLTS 650G        £4.75
CLUBCARD PRICE                 -£0.50
KROGER SAVINGS                  0.50-
CARRIER BAG                     £0.10
SUBTOTAL                       £11.43
TOTAL                          £11.43
12 BALANCE DUE                  12.84
VISA                           £11.43
CHANGE DUE                      £0.00
VAT A  0%                         0.00
T = MN TAX 0.00000 on $0.00     $0.00
Delivery charge                  1.50
APPROVED - PURCHASE AMOUNT: $72.43
CLUBCARD POINTS THIS VISIT          11
THANK YOU FOR SHOPPING AT TESCO"""
    items = parse_receipt(text)

    assert [i.name for i in items] == ["chicken breast fillet"]
    assert items[0].raw == "TSC CHKN BRST FLLTS 650G        £4.75"


def test_price_is_read_and_stripped() -> None:
    item = one("BANANAS LOOSE  £0.68")

    assert item.name == "banana"
    assert item.price_minor == 68
    assert item.count == 1
    assert item.size is None
    assert one("WILD SALMON FILLET   $13.98").price_minor == 1398
    assert one("Mushrooms 300g   0.89 A").price_minor == 89


@pytest.mark.parametrize(
    ("line", "name", "size"),
    [
        ("TESCO SEMI SKMD MILK 4PT   £1.45", "semi skimmed milk", Measure(4, "pint")),
        ("JS RED ONIONS 1KG   0.95", "red onion", Measure(1, "kg")),
        ("M SEMI SKIMMED MILK 2.272L   1.45", "semi skimmed milk", Measure(2.272, "l")),
        ("ESS DOUBLE CREAM 300ML   1.30", "double cream", Measure(300, "ml")),
        ("GV SHRD CHEDDAR 8OZ   2.18 N", "shredded cheddar", Measure(8, "oz")),
        ("RUSSET POTATO 5LB   3.47 N", "russet potato", Measure(5, "lb")),
        ("ASDA Semi Skimmed Milk 4 Pints   2.70", "semi skimmed milk", Measure(4, "pint")),
        ("ATLANTIC SALMON FILLET 1 LB   11.99", "atlantic salmon fillet", Measure(1, "lb")),
    ],
)
def test_size_tokens(line: str, name: str, size: Measure) -> None:
    item = one(line)

    assert item.name == name
    assert item.size == size


@pytest.mark.parametrize(
    ("line", "ml"),
    [
        ("GV 2% MILK GAL   3.18 N", 3785.4),
        ("365 WHOLE MILK HALF GAL   $3.29", 1892.7),
        ("KS 2% MILK 2 GAL   5.49", 7570.8),
        ("WHOLE MILK GALLON   2.89  F", 3785.4),
    ],
)
def test_gallons_become_millilitres(line: str, ml: float) -> None:
    size = one(line).size

    assert size is not None
    assert size.unit == "ml"
    assert size.quantity == pytest.approx(ml, abs=0.1)


@pytest.mark.parametrize(
    ("line", "pieces"),
    [
        ("TSC FR LGE EGGS 6PK   £2.10", 6),
        ("LG BROWN EGGS 12CT   3.47 N", 12),
        ("CO OP FREE RANGE EGGS 6   1.85", 6),
        ("EGGS FREE RANGE BROWN 1 DOZ   3.79", 12),
        ("WR AVOCADOS RIPE 2S   2.00", 2),
        ("Gala Apples 6pk   1.19 A", 6),
    ],
)
def test_piece_counts(line: str, pieces: float) -> None:
    item = one(line)

    assert item.pieces == pieces
    assert item.size is None


def test_multipack_of_sizes() -> None:
    beans = one("ASDA BAKED BEANS 4X420G   1.75")
    salmon = one("Salmon Fillets 2x120g   3.49 A")

    assert (beans.name, beans.pieces, beans.size) == ("baked bean", 4, Measure(420, "g"))
    assert (salmon.pieces, salmon.size) == (2, Measure(120, "g"))


def test_a_pack_count_next_to_a_size_is_not_a_multiplier() -> None:
    steaks = one("BRITISH BEEF STEAKS 2PK 454G   7.00")

    assert (steaks.pieces, steaks.size) == (None, Measure(454, "g"))


def test_slices_and_wedges_are_not_one_of_the_thing() -> None:
    onion = [*ONION, Portion(1, "slice", 'medium (1/8" thick)', 14)]

    assert estimate_amount(ReceiptItem(raw="", name="onion", pieces=3), onion, "onion", None) == (
        Amount(3, "medium", 330, approx=False)
    )


def test_leading_multiplier_and_quantity_column() -> None:
    toms = one("2 x TESCO CHOPPED TOMS 400G   £1.10")
    column = one("3    ASDA Chopped Tomatoes 400g   1.65")

    assert (toms.name, toms.count, toms.size) == ("chopped tomato", 2, Measure(400, "g"))
    assert (column.name, column.count) == ("chopped tomato", 3)


def test_quantity_line_applies_to_the_item_above() -> None:
    items = parse_receipt("LEEKS LOOSE   0.92\n  2 @ 0.46\nPlum Tomatoes 400g  1.10 A\n2 x 0.55")

    assert [(i.name, i.count) for i in items] == [("leek", 2), ("plum tomato", 2)]
    assert items[0].raw == "LEEKS LOOSE   0.92 | 2 @ 0.46"


def test_weight_line_completes_a_name_line_or_sizes_the_item_above() -> None:
    text = """BROCCOLI LOOSE
  0.352 kg @ £1.10/kg           £0.39
BANANAS               000000004011 KF   1.24 N
  2.10 lb @ 0.59 /lb
CARROTS LOOSE                    0.24
   0.400 kg @ £0.60/kg"""
    items = parse_receipt(text)

    assert [(i.name, i.size) for i in items] == [
        ("broccoli", Measure(0.352, "kg")),
        ("banana", Measure(2.10, "lb")),
        ("carrot", Measure(0.4, "kg")),
    ]
    assert items[0].price_minor == 39


def test_name_line_without_a_price_or_weight_is_dropped() -> None:
    assert parse_receipt("Market Street\nwww.example.co.uk\nGARLIC   0.30") == [
        ReceiptItem(raw="GARLIC   0.30", name="garlic", price_minor=30)
    ]


def test_item_codes_flags_and_store_brands_are_removed() -> None:
    assert one("  812345 Skimmed Milk 4 Pints      1.15 A").name == "skimmed milk"
    assert one("E   123456  KS ORG EGGS 24CT          7.99").name == "egg"
    assert one("212345680  GG WHITE BREAD 20OZ  NF  $1.39").name == "white bread"
    assert one("CHKN BRST BNLS SKNLS  002280010203 F    9.87 N").name == "chicken breast"


def test_common_ocr_confusions() -> None:
    cheddar = one("KRO SHRP CHEDDAR 80Z  2.29 B")
    beans = one("SIG BLACK BEANS 15.50Z  1.29")

    assert (cheddar.name, cheddar.size) == ("sharp cheddar", Measure(8, "oz"))
    assert beans.size == Measure(15.5, "oz")
    assert one("KR0 LG EGGS 12CT  2.49 B").name == "egg"
    assert parse_receipt("You \u0160aved  1.20") == []


def test_storage_hints() -> None:
    assert one("M FROZEN PEAS 1KG   1.30").storage == "frozen"
    assert one("TSC KIDNEY BEANS 400G   £0.50").storage is None
    assert one("CANNED BLACK BEANS 15OZ   0.65").storage == "ambient"
    assert one("2 x TINNED TOM 400G   1.10").storage == "ambient"


def test_size_grade_is_kept() -> None:
    assert one("TSC FR LGE EGGS 6PK   £2.10").grade == "large"
    assert one("ASDA MED FREE RANGE EGGS 12   2.65").grade == "medium"
    assert one("BANANAS   0.79").grade is None


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("CHKN BRST FLLTS", "chicken breast fillet"),
        ("SEMI SKMD MILK", "semi skimmed milk"),
        ("GV 2% MILK", "reduced fat milk"),
        ("KRO SHRP CHEDDAR", "sharp cheddar"),
        ("ORG BABY SPINACH", "baby spinach"),
        ("TSC MAT CHEDDAR", "mature cheddar"),
        ("JS GREEK STYLE YOG", "greek style yogurt"),
        ("WARBURTONS WHOLEMEAL", "wholemeal bread"),
        ("TSC VEG OIL", "vegetable oil"),
        ("GRND BEEF 80/20", "ground beef"),
        ("TSC LEAN STEAK MINCE 5%", "steak mince"),
    ],
)
def test_clean_name(raw: str, name: str) -> None:
    assert clean_name(raw) == name


def test_match_names_go_from_whole_name_to_shorter_phrases_rightmost_first() -> None:
    assert match_names("chicken breast fillet") == [
        "chicken breast fillet",
        "breast fillet",
        "chicken breast",
        "fillet",
        "breast",
        "chicken",
    ]
    assert match_names("milk") == ["milk"]
    assert match_names("") == []


@given(st.text(max_size=400))
def test_never_raises(text: str) -> None:
    for item in parse_receipt(text):
        assert item.name
        assert item.count > 0


# --- amounts ----------------------------------------------------------------------------------


def test_mass_amounts_keep_metric_units() -> None:
    item = ReceiptItem(raw="", name="flour", size=Measure(1.5, "kg"))

    assert estimate_amount(item, FLOUR, "flour", None) == Amount(1.5, "kg", 1500, approx=False)
    two = ReceiptItem(raw="", name="tomato", count=2, size=Measure(400, "g"))
    assert estimate_amount(two, [], "tomato", None) == Amount(800, "g", 800, approx=False)


def test_imperial_mass_becomes_grams() -> None:
    item = ReceiptItem(raw="", name="cheddar", size=Measure(8, "oz"))

    amount = estimate_amount(item, [], "cheese", None)

    assert (amount.quantity, amount.unit, amount.approx) == (227, "g", False)
    assert amount.grams == pytest.approx(226.8, abs=0.1)


def test_volumes_use_density() -> None:
    item = ReceiptItem(raw="", name="milk", size=Measure(4, "pint"))

    amount = estimate_amount(item, MILK, "milk", None)

    assert (amount.quantity, amount.unit) == (2273, "ml")
    assert amount.grams == pytest.approx(2273 * 244 / 240, rel=0.01)


def test_pieces_use_the_foods_count_portion_and_grade() -> None:
    large = ReceiptItem(raw="", name="egg", pieces=6, grade="large")
    plain = ReceiptItem(raw="", name="egg", pieces=12)

    assert estimate_amount(large, EGG, "egg", None) == Amount(6, "large", 300, approx=False)
    assert estimate_amount(plain, EGG, "egg", None) == Amount(12, "medium", 528, approx=False)


def test_packs_of_sizes_multiply() -> None:
    item = ReceiptItem(raw="", name="baked bean", pieces=4, size=Measure(420, "g"))

    assert estimate_amount(item, [], "beans", None) == Amount(1680, "g", 1680, approx=False)


def test_unknown_size_is_one_typical_portion_flagged_approx() -> None:
    onion = ReceiptItem(raw="", name="onion")
    leeks = ReceiptItem(raw="", name="leek", count=2)
    milk = ReceiptItem(raw="", name="milk")

    assert estimate_amount(onion, ONION, "onion", None) == Amount(1, "medium", 110, approx=True)
    assert estimate_amount(leeks, [], "leek", None) == Amount(200, "g", 200, approx=True)
    assert estimate_amount(milk, MILK, "milk", None) == Amount(244, "g", 244, approx=True)


def test_receipt_vocabulary_names_are_cleaned_names() -> None:
    table = load_receipt_foods()

    assert table["semi skimmed milk"] == 171267
    for name in table:
        assert name == clean_name(name), name
