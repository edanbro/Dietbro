"""Where a pantry item is kept: the user's choice, else where that food usually is."""

from typing import cast

from larder_api.schemas import Storage
from larder_core.shelf_life import storage_for
from larder_db.models import PantryItem


def kept_in(item: PantryItem) -> Storage:
    """Fridge, freezer or cupboard (`item.food` must be loaded)."""
    if item.storage is not None:
        return cast(Storage, item.storage)
    return storage_for(item.food.description, item.food.category)
