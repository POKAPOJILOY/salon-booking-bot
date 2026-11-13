import asyncio
import logging
from datetime import date, datetime, timedelta

import texts
from database import LOCAL_TZ, SalonDB, SlotUnavailable, db_time, utc_now
from keyboards import booking_actions
from notifications import notify_master

_background_tasks = set()


def demo_service(db: SalonDB):
    rows = db.list_services()
    if rows:
        return rows[0]
    service_id = db.add_service("Маникюр (демо)", 2000, 60)
    return db.get_service(service_id)


def create_demo_data(db: SalonDB, master_id: int, now: datetime | None = None) -> tuple[int, int]:
    now = now or utc_now()
    db.update_master(demo_mode=1)
    if not db.get_schedules():
        for weekday in range(7):
            db.set_schedule(weekday, True, "10:00", "19:00", "14:00", "14:30")
    service = demo_service(db)
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
        await bot.send_message(master_id, texts.DEMO_BOOKING_NOTE)
        await asyncio.sleep(10)
        booking = db.get_booking(booking_id)
        text = f"ДЕМО · {texts.REMINDER_24}\n\n{texts.booking_card(booking)}"
        await bot.send_message(booking["tg_id"], text, reply_markup=booking_actions(booking_id))
        db.mark_reminder_sent(booking_id, "reminder24_sent")
        await bot.send_message(master_id, texts.DEMO_REMINDER_NOTE)
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


def create_busy_demo_day(db: SalonDB, master_id: int, now: datetime | None = None) -> date:
    now = now or utc_now()
    db.update_master(demo_mode=1)
    service = demo_service(db)
    if not db.get_schedules():
        for weekday in range(7):
            db.set_schedule(weekday, True, "09:00", "20:00", "14:00", "14:30")
    for offset in range(1, 8):
        day = now.astimezone(LOCAL_TZ).date() + timedelta(days=offset)
        schedule = db.conn.execute(
            "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
            (master_id, day.weekday()),
        ).fetchone()
        if not schedule or not schedule["is_working"]:
            continue
        slots = db.available_slots(service["id"], day, now)
        selected = []
        for start in slots:
            if not selected or start >= selected[-1] + timedelta(minutes=service["duration_min"]):
                selected.append(start)
            if len(selected) == 8:
                break
        if len(selected) == 8:
            break
    else:
        raise SlotUnavailable("Для перегруженного дня нужен рабочий день с восемью свободными окнами.")
    client_id = db.create_client(master_id, "Анна (демо)", "+79990000000")
    for start in selected:
        db.create_booking(client_id, service["id"], start, source="link", now=now)
    db.add_block(day, "12:30", "12:45", "ДЕМО · Звонок")
    db.add_block(day, "17:30", "17:45", "ДЕМО · Личное дело")
    return day


async def _client_demo_script(bot, db: SalonDB, master_id: int, future_id: int, completed_id: int) -> None:
    try:
        for note in (texts.DEMO_CLIENT_LINK, texts.DEMO_CLIENT_SERVICE, texts.DEMO_CLIENT_TIME):
            await bot.send_message(master_id, note)
            await asyncio.sleep(1)
        await notify_master(bot, master_id, db.get_booking(future_id), demo=True)
        await bot.send_message(master_id, texts.DEMO_CLIENT_CONFIRM)
        await asyncio.sleep(1)
        await bot.send_message(master_id, texts.DEMO_CLIENT_REMINDER)
        await asyncio.sleep(1)
        from widget import send_reinvite_message

        await send_reinvite_message(bot, db, db.get_booking(completed_id))
        await bot.send_message(master_id, texts.DEMO_CLIENT_RETURN)
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.exception("Не удалось показать клиентское демо")


def run_client_demo(bot, db: SalonDB, master_id: int) -> tuple[int, int]:
    future_id, completed_id = create_demo_data(db, master_id)
    task = asyncio.create_task(_client_demo_script(bot, db, master_id, future_id, completed_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return future_id, completed_id


def cleanup_demo_data(db: SalonDB) -> None:
    with db.transaction() as conn:
        demo_client_ids = conn.execute(
            "SELECT id FROM clients WHERE master_id = ? AND name LIKE '%(демо)%'",
            (db.master_id,),
        ).fetchall()
        ids = [row["id"] for row in demo_client_ids]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM bookings WHERE master_id = ? AND client_id IN ({placeholders})", (db.master_id, *ids))
            conn.execute(f"DELETE FROM clients WHERE master_id = ? AND id IN ({placeholders})", (db.master_id, *ids))
        conn.execute("DELETE FROM blocks WHERE master_id = ? AND reason LIKE 'ДЕМО%'", (db.master_id,))
        conn.execute("DELETE FROM services WHERE master_id = ? AND name LIKE '%(демо)%'", (db.master_id,))
    db.update_master(demo_mode=0)
    from day_widget import _day_widgets

    _day_widgets.pop(db.master_id, None)
