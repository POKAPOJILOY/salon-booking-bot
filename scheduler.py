import asyncio
import logging
from datetime import datetime

from aiogram.exceptions import TelegramForbiddenError

import texts
from database import SalonDB, utc_now
from keyboards import booking_actions


async def send_reinvite(bot, booking, db: SalonDB) -> bool:
    from widget import send_reinvite_message

    return await send_reinvite_message(bot, db, booking)


async def process_pending(
    bot,
    db: SalonDB,
    master_id: int,
    now: datetime | None = None,
    reinvite_sender=None,
) -> None:
    now = now or utc_now()
    completed = db.complete_visits(now)
    if completed:
        from day_widget import refresh_open_day

        await refresh_open_day(bot, db, master_id)
    for kind, template in (("reminder24_sent", texts.REMINDER_24), ("reminder1_sent", texts.REMINDER_1)):
        for booking in db.due_reminders(kind, now):
            try:
                text = f"{template}\n\n{texts.booking_card(booking)}"
                await bot.send_message(
                    booking["tg_id"], text, reply_markup=booking_actions(booking["id"])
                )
            except TelegramForbiddenError:
                db.set_reinvite_opt_out_by_tg(booking["tg_id"])
            except Exception:
                logging.exception("Не удалось отправить напоминание для записи %s", booking["id"])
            else:
                db.mark_reminder_sent(booking["id"], kind)
    sender = reinvite_sender or (lambda current_bot, row: send_reinvite(current_bot, row, db))
    for booking in db.reinvites_due(now):
        try:
            sent = await sender(bot, booking)
        except TelegramForbiddenError:
            db.set_reinvite_opt_out_by_tg(booking["tg_id"])
        except Exception:
            logging.exception("Не удалось отправить приглашение для записи %s", booking["id"])
        else:
            if sent:
                with db.transaction() as conn:
                    conn.execute("UPDATE bookings SET reinvite_sent = 1 WHERE id = ?", (booking["id"],))


async def scheduler_loop(bot, db: SalonDB, master_id: int) -> None:
    while True:
        try:
            await process_pending(bot, db, master_id)
        except Exception:
            logging.exception("Ошибка фоновой обработки записей")
        await asyncio.sleep(60)
