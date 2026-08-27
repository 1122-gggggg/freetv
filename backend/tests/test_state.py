from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.protocol import NetflixContext, NetflixInputKind, NetflixStage
from app.state import ActiveApp, ControllerState, StateStore


@pytest.mark.parametrize(
    "changes",
    [
        {"volume": 999},
        {"active_app": "invalid"},
    ],
)
def test_update_rejects_invalid_changes_without_corrupting_state(
    changes: dict[str, object],
) -> None:
    async def scenario() -> None:
        initial = ControllerState(active_app=ActiveApp.NETFLIX, volume=35)
        store = StateStore(initial)

        with pytest.raises(ValidationError):
            await store.update(**changes)

        assert await store.snapshot() == initial

    asyncio.run(scenario())


def test_update_validates_and_stores_normal_changes() -> None:
    async def scenario() -> None:
        store = StateStore()

        updated = await store.update(active_app="browser", volume=75, muted=True)

        assert updated.active_app is ActiveApp.BROWSER
        assert updated.volume == 75
        assert updated.muted is True
        assert await store.snapshot() == updated

    asyncio.run(scenario())


def test_netflix_context_round_trips_to_wire_and_can_be_cleared() -> None:
    async def scenario() -> None:
        context = NetflixContext(
            stage=NetflixStage.BROWSE,
            input_kind=NetflixInputKind.NONE,
            focused_title="Example",
        )
        store = StateStore()

        updated = await store.update(
            active_app=ActiveApp.NETFLIX,
            netflix_context=context,
        )
        assert updated.to_wire().netflix_context == context
        assert updated.to_wire().model_dump(mode="json")["netflix_context"] == {
            "stage": "browse",
            "input_kind": "none",
            "has_error": False,
            "can_submit": False,
            "focused_title": "Example",
        }

        cleared = await store.update(netflix_context=None)
        assert cleared.to_wire().netflix_context is None
        assert cleared.to_wire().model_dump(mode="json")["netflix_context"] is None

    asyncio.run(scenario())
