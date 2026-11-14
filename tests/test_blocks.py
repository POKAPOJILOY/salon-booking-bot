import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import admin
import texts
from database import SalonDB, utc_now
from database import LOCAL_TZ
from day_widget import day_widget_state


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "09:00", "20:00", None, None)
    yield database
    database.close()


def fsm():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))


def callback(data, user_id=1):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(
            edit_text=AsyncMock(),
            delete=AsyncMock(),
            answer=AsyncMock(),
        ),
        answer=AsyncMock(),
    )


def message(text):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=1),
        answer=AsyncMock(),
    )


def cancel_button(markup):
    return any(
        button.callback_data == "block_cancel"
        for row in markup.inline_keyboard
        for button in row
    )


@pytest.mark.asyncio
async def test_block_appears_in_list_and_deletes_with_confirmation(db):
    day = (utc_now().astimezone(LOCAL_TZ).date() + timedelta(days=1))
    block_id = db.add_block(day, "19:30", "20:00", "Личное")

    query = callback("admin_blocks")
    await admin.blocks_list(query, db)
    text = query.message.edit_text.await_args.args[0]
    assert "Личное" in text and "19:30–20:00" in text
    callbacks = [
        button.callback_data
        for row in query.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert f"block_delete:{block_id}" in callbacks

    confirm = callback(f"block_delete:{block_id}")
    await admin.block_delete_confirm(confirm, db)
    question = confirm.message.edit_text.await_args.args[0]
    assert "Удалить блок 19:30–20:00 (Личное)" in question

    bot = SimpleNamespace(send_message=AsyncMock())
    yes = callback(f"block_delete_yes:{block_id}")
    await admin.block_delete_yes(yes, db, bot, 1)
    assert db.get_block(block_id) is None

    state = json.loads(day_widget_state(db, day))
    assert not any(item["t"] == "k" for item in state["items"])


@pytest.mark.asyncio
async def test_empty_blocks_list_shows_hint(db):
    query = callback("admin_blocks")
    await admin.blocks_list(query, db)
    assert query.message.edit_text.await_args.args[0] == texts.BLOCKS_EMPTY


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["start", "day", "interval"])
async def test_cancel_button_available_and_clears_state_on_every_step(db, step):
    state = fsm()
    if step == "start":
        msg = message(texts.MASTER_BLOCK)
        await admin.block_start(msg, state)
        assert cancel_button(msg.answer.await_args.kwargs["reply_markup"])
    elif step == "day":
        await state.set_state(admin.BlockStates.day)
        msg = message("20.11.2026")
        await admin.block_day(msg, state)
        assert cancel_button(msg.answer.await_args.kwargs["reply_markup"])
    else:
        await state.set_state(admin.BlockStates.interval)
        await state.update_data(day="2026-11-20")
        msg = message("12:00-13:00")
        await admin.block_interval(msg, state)
        assert cancel_button(msg.answer.await_args.kwargs["reply_markup"])
    assert await state.get_state() is not None

    cancel = callback("block_cancel")
    await admin.block_cancel(cancel, state)
    assert await state.get_state() is None
    cancel.message.edit_text.assert_awaited_once()
    assert cancel.message.edit_text.await_args.args[0] == texts.BLOCK_MENU_TITLE


@pytest.mark.asyncio
async def test_invalid_input_also_offers_cancel(db):
    state = fsm()
    await state.set_state(admin.BlockStates.day)
    msg = message("не дата")
    await admin.block_day(msg, state)
    assert msg.answer.await_args.args[0] == texts.ADMIN_INVALID_DATE
    assert cancel_button(msg.answer.await_args.kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_delete_refreshes_open_day_widget(db, monkeypatch):
    day = utc_now().astimezone(LOCAL_TZ).date() + timedelta(days=1)
    block_id = db.add_block(day, "19:30", "20:00", "Личное")
    refresh = AsyncMock()
    monkeypatch.setattr(admin, "refresh_open_day", refresh)
    bot = SimpleNamespace(send_message=AsyncMock())
    await admin.block_delete_yes(callback(f"block_delete_yes:{block_id}"), db, bot, 1)
    refresh.assert_awaited_once()
    assert refresh.await_args.args[3] == day


@pytest.mark.asyncio
async def test_blocks_list_does_not_set_state_and_menu_still_works(db):
    state = fsm()
    await admin.blocks_list(callback("admin_blocks"), db)
    assert await state.get_state() is None
    # reply-кнопка меню во время просмотра списка переключает раздел штатно
    msg = message(texts.MASTER_SCHEDULE)
    await admin.schedule(msg, db)
    assert texts.WEEK_SCHEDULE_TITLE in msg.answer.await_args.args[0]
