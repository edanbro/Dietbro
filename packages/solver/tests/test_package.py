import importlib

import larder_solver


def test_public_api_is_re_exported() -> None:
    sources = {
        "problem": ["Problem", "Plan", "Meal", "Recipe", "SlotSpec", "check_problem", "Status"],
        "solve": ["solve"],
        "baseline": ["greedy"],
        "diagnose": ["diagnose"],
        "validate": [
            "validate",
            "hard",
            "Violation",
            "Code",
            "SAFETY_CODES",
            "STRUCTURAL_CODES",
            "HARD_FILTER_CODES",
        ],
        "metrics": ["score", "Score"],
        "shopping": ["shopping_list", "ShoppingList", "ShoppingLine"],
    }
    for module, names in sources.items():
        source = importlib.import_module(f"larder_solver.{module}")
        for name in names:
            assert getattr(larder_solver, name) is getattr(source, name), name
            assert name in larder_solver.__all__
    assert all(hasattr(larder_solver, name) for name in larder_solver.__all__)
    problem = importlib.import_module("larder_solver.problem")
    assert set(problem.__all__) <= set(larder_solver.__all__)
