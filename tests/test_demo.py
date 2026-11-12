from datetime import timedelta

import pytest

from database import SalonDB, utc_now
from demo import create_demo_data
from scheduler import process_pending


@pytest.mark.asyncio
async def test_demo_creates_independent_visits_and_reinvites_after_60_seconds(tmp_path):
    database = SalonDB(tmp_path / "demo.db", master_id=1)
    now = utc_now()
    future_id, completed_id = create_demo_data(database, 1, now=now)
    future = database.get_booking(future_id)
    completed = database.get_booking(completed_id)
    assert future["status"] == "active"
    assert completed["status"] == "done"
    assert future["client_id"] != completed["client_id"]
    assert future["tg_id"] == completed["tg_id"] == 1
    assert future["start_at"] > future["created_at"]
    assert database.get_master()["demo_mode"] == 1
    sent = []

    async def send(bot, booking):
        sent.append(booking["id"])
        return True

    await process_pending(object(), database, 1, now=now + timedelta(seconds=59), reinvite_sender=send)
    assert sent == []
    await process_pending(object(), database, 1, now=now + timedelta(seconds=61), reinvite_sender=send)
    assert sent == [completed_id]
    database.close()
