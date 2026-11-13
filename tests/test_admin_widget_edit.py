from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText

from admin import day_pick, edit_callback_message


def widget_callback(data):
    error = TelegramBadRequest(
        EditMessageText(chat_id=1, message_id=42, text="Недоступно"),
        "there is no text in the message to edit",
    )
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(
            text=None,
            edit_text=AsyncMock(side_effect=error),
            delete=AsyncMock(),
            answer=AsyncMock(),
        ),
        answer=AsyncMock(),
    )


def state():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))


@pytest.mark.asyncio
async def test_day_pick_on_widget_deletes_old_and_sends_calendar_in_new_message():
    callback = widget_callback("admin_day_pick")
    await day_pick(callback, state())
    callback.message.delete.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    markup = callback.message.answer.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard


@pytest.mark.asyncio
async def test_shared_admin_edit_helper_replaces_uneditable_widget_message():
    callback = widget_callback("admin_edit_day:2")
    await edit_callback_message(callback, "Новый экран", None)
    callback.message.delete.assert_awaited_once()
    callback.message.answer.assert_awaited_once_with("Новый экран", reply_markup=None)
