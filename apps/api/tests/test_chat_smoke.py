"""`larder-llm-smoke` with a scripted model in place of Claude: the real run needs a key, but its
plumbing (user, plan, gate, turns, costs, safety check, clean-up) is checked here."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import smoke
from larder_api.chat.scope import Models
from larder_api.settings import Settings
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.fake import ScriptedChatModel, say


@pytest.mark.usefixtures("menu")
async def test_the_smoke_run_talks_checks_and_cleans_up(
    migrated_database_url: str,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings.model_validate(
        {"database_url": migrated_database_url, "anthropic_api_key": "test", "planner": "greedy"}
    )
    replies = ["Spicy tonight.", "Logged the pizza.", "Skipped.", "Swapped Friday."]
    chat = ScriptedChatModel([say(text) for text in replies])  # strict: checks every replay
    monkeypatch.setattr(smoke, "get_settings", lambda: settings)

    def models(_: Settings) -> Models:
        return Models(chat=chat)

    monkeypatch.setattr(smoke, "get_models", models)

    code = await smoke.run(keep=False)

    out = capsys.readouterr().out
    assert code == 0, out
    assert out.count("[done]") == len(smoke.TURNS) == len(chat.requests)
    assert all(text in out for text in replies)
    assert "OK" in out
    async with make_sessionmaker(db_engine)() as session:
        users = await session.scalar(select(func.count(db.User.id)))
        calls = await session.scalar(select(func.count(db.LlmCall.id)))
    assert (users, calls) == (0, 0)  # the throwaway user and everything it made are gone


async def test_without_a_key_the_smoke_run_stops_at_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(smoke, "get_settings", lambda: Settings.model_validate({}))

    assert await smoke.run(keep=False) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out
