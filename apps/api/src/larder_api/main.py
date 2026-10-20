from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from larder_api import __version__, health
from larder_api.chat.gate import ChatRefused, problem_response
from larder_api.resources import lifespan
from larder_api.routers import (
    chat,
    diary,
    foods,
    pantry,
    plans,
    profile,
    push,
    receipts,
    recipes,
    share,
    shopping,
)
from larder_api.settings import get_settings
from larder_core.brand import APP_NAME


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=f"{APP_NAME} API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ChatRefused, problem_response)  # the chat gate's JSON 4xx
    app.include_router(health.router)
    app.include_router(profile.router)
    app.include_router(profile.allergens_router)
    app.include_router(foods.router)
    app.include_router(receipts.router)
    app.include_router(pantry.router)
    app.include_router(plans.router)
    app.include_router(shopping.router)
    app.include_router(recipes.router)
    app.include_router(chat.router)
    app.include_router(diary.router)
    app.include_router(push.router)
    app.include_router(share.router)
    return app


app = create_app()
