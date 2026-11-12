import asyncio
import logging
from datetime import datetime, timedelta

import texts
from database import LOCAL_TZ, SalonDB, SlotUnavailable, db_time, utc_now
from keyboards import booking_actions
from notifications import notify_master

_background_tasks = set()


def create_demo_data(db: SalonDB, master_id: int, now: datetime | None = None) -> tuple[int, int]:
    now = now or utc_now()
    db.update_master(demo_mode=1)
    if not db.list_services():
        db.add_service("Маникюр", 2000, 60)
    if not db.get_schedules():
        for weekday in range(7):
            db.set_schedule(weekday, True, "10:00", "19:00", "14:00", "14:30")
    service = db.list_services()[0]
    tomorrow = now.astimezone(LOCAL_TZ).date() + timedelta(days=1)
    slots = db.available_slots(service["id"], tomorrow, now)
    if not slots:
        raise SlotUnavailable("Для демо нужно свободное время завтра. Освободите хотя бы одно окно.")
    future_client = db.create_client(master_id, "Анна (демо)", "+79990000000")
    future_id = db.create_booking(future_client, service["id"], slots[0], source="link", now=now)
    completed_client = db.create_client(master_id, "Мария (демо)", "+79990000001")
    with db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at)
            VALUES (?, ?, ?, ?, ?, 'done', 'link', ?)
            """,
            (
                master_id,
                completed_client,
                service["id"],
                db_time(now - timedelta(minutes=service["duration_min"])),
                db_time(now),
                db_time(now),
            ),
        )
        completed_id = cursor.lastrowid
    return future_id, completed_id


async def _future_notifications(bot, db: SalonDB, master_id: int, booking_id: int) -> None:
    try:
        await asyncio.sleep(10)
        await notify_master(bot, master_id, db.get_booking(booking_id), demo=True)
        await asyncio.sleep(10)
        booking = db.get_booking(booking_id)
        text = f"ДЕМО · {texts.REMINDER_24}\n\n{texts.booking_card(booking)}"
        await bot.send_message(booking["tg_id"], text, reply_markup=booking_actions(booking_id))
        db.mark_reminder_sent(booking_id, "reminder24_sent")
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.exception("Не удалось выполнить демо-напоминание")


def run_demo_scenario(bot, db: SalonDB, master_id: int) -> tuple[int, int]:
    future_id, completed_id = create_demo_data(db, master_id)
    task = asyncio.create_task(_future_notifications(bot, db, master_id, future_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return future_id, completed_id
