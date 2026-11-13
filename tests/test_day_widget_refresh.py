import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import day_widget
from client import confirm_booking
from database import LOCAL_TZ, SalonDB, db_time, utc_now
from day_widget import refresh_open_day, send_day_widget
from scheduler import process_pending
from widget import handle_widget_update


class FakeBot:
    def __init__(self, fail_edit=False):
        self.methods = []
        self.send_message = AsyncMock()
        self.fail_edit = fail_edit

    async def __call__(self, method):
        if self.fail_edit and method.__api_method__ == "editMessageWidgetData":
            raise RuntimeError("edit failed")
        self.methods.append(method)
        return SimpleNamespace(message_id=100 + len(self.methods))


@pytest.fixture(autouse=True)
def clear_widget_registry():
    day_widget._day_widgets.clear()
    yield
    day_widget._day_widgets.clear()


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "09:00", "20:00", None, None)
    yield database, service_id
    database.close()


def next_day_start(database, service_id):
    return database.next_slots(service_id, limit=1)[0]


def callback(data="confirm"):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=100),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_client_booking_edits_open_day_and_caption_is_static(db):
    database, service_id = db
    start = next_day_start(database, service_id)
    day = start.astimezone(LOCAL_TZ).date()
    bot = FakeBot()
    assert await send_day_widget(bot, database, day, 1)
    initial = next(method for method in bot.methods if method.__api_method__ == "sendWidget")
    assert "Выручка" not in initial.caption
    assert initial.caption.startswith("📅 Расписание · ")
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=100, user_id=100))
    await state.set_data({
        "service_id": service_id, "start_at": start.isoformat(), "name": "Анна",
        "phone": "+79990000000", "source": "link", "reinvited_from_id": None,
    })
    await confirm_booking(callback(), state, database, bot, 1)
    edit = next(method for method in bot.methods if method.__api_method__ == "editMessageWidgetData")
    state = json.loads(edit.chat_data)
    assert "1 запис" in state["summary"]
    assert any(item["type"] == "booking" and item["client"] == "Анна" for item in state["items"])


@pytest.mark.asyncio
async def test_reinvite_booking_edits_open_day(db):
    database, service_id = db
    start = next_day_start(database, service_id)
    day = start.astimezone(LOCAL_TZ).date()
    bot = FakeBot()
    await send_day_widget(bot, database, day, 1)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    now = utc_now()
    cursor = database.conn.execute(
        "INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at) VALUES (1, ?, ?, ?, ?, 'done', 'link', ?)",
        (client_id, service_id, db_time(now - timedelta(days=22)), db_time(now - timedelta(days=21)), db_time(now)),
    )
    update = SimpleNamespace(widget_query={
        "id": "book-query", "from": {"id": 100}, "chat": {"id": 100},
        "message_id": 42, "data": f"book:{cursor.lastrowid}:{start.isoformat()}",
    })
    await handle_widget_update(update, bot, database, 1)
    edits = [method for method in bot.methods if method.__api_method__ == "editMessageWidgetData"]
    summaries = [json.loads(method.chat_data).get("summary", "") for method in edits]
    assert any("1 запис" in summary for summary in summaries)


@pytest.mark.asyncio
async def test_scheduler_completion_edits_open_day(db):
    database, service_id = db
    start = next_day_start(database, service_id)
    day = start.astimezone(LOCAL_TZ).date()
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    booking_id = database.create_booking(client_id, service_id, start)
    database.conn.execute(
        "UPDATE bookings SET start_at = ?, end_at = ? WHERE id = ?",
        (db_time(utc_now() - timedelta(hours=2)), db_time(utc_now() - timedelta(hours=1)), booking_id),
    )
    bot = FakeBot()
    await send_day_widget(bot, database, day, 1)
    await process_pending(bot, database, 1)
    edits = [method for method in bot.methods if method.__api_method__ == "editMessageWidgetData"]
    assert edits
    assert "0 запис" in json.loads(edits[-1].chat_data)["summary"]


@pytest.mark.asyncio
async def test_failed_edit_replaces_widget_and_updates_registry(db):
    database, service_id = db
    start = next_day_start(database, service_id)
    day = start.astimezone(LOCAL_TZ).date()
    bot = FakeBot()
    await send_day_widget(bot, database, day, 1)
    old_id = day_widget._day_widgets[1]["message_id"]
    bot.fail_edit = True
    assert await refresh_open_day(bot, database, 1)
    names = [method.__api_method__ for method in bot.methods]
    assert "deleteMessage" in names
    assert "sendWidget" in names
    assert day_widget._day_widgets[1]["message_id"] != old_id
