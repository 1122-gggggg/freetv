from __future__ import annotations

import pytest

from app.discovery.advertiser import SERVICE_TYPE, ServiceAdvertiser


@pytest.mark.anyio
async def test_service_advertiser_lifecycle():
    advertiser = ServiceAdvertiser(port=8765, name="Test TV Box")
    assert not advertiser.is_running
    assert SERVICE_TYPE == "_pctvbox._tcp.local."

    await advertiser.start()
    assert advertiser.is_running

    # idempotent start
    await advertiser.start()
    assert advertiser.is_running

    await advertiser.stop()
    assert not advertiser.is_running

    # idempotent stop
    await advertiser.stop()
    assert not advertiser.is_running
