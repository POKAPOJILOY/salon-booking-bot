import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher

import admin
import client
import config
from config import BOT_TOKEN, MASTER_ID
from database import SalonDB
from scheduler import scheduler_loop
from widget import handle_widget_update


def polling_updates(dp: Dispatcher) -> list[str]:
    return [*dp.resolve_used_update_types(), "widget_query"]


async def main() -> None:
    if not BOT_TOKEN or not MASTER_ID:
        raise SystemExit("Заполните BOT_TOKEN и MASTER_ID в файле .env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = SalonDB(master_id=MASTER_ID)
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(client.router)
    dp.update.register(handle_widget_update)
    task = asyncio.create_task(scheduler_loop(bot, db, MASTER_ID))
    webapp_task = None
    if config.WEBAPP_PUBLIC_URL:
        import webapp

        webapp_task = asyncio.ensure_future(
            webapp.run(bot, db, MASTER_ID, BOT_TOKEN, config.WEBAPP_PORT)
        )
    try:
        await dp.start_polling(
            bot, db=db, master_id=MASTER_ID, allowed_updates=polling_updates(dp)
        )
    finally:
        task.cancel()
        if webapp_task:
            webapp_task.cancel()
            with suppress(asyncio.CancelledError):
                await webapp_task
        with suppress(asyncio.CancelledError):
            await task
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
