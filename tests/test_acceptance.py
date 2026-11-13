from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText

import admin
import texts
from client import confirm_booking
from database import LOCAL_TZ, SalonDB, SlotUnavailable, utc_now
from day_widget import day_widget_state
from widget import handle_widget_update


class FakeBot:
    def __init__(self):
        self.methods = []
        self.send_message = AsyncMock()
        self.get_me = AsyncMock(return_value=SimpleNamespace(username="salon_test_bot"))

    async def __call__(self, method):
        self.methods.append(method)
        return SimpleNamespace(message_id=100 + len(self.methods))


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "09:00", "20:00", "14:00", "14:30")
    yield database
    database.close()


def state(user_id=1):
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


def message(text, user_id=1):
    return SimpleNamespace(text=text, from_user=SimpleNamespace(id=user_id, username="test"), answer=AsyncMock())


def callback(data, user_id=1, edit_error=False):
    error = TelegramBadRequest(
        EditMessageText(chat_id=user_id, message_id=42, text="x"),
        "there is no text in the message to edit",
    )
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(
            text=None,
            widget={"id": "w"} if edit_error else None,
            message_id=42,
            chat=SimpleNamespace(id=user_id),
            edit_text=AsyncMock(side_effect=error if edit_error else None),
            delete=AsyncMock(),
            answer=AsyncMock(),
        ),
        answer=AsyncMock(),
    )


async def accept_start(db):
    msg = message("/start")
    await admin.admin_start(msg, state(), db)
    keyboard = msg.answer.await_args.kwargs["reply_markup"]
    assert sum(len(row) for row in keyboard.keyboard) == 9


async def accept_day_navigation_calendar(db):
    bot = FakeBot()
    msg = message(texts.MASTER_BOOKINGS)
    await admin.show_day(msg, db, utc_now().astimezone(LOCAL_TZ).date(), bot)
    assert any(method.__api_method__ == "sendWidget" for method in bot.methods)
    query = callback("admin_day:2026-11-18", edit_error=True)
    await admin.day_navigation(query, db, bot)
    assert any(method.__api_method__ == "deleteMessage" for method in bot.methods)
    pick = callback("admin_day_pick", edit_error=True)
    await admin.day_pick(pick, state())
    assert pick.message.answer.await_args.kwargs["reply_markup"].inline_keyboard


async def accept_open_booking(db):
    client_id = db.upsert_client(100, "Анна", "+79990000000")
    booking_id = db.create_booking(client_id, 1, db.next_slots(1, limit=1)[0])
    update = SimpleNamespace(widget_query={"id": "q", "from": {"id": 1}, "chat": {"id": 1}, "message_id": 42, "data": f"open:{booking_id}"})
    bot = FakeBot()
    await handle_widget_update(update, bot, db, 1)
    assert f"admin_cancel:{booking_id}" in [button.callback_data for row in bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard for button in row]


async def accept_manual_booking_and_conflict(db):
    bot = FakeBot()
    fsm = state()
    await admin.manual_service(callback("manual_service:1"), fsm, db)
    day = db.available_dates(1)[0]
    await admin.manual_date(callback(f"manual_date:{day.isoformat()}"), fsm, db)
    start = db.available_slots(1, day)[0]
    await admin.manual_time(callback(f"manual_time:{start.isoformat()}"), fsm)
    await admin.manual_name(message("Мария"), fsm)
    await admin.manual_phone(message("+79990000000"), fsm, db, bot, 1)
    assert db.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1
    client_id = db.create_client(None, "Другая", "+79990000001")
    with pytest.raises(SlotUnavailable):
        db.create_booking(client_id, 1, start)


async def accept_block(db):
    fsm = state()
    day = utc_now().astimezone(LOCAL_TZ).date() + timedelta(days=1)
    await admin.block_day(message(day.strftime("%d.%m.%Y")), fsm)
    await admin.block_interval(message("12:00-13:00"), fsm)
    await admin.block_reason(message("ДЕМО · проверка"), fsm, db, FakeBot(), 1)
    state_data = day_widget_state(db, day)
    assert '"t":"k"' in state_data


async def accept_services(db):
    fsm = state()
    await admin.service_name(message("Педикюр"), fsm)
    await admin.service_price(message("2500"), fsm)
    await admin.service_duration(message("90"), fsm, db)
    service_id = db.list_services()[-1]["id"]
    await admin.service_toggle(callback(f"service_toggle:{service_id}:False"), db)
    assert db.get_service(service_id)["is_active"] == 0
    await admin.service_toggle(callback(f"service_toggle:{service_id}:True"), db)
    assert db.get_service(service_id)["is_active"] == 1
    await admin.service_delete(callback(f"service_delete:{service_id}"), db)
    assert db.get_service(service_id)["is_active"] == 0


async def accept_schedule(db):
    fsm = state()
    await admin.schedule_weekday(callback("admin_edit_day:0"), fsm)
    await admin.schedule_day(message("10:00-18:00"), fsm)
    await admin.schedule_break(message("14:00-14:30"), fsm, db)
    row = next(row for row in db.get_schedules() if row["weekday"] == 0)
    assert row["work_start"] == "10:00" and row["work_end"] == "18:00"
    assert row["break_start"] == "14:00"


async def accept_settings(db):
    fsm = state()
    await admin.setting_start(callback("setting:min_notice_hours"), fsm)
    await admin.setting_value(message("3"), fsm, db)
    assert db.get_master()["min_notice_hours"] == 3
    start = db.next_slots(1, limit=1)[0]
    assert start not in db.available_slots(1, start.astimezone(LOCAL_TZ).date(), now=start - timedelta(hours=1))


async def accept_link(db):
    bot = FakeBot()
    query = callback("admin_link")
    await admin.my_link(query, bot, db)
    keyboard = query.message.edit_text.await_args.kwargs["reply_markup"]
    copy = keyboard.inline_keyboard[0][0].copy_text
    assert copy.text == "https://t.me/salon_test_bot"


async def accept_stats(db):
    text = admin.stats_text(db)
    assert "За всё время" in text
    assert "За 30 дней" not in text


async def accept_client_booking(db):
    start = db.next_slots(1, limit=1)[0]
    fsm = state(100)
    await fsm.set_data({"service_id": 1, "start_at": start.isoformat(), "name": "Анна", "phone": "+79990000000", "source": "link", "reinvited_from_id": None})
    bot = FakeBot()
    await confirm_booking(callback("confirm", user_id=100), fsm, db, bot, 1)
    assert db.get_booking(1)["client_name"] == "Анна"
    with pytest.raises(SlotUnavailable):
        db.create_booking(db.create_client(None, "Другая", "+79990000001"), 1, start)


async def accept_block_hint_compact(db):
    query = callback("admin_day_pick", edit_error=True)
    await admin.day_pick(query, state())
    text = query.message.answer.await_args.args[0]
    assert texts.ADMIN_BLOCK_DATE in text
    assert "🟢" not in text
    assert query.message.answer.await_args.kwargs["reply_markup"].inline_keyboard


async def accept_menu_interrupt(db):
    fsm = state()
    await fsm.set_state(admin.BlockStates.day)
    await admin.block_day(message(texts.MASTER_SCHEDULE), fsm, db=db)
    assert await fsm.get_state() is None


async def accept_no_edit_on_widget(db):
    query = callback("admin_day_pick", edit_error=True)
    await admin.day_pick(query, state())
    query.message.delete.assert_awaited_once()
    query.message.answer.assert_awaited_once()


SCENARIOS = [
    accept_start,
    accept_day_navigation_calendar,
    accept_open_booking,
    accept_manual_booking_and_conflict,
    accept_block,
    accept_services,
    accept_schedule,
    accept_settings,
    accept_link,
    accept_stats,
    accept_client_booking,
    accept_block_hint_compact,
    accept_menu_interrupt,
    accept_no_edit_on_widget,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda fn: fn.__name__)
async def test_acceptance_every_button_and_flow(db, scenario):
    await scenario(db)
