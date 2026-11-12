from datetime import date, datetime, time, timedelta

import texts
from database import LOCAL_TZ, SalonDB, db_time, local_time, utc_now
from keyboards import inline_keyboard


def bookings_for_day(db: SalonDB, day: date):
    start = datetime.combine(day, time.min, LOCAL_TZ)
    end = start + timedelta(days=1)
    return db.conn.execute(
        """
        SELECT b.*, s.name AS service_name, s.price, s.duration_min,
               c.tg_id, c.name AS client_name, c.phone
        FROM bookings b
        JOIN services s ON s.id = b.service_id
        JOIN clients c ON c.id = b.client_id
        WHERE b.master_id = ? AND b.status = 'active'
          AND b.start_at >= ? AND b.start_at < ?
        ORDER BY b.start_at
        """,
        (db.master_id, db_time(start), db_time(end)),
    ).fetchall()


def day_card(db: SalonDB, day: date, now: datetime | None = None) -> str:
    now = now or utc_now()
    master = db.get_master()
    schedule = db.conn.execute(
        "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
        (db.master_id, day.weekday()),
    ).fetchone()
    bookings = bookings_for_day(db, day)
    blocks = db.conn.execute(
        "SELECT * FROM blocks WHERE master_id = ? AND date = ? ORDER BY start_time",
        (db.master_id, day.isoformat()),
    ).fetchall()
    booking_intervals = [
        (local_time(row["start_at"]), local_time(row["end_at"])) for row in bookings
    ]
    block_intervals = [
        (
            datetime.combine(day, time.fromisoformat(row["start_time"]), LOCAL_TZ),
            datetime.combine(day, time.fromisoformat(row["end_time"]), LOCAL_TZ),
            row["reason"] or "Блок",
        )
        for row in blocks
    ]
    break_interval = None
    if schedule and schedule["break_start"] and schedule["break_end"]:
        break_interval = (
            datetime.combine(day, time.fromisoformat(schedule["break_start"]), LOCAL_TZ),
            datetime.combine(day, time.fromisoformat(schedule["break_end"]), LOCAL_TZ),
        )

    free_slots = []
    timeline = []
    if not schedule or not schedule["is_working"]:
        timeline.append(texts.DAY_NONWORKING)
    else:
        candidate = datetime.combine(day, time.fromisoformat(schedule["work_start"]), LOCAL_TZ)
        work_end = datetime.combine(day, time.fromisoformat(schedule["work_end"]), LOCAL_TZ)
        step = timedelta(minutes=master["slot_step_min"])
        while candidate < work_end:
            candidate_end = candidate + step
            booking = next((row for row in bookings if local_time(row["start_at"]) == candidate), None)
            block = next((row for row in block_intervals if row[0] == candidate), None)
            has_break = break_interval and break_interval[0] == candidate
            overlaps_booking = any(candidate < end and start < candidate_end for start, end in booking_intervals)
            overlaps_block = any(candidate < end and start < candidate_end for start, end, _ in block_intervals)
            overlaps_break = break_interval and candidate < break_interval[1] and break_interval[0] < candidate_end
            is_free = (
                candidate_end <= work_end
                and candidate >= now + timedelta(hours=master["min_notice_hours"])
                and not overlaps_booking and not overlaps_block and not overlaps_break
            )
            if is_free:
                free_slots.append(candidate)
            label = f"{candidate:%H:%M} ━"
            if booking:
                icon = "📞" if booking["source"] == "manual" else ("🔁" if booking["source"] == "reinvite" else "📱")
                detail = f"{icon} {booking['client_name']} · {booking['service_name']}"
                if booking["source"] == "manual":
                    detail += " · Вручную"
                else:
                    detail += f" · {texts.money(booking['price'])}"
                timeline.append(f"{label} {detail}")
            elif block:
                timeline.append(f"{label} 🚫 {block[2]}")
            elif has_break:
                timeline.append(f"{label} 🍽 Перерыв")
            elif is_free:
                timeline.append(f"{label} 🟢")
            elif overlaps_booking or overlaps_block or overlaps_break:
                timeline.append(f"{label} ·")
            candidate += step

    lines = [
        texts.day_title(day, now.astimezone(LOCAL_TZ).date()),
        texts.day_summary(len(bookings), len(free_slots)),
        "",
        *timeline,
        "",
        texts.DAY_REVENUE.format(amount=texts.money(sum(row["price"] for row in bookings))),
    ]
    return "\n".join(lines)


def day_keyboard(db: SalonDB, day: date):
    today = utc_now().astimezone(LOCAL_TZ).date()
    keyboard = inline_keyboard([
        ("⬅ Вчера", f"admin_day:{(day - timedelta(days=1)).isoformat()}"),
        ("Сегодня", f"admin_day:{today.isoformat()}"),
        ("Завтра ➡", f"admin_day:{(day + timedelta(days=1)).isoformat()}"),
    ], columns=3)
    from aiogram.types import InlineKeyboardButton

    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text=texts.DAY_PICK, callback_data="admin_day_pick")
    ])
    for booking in bookings_for_day(db, day):
        local = local_time(booking["start_at"])
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"❌ {local:%H:%M} · {booking['client_name']}",
                callback_data=f"admin_cancel:{booking['id']}",
            )
        ])
    return keyboard


def week_schedule_text(db: SalonDB) -> str:
    schedules = {row["weekday"]: row for row in db.get_schedules()}
    lines = [texts.WEEK_SCHEDULE_TITLE, ""]
    for weekday, name in enumerate(texts.WEEKDAYS):
        row = schedules.get(weekday)
        if not row:
            value = "не настроено"
        elif not row["is_working"]:
            value = "выходной"
        else:
            value = f"{row['work_start']}–{row['work_end']}"
            if row["break_start"] and row["break_end"]:
                value += f"  🍽 {row['break_start']}–{row['break_end']}"
        lines.append(f"{name}  {value}")
    return "\n".join(lines)
