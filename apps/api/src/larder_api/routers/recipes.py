"""Recipe catalogue (public data: TheMealDB + curated recipes)."""

from fastapi import APIRouter

from larder_api.db import Session
from larder_api.schemas import RecipeDetail

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get("/{recipe_id}", operation_id="getRecipe")
async def get_recipe(recipe_id: int, session: Session) -> RecipeDetail:
    raise NotImplementedError
