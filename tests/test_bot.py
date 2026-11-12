from aiogram import Dispatcher

from bot import polling_updates
from widget import handle_widget_update


def test_polling_requests_messages_callbacks_and_widget_queries():
    dp = Dispatcher()
    dp.update.register(handle_widget_update)
    assert polling_updates(dp) == ["widget_query"]


def test_polling_keeps_standard_update_types():
    dp = Dispatcher()

    @dp.message()
    async def message_handler():
        pass

    @dp.callback_query()
    async def callback_handler():
        pass

    dp.update.register(handle_widget_update)
    updates = polling_updates(dp)
    assert "message" in updates
    assert "callback_query" in updates
    assert "widget_query" in updates
