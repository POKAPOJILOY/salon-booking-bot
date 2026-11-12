import logging

from aiogram.exceptions import TelegramAPIError

import texts


async def notify_master(bot, master_id: int, booking, action: str = "Новая запись", demo: bool = False) -> None:
    try:
        await bot.send_message(master_id, texts.master_notification(booking, action, demo))
    except TelegramAPIError:
        logging.exception("Не удалось уведомить мастера %s", master_id)
