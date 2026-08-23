from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

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
