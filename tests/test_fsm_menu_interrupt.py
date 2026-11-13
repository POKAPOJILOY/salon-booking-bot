from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import admin
import texts
from database import SalonDB


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    database.add_service("Маникюр", 2000, 60)
    yield database
    database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("state_name,handler", [
    (admin.ManualStates.name, admin.manual_name),
    (admin.ManualStates.phone, admin.manual_phone),
    (admin.BlockStates.day, admin.block_day),
    (admin.BlockStates.interval, admin.block_interval),
    (admin.BlockStates.reason, admin.block_reason),
    (admin.ServiceStates.name, admin.service_name),
    (admin.ServiceStates.price, admin.service_price),
    (admin.ServiceStates.duration, admin.service_duration),
    (admin.ScheduleStates.days, admin.schedule_day),
    (admin.ScheduleStates.break_time, admin.schedule_break),
    (admin.SettingStates.value, admin.setting_value),
    (admin.DayPickStates.day, admin.day_picked),
])
async def test_every_admin_state_menu_button_cancels_dialog_without_validation_error(db, state_name, handler):
    message = SimpleNamespace(
        text=texts.MASTER_SCHEDULE,
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))
    await state.set_state(state_name)
    bot = SimpleNamespace(send_message=AsyncMock())
    await handler(message=message, state=state, db=db, bot=bot, master_id=1)
    assert await state.get_state() is None
    text = message.answer.await_args.args[0]
    assert texts.WEEK_SCHEDULE_TITLE in text
    assert texts.ADMIN_INVALID_DATE not in text
    assert texts.ADMIN_INVALID_INTERVAL not in text
    assert texts.INVALID_NAME not in text
    assert texts.INVALID_PHONE not in text


@pytest.mark.asyncio
async def test_client_menu_button_cancels_name_input(db):
    import client

    message = SimpleNamespace(
        text=texts.CLIENT_BOOKINGS,
        from_user=SimpleNamespace(id=100),
        answer=AsyncMock(),
    )
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=100, user_id=100))
    await state.set_state(client.BookingStates.name)
    await client.save_name(message=message, state=state, db=db)
    assert await state.get_state() is None
    assert message.answer.await_args.args[0] == texts.CLIENT_NO_BOOKINGS
