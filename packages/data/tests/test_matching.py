import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from larder_data import embeddings, matching
from larder_data.matching import Candidate, best, rewrite, score
from larder_db.models import Food

from .fakes import FakeEmbedder


def cand(
    food_id: int, description: str, *, similarity: float = 0.8, has_macros: bool = True
) -> Candidate:
    return Candidate(food_id, description, None, similarity, has_macros, portions=1)


@pytest.mark.parametrize(
    ("query", "right", "wrong"),
    [
        ("egg", "Egg, whole, raw, fresh", "Bread, egg"),
        ("almond", "Nuts, almonds", "Flour, almond"),
        ("walnut", "Nuts, walnuts, english", "Oil, walnut"),
        ("lemon", "Lemons, raw, without peel", "Lemon juice, raw"),
        ("lentil", "Lentils, raw", "SMART SOUP, French Lentil"),
        ("sour cream", "Cream, sour, cultured", "Sour cream, fat free"),
        ("dried cherry", "Cherries, tart, dried, sweetened", "Cherries, sweet, raw"),
    ],
)
def test_score_prefers_the_plain_ingredient(query: str, right: str, wrong: str) -> None:
    # Equal embedding similarity: the lexical rules alone must pick the right food.
    assert score(query, cand(1, right)) > score(query, cand(2, wrong))


def test_score_penalises_missing_macros() -> None:
    assert score("olive oil", cand(1, "Oil, olive, salad or cooking")) > score(
        "olive oil", cand(2, "Oil, olive, salad or cooking", has_macros=False)
    )


def test_best_returns_none_for_no_candidates() -> None:
    assert best("x", []) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("aubergine", "eggplant"),
        ("baby courgette", "baby zucchini"),
        ("lamb mince", "lamb ground"),
        ("raw king prawn", "raw shrimp"),
        ("chicken stock cube", "chicken bouillon dry"),
        ("onion", "onion"),
    ],
)
def test_rewrite(name: str, expected: str) -> None:
    assert rewrite(name) == expected


async def test_hybrid_retrieval_finds_lexical_matches(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Food(id=1, description="Spices, paprika", data_type="sr_legacy", kcal=282),
            Food(
                id=2, description="Tofu, dried-frozen (koyadofu)", data_type="sr_legacy", kcal=480
            ),
            Food(
                id=3, description="Fast food, burger", data_type="sr_legacy", category="Fast Foods"
            ),
        ]
    )
    await db_session.commit()
    embedder = FakeEmbedder()
    await embeddings.embed_foods(db_session, embedder)

    [vector] = embedder.embed(["paprika"])
    found = await matching.rank(db_session, "paprika", vector)

    assert found is not None
    assert found[0].description == "Spices, paprika"
    ids = {c.food_id for c in await matching.candidates(db_session, "burger", vector)}
    assert 3 not in ids  # excluded category
