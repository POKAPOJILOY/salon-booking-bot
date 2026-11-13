import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from database import SalonDB, db_time, utc_now
from notifications import notify_master
from widget import send_reinvite_message


class FakeBot:
    def __init__(self, fail=False):
        self.methods = []
        self.fail = fail
        self.send_message = AsyncMock()

    async def __call__(self, method):
        if self.fail:
            raise RuntimeError("widget unavailable")
        self.methods.append(method)
        return SimpleNamespace(message_id=100)


@pytest.fixture
def booking():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "09:00", "20:00", None, None)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = database.next_slots(service_id, limit=1)[0]
    booking_id = database.create_booking(client_id, service_id, start)
    yield database, database.get_booking(booking_id)
    database.close()


@pytest.mark.asyncio
async def test_master_notification_is_widget_with_details_and_action_buttons(booking):
    database, row = booking
    bot = FakeBot()
    await notify_master(bot, 1, row)
    method = next(method for method in bot.methods if method.__api_method__ == "sendWidget")
    assert "Анна" in method.html
    assert "Маникюр" in method.html
    assert "+79990000000" in method.html
    assert "Анна" in method.caption and "2 000 ₽" in method.caption
    assert len(method.chat_data.encode("utf-8")) <= 1000
    bot.send_message.assert_awaited_once()
    callbacks = [button.callback_data for button_row in bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard for button in button_row]
    assert f"admin_reschedule:{row['id']}" in callbacks
    assert f"admin_cancel:{row['id']}" in callbacks


@pytest.mark.asyncio
async def test_master_notification_widget_failure_uses_current_text(booking):
    database, row = booking
    bot = FakeBot(fail=True)
    await notify_master(bot, 1, row)
    bot.send_message.assert_awaited_once()
    assert "Маникюр" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_reinvite_caption_contains_service_price_and_call_to_action(booking):
    database, row = booking
    now = utc_now()
    database.conn.execute(
        "UPDATE bookings SET status = 'done', start_at = ?, end_at = ? WHERE id = ?",
        (db_time(now - timedelta(days=22)), db_time(now - timedelta(days=21)), row["id"]),
    )
    row = database.get_booking(row["id"])
    bot = FakeBot()
    assert await send_reinvite_message(bot, database, row)
    method = next(method for method in bot.methods if method.__api_method__ == "sendWidget")
    assert "Маникюр" in method.caption
    assert "2 000 ₽" in method.caption
    assert "выберите удобное время" in method.caption
    assert len(method.caption) <= 1024
