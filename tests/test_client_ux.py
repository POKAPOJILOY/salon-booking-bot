from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from client import client_start, my_bookings
from database import SalonDB


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    yield database, service_id
    database.close()


@pytest.mark.asyncio
async def test_start_shows_persistent_client_menu(db):
    database, service_id = db
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=100, user_id=100))
    await client_start(message, state, database, 1)
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert [[button.text for button in row] for row in markup.keyboard] == [["📝 Записаться", "📋 Мои записи"]]


@pytest.mark.asyncio
async def test_my_bookings_lists_active_record_with_actions(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = database.next_slots(service_id, limit=1)[0]
    database.create_booking(client_id, service_id, start)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )
    await my_bookings(message, database)
    text = message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert "Анна" in text
    assert "Маникюр" in text
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callbacks == ["reschedule:1", "cancel:1"]
