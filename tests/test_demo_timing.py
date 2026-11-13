from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import demo
from database import SalonDB


@pytest.mark.asyncio
async def test_demo_notification_and_reminder_are_10_and_20_seconds(monkeypatch):
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "09:00", "20:00", None, None)
    client_id = database.upsert_client(1, "Анна (демо)", "+79990000000")
    start = database.next_slots(service_id, limit=1)[0]
    booking_id = database.create_booking(client_id, service_id, start)
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(demo.asyncio, "sleep", sleep)
    bot = SimpleNamespace(send_message=AsyncMock(), __call__=AsyncMock())
    await demo._future_notifications(bot, database, 1, booking_id)
    assert sleeps == [10, 10]
    assert database.get_booking(booking_id)["reminder24_sent"] == 1
    database.close()
