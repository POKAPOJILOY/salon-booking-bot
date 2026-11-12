import json
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import day_widget
from admin import day_navigation
from database import LOCAL_TZ, SalonDB, utc_now
from day_widget import day_widget_state, send_day_widget
from widget import handle_widget_update


class FakeBot:
    def __init__(self):
        self.methods = []
        self.send_message = AsyncMock()

    async def __call__(self, method):
        self.methods.append(method)
        return SimpleNamespace(message_id=100)


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    database.update_master(slot_step_min=60)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(6):
        database.set_schedule(weekday, True, "09:00", "18:00", "15:00", "15:30")
    database.set_schedule(6, False)
    yield database, service_id
    database.close()


def seed_day(database, service_id):
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    start = datetime.combine(day, time(10), tzinfo=LOCAL_TZ)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    booking_id = database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))
    database.add_block(day, "16:00", "17:00", "Личное дело")
    return day, start, booking_id


def test_day_widget_state_sorts_items_compresses_free_time_and_calculates_revenue(db):
    database, service_id = db
    day, start, booking_id = seed_day(database, service_id)
    state = json.loads(day_widget_state(database, day))
    assert state["d"] == day.isoformat()
    assert "1 запис" in state["summary"]
    assert state["revenue"] == "Выручка по записи: 2 000 ₽"
    starts = [item.get("start", "00:00") for item in state["items"]]
    assert starts == sorted(starts)
    booking = next(item for item in state["items"] if item["type"] == "booking")
    assert booking["id"] == booking_id and booking["past"] is False
    free = next(item for item in state["items"] if item["type"] == "free" and item["start"] == "11:00")
    assert free["end"] == "15:00"
    assert all(not (item["type"] == "free" and item["start"] == item["end"]) for item in state["items"])
    later = json.loads(day_widget_state(database, day, now=start + timedelta(hours=2)))
    assert next(item for item in later["items"] if item["type"] == "booking")["past"] is True


def test_day_widget_state_closed_day(db):
    database, service_id = db
    sunday = date(2026, 11, 15)
    state = json.loads(day_widget_state(database, sunday))
    assert state["items"] == [{"type": "closed"}]


@pytest.mark.asyncio
async def test_open_booking_permissions_and_keyboard(db):
    database, service_id = db
    day, start, booking_id = seed_day(database, service_id)

    def update(user_id):
        return SimpleNamespace(widget_query={
            "id": "query-open", "from": {"id": user_id},
            "chat": {"id": user_id}, "message_id": 42, "data": f"open:{booking_id}",
        })

    bot = FakeBot()
    await handle_widget_update(update(200), bot, database, 1)
    answer = next(method for method in bot.methods if method.__api_method__ == "answerWidgetQuery")
    assert json.loads(answer.data)["status"] == "invalid"
    bot.send_message.assert_not_called()

    await handle_widget_update(update(1), bot, database, 1)
    answer = next(method for method in bot.methods if method.__api_method__ == "answerWidgetQuery" and method.widget_query_id == "query-open")
    bot.send_message.assert_awaited_once()
    callbacks = [button.callback_data for row in bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard for button in row]
    assert f"admin_cancel:{booking_id}" in callbacks


@pytest.mark.asyncio
async def test_widget_navigation_replaces_widget_but_edits_text(db):
    database, service_id = db
    day, start, booking_id = seed_day(database, service_id)
    bot = FakeBot()

    def callback(widget_value):
        return SimpleNamespace(
            data=f"admin_day:{day.isoformat()}",
            from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(
                widget=widget_value, message_id=42,
                chat=SimpleNamespace(id=1), edit_text=AsyncMock(),
            ),
            answer=AsyncMock(),
        )

    widget_callback = callback({"id": "widget-1"})
    await day_navigation(widget_callback, database, bot)
    names = [method.__api_method__ for method in bot.methods]
    assert "sendWidget" in names and "deleteMessage" in names
    widget_callback.message.edit_text.assert_not_called()

    bot.methods.clear()
    text_callback = callback(None)
    await day_navigation(text_callback, database, bot)
    text_callback.message.edit_text.assert_awaited_once()
    assert "sendWidget" not in [method.__api_method__ for method in bot.methods]


@pytest.mark.asyncio
async def test_day_widget_falls_back_to_text_when_disabled(db, monkeypatch):
    database, service_id = db
    day, start, booking_id = seed_day(database, service_id)
    monkeypatch.setattr(day_widget, "WIDGETS_ENABLED", False)
    bot = FakeBot()
    assert await send_day_widget(bot, database, day, 1) is False
    bot.send_message.assert_awaited_once()
    assert "Выручка по записи дня" in bot.send_message.await_args.args[1]
