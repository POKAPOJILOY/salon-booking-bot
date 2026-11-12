from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText

from client import opt_out, show_confirmation, show_dates, show_services, start_reinvite
from database import SalonDB, db_time, utc_now


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    yield database, service_id
    database.close()


def completed_visit(database, service_id):
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    now = utc_now()
    cursor = database.conn.execute(
        "INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at) VALUES (1, ?, ?, ?, ?, 'done', 'link', ?)",
        (client_id, service_id, db_time(now - timedelta(days=22)), db_time(now - timedelta(days=21)), db_time(now)),
    )
    return cursor.lastrowid


def widget_callback(database, booking_id):
    error = TelegramBadRequest(
        EditMessageText(chat_id=100, message_id=42, text="Нельзя отредактировать"),
        "there is no text in the message to edit",
    )
    message = SimpleNamespace(
        text=None,
        edit_text=AsyncMock(side_effect=error),
        answer=AsyncMock(),
    )
    return SimpleNamespace(
        data=f"reinvite:{booking_id}",
        from_user=SimpleNamespace(id=100),
        message=message,
        answer=AsyncMock(),
    )


def fsm():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=100, user_id=100))


@pytest.mark.asyncio
async def test_reinvite_from_widget_message_answers_without_editing(db):
    database, service_id = db
    booking_id = completed_visit(database, service_id)
    callback = widget_callback(database, booking_id)
    state = fsm()
    await start_reinvite(callback, state, database)
    callback.message.answer.assert_awaited_once()
    callback.message.edit_text.assert_not_called()
    assert (await state.get_data())["reinvited_from_id"] == booking_id


@pytest.mark.asyncio
async def test_opt_out_from_widget_message_answers_without_editing(db):
    database, service_id = db
    booking_id = completed_visit(database, service_id)
    callback = widget_callback(database, booking_id)
    callback.data = f"optout:{booking_id}"
    await opt_out(callback, database)
    callback.message.answer.assert_awaited_once()
    callback.message.edit_text.assert_not_called()
    assert database.get_booking(booking_id)["reinvite_opt_out"] == 1


@pytest.mark.asyncio
async def test_show_services_falls_back_to_answer_on_uneditable_message(db):
    database, service_id = db
    callback = widget_callback(database, 1)
    await show_services(callback.message, fsm(), database, edit=True)
    callback.message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_show_dates_falls_back_to_answer_on_uneditable_message(db):
    database, service_id = db
    callback = widget_callback(database, 1)
    state = fsm()
    await state.update_data(service_id=service_id)
    await show_dates(callback.message, state, database)
    callback.message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_show_confirmation_falls_back_to_answer_on_uneditable_message(db):
    database, service_id = db
    callback = widget_callback(database, 1)
    state = fsm()
    await state.set_data({
        "service_id": service_id,
        "start_at": database.next_slots(service_id, limit=1)[0].isoformat(),
        "name": "Анна",
        "phone": "+79990000000",
    })
    await show_confirmation(callback.message, state, database)
    callback.message.answer.assert_awaited_once()
