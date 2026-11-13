import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import admin
import demo
import texts
from database import SalonDB
from day_widget import day_widget_state


class FakeBot:
    def __init__(self):
        self.send_message = AsyncMock()
        self.methods = []

    async def __call__(self, method):
        self.methods.append(method)
        return SimpleNamespace(message_id=100)


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    yield database
    database.close()


@pytest.mark.asyncio
async def test_demo_menu_offers_three_modes_without_creating_data(db):
    message = SimpleNamespace(
        text=texts.MASTER_DEMO,
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )
    state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))
    await admin.demo(message, db, FakeBot(), 1)
    assert db.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    text = message.answer.await_args.args[0]
    markup = message.answer.await_args.kwargs["reply_markup"]
    assert text == texts.DEMO_MENU
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callbacks == ["demo_full", "demo_busy", "demo_client", "demo_disable"]


def test_busy_demo_has_eight_bookings_and_cleanup_restores_empty_stats(db):
    day = demo.create_busy_demo_day(db, 1)
    assert db.conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'active'").fetchone()[0] == 8
    assert db.conn.execute("SELECT COUNT(*) FROM blocks WHERE reason LIKE 'ДЕМО%'").fetchone()[0] == 2
    payload = json.loads(day_widget_state(db, day))
    assert len(payload["items"]) <= 9
    demo.cleanup_demo_data(db)
    assert db.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0
    assert db.get_master()["demo_mode"] == 0
    stats = db.statistics()["all"]
    assert all(value == 0 for value in stats.values())


def test_full_demo_cleanup_does_not_leave_demo_records(db):
    demo.create_demo_data(db, 1)
    assert db.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 2
    demo.cleanup_demo_data(db)
    assert db.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0
    assert db.get_master()["demo_mode"] == 0


@pytest.mark.asyncio
async def test_client_demo_plays_full_path_with_sales_notes(db, monkeypatch):
    sleeps = []

    async def no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(demo.asyncio, "sleep", no_sleep)
    bot = FakeBot()
    demo.run_client_demo(bot, db, 1)
    task = next(iter(demo._background_tasks))
    await task
    assert sleeps == [1, 1, 1, 1, 1]
    texts_sent = [call.args[1] for call in bot.send_message.await_args_list]
    assert texts.DEMO_CLIENT_LINK in texts_sent
    assert texts.DEMO_CLIENT_CONFIRM in texts_sent
    assert texts.DEMO_CLIENT_RETURN in texts_sent
    assert any(method.__api_method__ == "sendWidget" for method in bot.methods)
