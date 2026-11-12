from datetime import datetime

import pytest
from aiogram import Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

import admin
import client
from database import LOCAL_TZ, SalonDB


class FakeBot:
    id = 1

    def __init__(self):
        self.methods = []

    async def __call__(self, method):
        self.methods.append(method)
        return True

    async def send_message(self, chat_id, text, **kwargs):
        self.methods.append(SendMessage(chat_id=chat_id, text=text, **kwargs))
        return True


def message(user_id, text, message_id=1):
    return Message(
        message_id=message_id,
        date=datetime.now(),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Анна"),
        text=text,
    )


@pytest.mark.asyncio
async def test_real_dispatcher_completes_client_booking_flow(tmp_path):
    database = SalonDB(tmp_path / "flow.db", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(client.router)
    bot = FakeBot()
    user_id = 100

    async def send_message(text):
        update = Update(update_id=len(bot.methods) + 1000, message=message(user_id, text))
        await dp.feed_update(bot, update, db=database, master_id=1)

    async def click(data):
        update = Update(
            update_id=len(bot.methods) + 2000,
            callback_query=CallbackQuery(
                id=str(len(bot.methods) + 2000),
                from_user=User(id=user_id, is_bot=False, first_name="Анна"),
                chat_instance="chat",
                message=message(user_id, "Предыдущее сообщение"),
                data=data,
            ),
        )
        await dp.feed_update(bot, update, db=database, master_id=1)

    await send_message("/start")
    await click("book")
    await click(f"service:{service_id}")
    start = database.next_slots(service_id, limit=1)[0]
    day = start.astimezone(LOCAL_TZ).date()
    await click(f"date:{day.isoformat()}")
    await click(f"time:{start.isoformat()}")
    await send_message("Анна")
    await send_message("+79990000000")
    await click("confirm")
    booking = database.get_booking(1)
    assert booking["client_name"] == "Анна"
    assert booking["phone"] == "+79990000000"
    assert booking["start_at"] == start.isoformat(timespec="seconds")
    master_messages = [method for method in bot.methods if method.__api_method__ == "sendMessage" and method.chat_id == 1]
    assert len(master_messages) == 1

    await dp.feed_update(
        bot,
        Update(update_id=9001, message=message(user_id, "📋 Мои записи")),
        db=database,
        master_id=1,
    )
    client_messages = [method for method in bot.methods if method.__api_method__ == "sendMessage" and method.chat_id == user_id]
    assert any("Анна" in method.text and "Маникюр" in method.text for method in client_messages)

    await dp.feed_update(
        bot,
        Update(update_id=9002, message=message(1, "📋 Записи")),
        db=database,
        master_id=1,
    )
    day_widgets = [method for method in bot.methods if method.__api_method__ == "sendWidget" and method.chat_id == 1]
    assert any("Выручка по записи" in method.caption for method in day_widgets)
    database.close()
