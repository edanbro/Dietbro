"""Build a tiny FDC-shaped CSV zip for tests."""

import csv
import io
import zipfile
from pathlib import Path

TABLES: dict[str, list[dict[str, str]]] = {
    "food_category": [
        {"id": "11", "code": "1100", "description": "Vegetables and Vegetable Products"},
        {"id": "4", "code": "0400", "description": "Fats and Oils"},
    ],
    "measure_unit": [
        {"id": "1000", "name": "cup"},
        {"id": "1001", "name": "tablespoon"},
        {"id": "9999", "name": "undetermined"},
    ],
    "food": [
        {
            "fdc_id": "170000",
            "data_type": "sr_legacy_food",
            "description": "Onions, raw",
            "food_category_id": "11",
        },
        {
            "fdc_id": "171413",
            "data_type": "sr_legacy_food",
            "description": "Oil, olive, salad or cooking",
            "food_category_id": "4",
        },
        {
            "fdc_id": "999999",
            "data_type": "sample_food",
            "description": "ONION SAMPLE",
            "food_category_id": "11",
        },
    ],
    "food_nutrient": [
        {"fdc_id": "170000", "nutrient_id": "1008", "amount": "40"},
        {"fdc_id": "170000", "nutrient_id": "1003", "amount": "1.1"},
        {"fdc_id": "170000", "nutrient_id": "1004", "amount": "0.1"},
        {"fdc_id": "170000", "nutrient_id": "1005", "amount": "9.34"},
        {"fdc_id": "170000", "nutrient_id": "1093", "amount": "4"},
        {"fdc_id": "171413", "nutrient_id": "1003", "amount": "0"},
        {"fdc_id": "171413", "nutrient_id": "1004", "amount": "100"},
        {"fdc_id": "171413", "nutrient_id": "1005", "amount": "0"},
        {"fdc_id": "999999", "nutrient_id": "1008", "amount": "1"},
    ],
    "food_portion": [
        {
            "fdc_id": "170000",
            "amount": "1",
            "measure_unit_id": "9999",
            "portion_description": "",
            "modifier": "cup, chopped",
            "gram_weight": "160",
        },
        {
            "fdc_id": "170000",
            "amount": "1",
            "measure_unit_id": "9999",
            "portion_description": "",
            "modifier": 'medium (2-1/2" dia)',
            "gram_weight": "110",
        },
        {
            "fdc_id": "170000",
            "amount": "1",
            "measure_unit_id": "9999",
            "portion_description": "",
            "modifier": "large",
            "gram_weight": "150",
        },
        {
            "fdc_id": "171413",
            "amount": "1",
            "measure_unit_id": "1001",
            "portion_description": "",
            "modifier": "",
            "gram_weight": "13.5",
        },
        {
            "fdc_id": "171413",
            "amount": "1",
            "measure_unit_id": "9999",
            "portion_description": "",
            "modifier": "fl oz",
            "gram_weight": "",
        },
    ],
}


def write_fdc_zip(path: Path, prefix: str = "FoodData_Central_sr_legacy_food_csv_2018-04") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for table, rows in TABLES.items():
            buf = io.StringIO()
            fields = sorted({k for r in rows for k in r})
            writer = csv.DictWriter(buf, fieldnames=fields, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rows)
            zf.writestr(f"{prefix}/{table}.csv", buf.getvalue())
    return path
