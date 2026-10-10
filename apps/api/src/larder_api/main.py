from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from larder_api import __version__, health
from larder_api.resources import lifespan
from larder_api.routers import chat, foods, pantry, plans, profile, recipes
from larder_api.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Larder API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(profile.router)
    app.include_router(profile.allergens_router)
    app.include_router(foods.router)
    app.include_router(pantry.router)
    app.include_router(plans.router)
    app.include_router(recipes.router)
    app.include_router(chat.router)
    return app


app = create_app()
