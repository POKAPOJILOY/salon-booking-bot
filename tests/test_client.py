from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from client import confirm_booking, start_reinvite
from database import LOCAL_TZ, SalonDB


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    yield database, service_id
    database.close()


def fsm(user_id=100):
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


def callback(data, user_id=100):
    message = SimpleNamespace(answer=AsyncMock(), edit_text=AsyncMock())
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id, full_name="Анна"),
        message=message,
        answer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_confirmation_creates_booking_and_notifies_master(db):
    database, service_id = db
    start = database.next_slots(service_id, limit=1)[0]
    state = fsm()
    await state.set_data({
        "service_id": service_id,
        "start_at": start.isoformat(),
        "name": "Анна",
        "phone": "+79990000000",
        "source": "link",
        "reinvited_from_id": None,
    })
    query = callback("confirm")
    bot = SimpleNamespace(send_message=AsyncMock())
    await confirm_booking(query, state, database, bot, 1)
    booking = database.get_booking(database.conn.execute("SELECT id FROM bookings").fetchone()[0])
    assert booking["source"] == "link"
    assert booking["client_name"] == "Анна"
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == 1
    query.message.edit_text.assert_awaited_once()
    assert (await state.get_data()) == {}


@pytest.mark.asyncio
async def test_reinvite_skips_service_and_reuses_saved_client(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = database.next_slots(service_id, limit=1)[0]
    old_id = database.create_booking(client_id, service_id, start)
    database.conn.execute("UPDATE bookings SET status = 'done' WHERE id = ?", (old_id,))
    state = fsm()
    query = callback(f"reinvite:{old_id}")
    await start_reinvite(query, state, database)
    data = await state.get_data()
    assert data["service_id"] == service_id
    assert data["client_id"] == client_id
    assert data["name"] == "Анна"
    assert data["phone"] == "+79990000000"
    assert data["source"] == "reinvite"
    assert data["reinvited_from_id"] == old_id
    query.message.edit_text.assert_awaited_once()
