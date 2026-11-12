import json
import zlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import widget
from database import SalonDB, db_time, utc_now
from widget import WIDGET_HTML, handle_widget_update, send_reinvite_message, widget_state


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    yield database, service_id
    database.close()


def completed_visit(database, service_id, tg_id=100):
    client_id = database.upsert_client(tg_id, "Анна", "+79990000000")
    now = utc_now()
    cursor = database.conn.execute(
        """
        INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at)
        VALUES (1, ?, ?, ?, ?, 'done', 'link', ?)
        """,
        (client_id, service_id, db_time(now - timedelta(days=22)), db_time(now - timedelta(days=21)), db_time(now)),
    )
    return database.get_booking(cursor.lastrowid)


def update_for(booking, start):
    return SimpleNamespace(widget_query={
        "id": "query-1",
        "from": {"id": booking["tg_id"]},
        "chat": {"id": booking["tg_id"]},
        "message_id": 42,
        "data": f"book:{booking['id']}:{start.isoformat()}",
    })


class FakeBot:
    def __init__(self, fail_widget=False):
        self.fail_widget = fail_widget
        self.methods = []
        self.send_message = AsyncMock()

    async def __call__(self, method):
        self.methods.append(method)
        if method.__api_method__ == "sendWidget" and self.fail_widget:
            raise RuntimeError("widgets unavailable")
        return SimpleNamespace(message_id=42)


@pytest.mark.asyncio
async def test_disabled_widget_uses_button_fallback(db, monkeypatch):
    database, service_id = db
    booking = completed_visit(database, service_id)
    bot = FakeBot()
    monkeypatch.setattr(widget, "WIDGETS_ENABLED", False)
    assert await send_reinvite_message(bot, database, booking)
    bot.send_message.assert_awaited_once()
    assert bot.methods == []
    assert "Подобрать" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_failed_widget_quietly_falls_back(db):
    database, service_id = db
    booking = completed_visit(database, service_id)
    bot = FakeBot(fail_widget=True)
    assert await send_reinvite_message(bot, database, booking)
    bot.send_message.assert_awaited_once()
    assert bot.methods[0].__api_method__ == "sendWidget"


def test_widget_document_and_state_fit_telegram_limits(db):
    database, service_id = db
    booking = completed_visit(database, service_id)
    state = widget_state(database, booking)
    assert len(state.encode("utf-8")) <= 1024
    assert 5 <= len(json.loads(state)["slots"]) <= 7
    assert len(WIDGET_HTML.encode("utf-8")) <= 32768
    assert len(zlib.compress(WIDGET_HTML.encode("utf-8"), level=9)) <= 4096


@pytest.mark.asyncio
async def test_double_widget_tap_creates_only_one_reinvite(db):
    database, service_id = db
    old = completed_visit(database, service_id)
    start = database.next_slots(service_id, limit=1)[0]
    bot = FakeBot()
    await handle_widget_update(update_for(old, start), bot, database, 1)
    await handle_widget_update(update_for(old, start), bot, database, 1)
    rows = database.conn.execute("SELECT * FROM bookings WHERE status = 'active'").fetchall()
    assert len(rows) == 1
    assert rows[0]["source"] == "reinvite"
    assert rows[0]["reinvited_from_id"] == old["id"]
    answers = [method for method in bot.methods if method.__api_method__ == "answerWidgetQuery"]
    assert json.loads(answers[0].data)["status"] == "booked"
    assert json.loads(answers[1].data)["status"] == "exists"
    edit = next(method for method in bot.methods if method.__api_method__ == "editMessageWidgetData")
    success = json.loads(edit.chat_data)
    assert "title" not in success and "subtitle" not in success
    assert success["service"] == "Маникюр"
    assert success["price"] == 2000
    assert success["success"]


@pytest.mark.asyncio
async def test_stale_widget_slot_is_refreshed(db):
    database, service_id = db
    old = completed_visit(database, service_id)
    start = database.next_slots(service_id, limit=1)[0]
    other_client = database.upsert_client(200, "Мария", "+79990000001")
    database.create_booking(other_client, service_id, start)
    bot = FakeBot()
    await handle_widget_update(update_for(old, start), bot, database, 1)
    assert database.active_booking_for_client(old["client_id"]) is None
    answer = next(method for method in bot.methods if method.__api_method__ == "answerWidgetQuery")
    assert json.loads(answer.data)["status"] == "stale"
    edit = next(method for method in bot.methods if method.__api_method__ == "editMessageWidgetData")
    refreshed = json.loads(edit.chat_data)
    assert start.isoformat() not in [slot["s"] for slot in refreshed["slots"]]
    assert "заняли" in refreshed["notice"]
