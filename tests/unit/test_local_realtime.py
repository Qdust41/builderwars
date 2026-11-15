from __future__ import annotations

import asyncio
import json
import threading

from api.local_realtime import LocalRealtimeHub
from application.realtime import RealtimeEvent, RealtimeEventType


def _event(device_id: str) -> RealtimeEvent:
    return RealtimeEvent(
        type=RealtimeEventType.DEVICE_LOG, project_id="prj_1", device_id=device_id, data={"n": 1}
    )


def test_hub_delivers_events_from_other_threads_to_channel_subscribers() -> None:
    hub = LocalRealtimeHub()

    async def scenario() -> list[str]:
        mine = _event("dev_a")
        with hub.subscribe(mine.channel) as queue:
            thread = threading.Thread(
                target=lambda: (hub.publish(_event("dev_b")), hub.publish(mine))
            )
            thread.start()
            thread.join()
            data = await asyncio.wait_for(queue.get(), 1)
            assert queue.empty()  # dev_b's event went to a different channel
            return [json.loads(data)["device_id"]]

    assert asyncio.run(scenario()) == ["dev_a"]
    # Subscriptions are cleaned up; publishing with nobody listening is fine.
    hub.publish(_event("dev_a"))
    assert len(hub.published) == 3
