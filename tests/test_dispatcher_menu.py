"""Интеграционные тесты через настоящий Dispatcher: ловят класс бага
«menu_interruptible не получает db из-за @wraps» — юнит-тесты с прямыми
вызовами его не видят."""

from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetMe, SendMessage
from aiogram.types import Chat, Message, Update, User

import admin
import client
import texts
from database import SalonDB


class DummySession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.calls), date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"), text=method.text,
            )
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="salon", username="salon_test_bot")
        return True

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError


@pytest.fixture
def harness():
    database = SalonDB(":memory:", master_id=1)
    database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    session = DummySession()
    bot = Bot("1:TEST", session=session)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    # глобальные роутеры можно прикрепить только к одному Dispatcher — сбрасываем привязку между тестами
    admin.router._parent_router = None
    client.router._parent_router = None
    dp.include_router(admin.router)
    dp.include_router(client.router)
    yield database, bot, session, storage, dp
    admin.router._parent_router = None
    client.router._parent_router = None
    database.close()


def fsm(storage, user_id=1):
    return FSMContext(storage, StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


def incoming(text, user_id=1):
    return Update(
        update_id=1,
        message=Message(
            message_id=1, date=datetime.now(),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Мастер"),
            text=text,
        ),
    )


@pytest.mark.asyncio
async def test_menu_button_during_block_dialog_opens_schedule_without_validation_error(harness):
    database, bot, session, storage, dp = harness
    state = fsm(storage)
    await state.set_state(admin.BlockStates.day)
    await dp.feed_update(bot, incoming(texts.MASTER_SCHEDULE), db=database, master_id=1)
    assert await state.get_state() is None
    sent = [call.text for call in session.calls if isinstance(call, SendMessage)]
    assert sent, "бот ничего не ответил"
    assert any(texts.WEEK_SCHEDULE_TITLE in text for text in sent)
    assert not any(texts.ADMIN_INVALID_DATE in text for text in sent)


@pytest.mark.asyncio
async def test_regular_text_still_reaches_fsm_handler(harness):
    database, bot, session, storage, dp = harness
    state = fsm(storage)
    await state.set_state(admin.BlockStates.day)
    await dp.feed_update(bot, incoming("20.11.2026"), db=database, master_id=1)
    assert await state.get_state() == admin.BlockStates.interval
    sent = [call.text for call in session.calls if isinstance(call, SendMessage)]
    assert any(texts.ADMIN_BLOCK_INTERVAL in text for text in sent)


@pytest.mark.asyncio
async def test_menu_middleware_does_not_touch_other_users_state(harness):
    database, bot, session, storage, dp = harness
    state = fsm(storage, user_id=100)
    await state.set_state(client.BookingStates.name)
    # клиент пишет текст кнопки мастера — его диалог не должен очищаться админским middleware
    await dp.feed_update(bot, incoming(texts.MASTER_SCHEDULE, user_id=100), db=database, master_id=1)
    assert await state.get_state() == client.BookingStates.name


@pytest.mark.asyncio
async def test_client_menu_button_cancels_dialog_via_dispatcher(harness):
    database, bot, session, storage, dp = harness
    state = fsm(storage, user_id=100)
    await state.set_state(client.BookingStates.name)
    await dp.feed_update(bot, incoming(texts.CLIENT_BOOKINGS, user_id=100), db=database, master_id=1)
    assert await state.get_state() is None
    sent = [call.text for call in session.calls if isinstance(call, SendMessage)]
    assert any(texts.CLIENT_NO_BOOKINGS in text for text in sent)
