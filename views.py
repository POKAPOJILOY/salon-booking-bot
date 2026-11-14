from datetime import date, datetime, time, timedelta

from aiogram.types import InlineKeyboardButton, WebAppInfo

import config
import texts
from database import LOCAL_TZ, SalonDB, db_time, local_time, utc_now
from keyboards import inline_keyboard


CLOCK_HOUR = ("🕛", "🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚")
CLOCK_HALF = ("🕧", "🕜", "🕝", "🕞", "🕟", "🕠", "🕡", "🕢", "🕣", "🕤", "🕥", "🕦")
SOURCE_ICONS = {"link": "📱", "manual": "✍️", "reinvite": "🔁"}
MAX_CARD_LINES = 25


def clock_emoji(value: datetime) -> str:
    return (CLOCK_HALF if value.minute >= 30 else CLOCK_HOUR)[value.hour % 12]


def compress_free_slots(slots: list[datetime], step: timedelta) -> list[dict]:
    ranges = []
    for slot in sorted(slots):
        if ranges and slot == ranges[-1]["_end"]:
            ranges[-1]["_end"] = slot + step
            ranges[-1]["end"] = f"{slot + step:%H:%M}"
        else:
            ranges.append({"type": "free", "start": f"{slot:%H:%M}", "end": f"{slot + step:%H:%M}", "_end": slot + step})
    for item in ranges:
        del item["_end"]
    return ranges


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


def free_slots_for_day(db: SalonDB, day: date, now: datetime | None = None) -> list[datetime]:
    now = now or utc_now()
    master = db.get_master()
    schedule = db.conn.execute(
        "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
        (db.master_id, day.weekday()),
    ).fetchone()
    if not schedule or not schedule["is_working"]:
        return []
    bookings = bookings_for_day(db, day)
    booking_intervals = [(local_time(row["start_at"]), local_time(row["end_at"])) for row in bookings]
    blocks = db.conn.execute(
        "SELECT * FROM blocks WHERE master_id = ? AND date = ?",
        (db.master_id, day.isoformat()),
    ).fetchall()
    block_intervals = [
        (
            datetime.combine(day, time.fromisoformat(row["start_time"]), LOCAL_TZ),
            datetime.combine(day, time.fromisoformat(row["end_time"]), LOCAL_TZ),
        )
        for row in blocks
    ]
    break_interval = None
    if schedule["break_start"] and schedule["break_end"]:
        break_interval = (
            datetime.combine(day, time.fromisoformat(schedule["break_start"]), LOCAL_TZ),
            datetime.combine(day, time.fromisoformat(schedule["break_end"]), LOCAL_TZ),
        )
    candidate = datetime.combine(day, time.fromisoformat(schedule["work_start"]), LOCAL_TZ)
    work_end = datetime.combine(day, time.fromisoformat(schedule["work_end"]), LOCAL_TZ)
    step = timedelta(minutes=master["slot_step_min"])
    result = []
    while candidate < work_end:
        candidate_end = candidate + step
        overlaps_booking = any(candidate < end and start < candidate_end for start, end in booking_intervals)
        overlaps_block = any(candidate < end and start < candidate_end for start, end in block_intervals)
        overlaps_break = break_interval and candidate < break_interval[1] and break_interval[0] < candidate_end
        if (
            candidate_end <= work_end
            and candidate >= now + timedelta(hours=master["min_notice_hours"])
            and not overlaps_booking and not overlaps_block and not overlaps_break
        ):
            result.append(candidate)
        candidate += step
    return result


def day_card(db: SalonDB, day: date, now: datetime | None = None) -> str:
    now = now or utc_now()
    master = db.get_master()
    schedule = db.conn.execute(
        "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
        (db.master_id, day.weekday()),
    ).fetchone()
    bookings = bookings_for_day(db, day)
    free_slots = free_slots_for_day(db, day, now)
    lines = [
        texts.day_title(day, now.astimezone(LOCAL_TZ).date()),
        texts.day_summary(len(bookings), len(free_slots)),
        "",
    ]
    if not schedule or not schedule["is_working"]:
        lines.append(texts.DAY_NONWORKING)
    else:
        for booking in bookings:
            start = local_time(booking["start_at"])
            end = local_time(booking["end_at"])
            icon = SOURCE_ICONS.get(booking["source"], "📱")
            lines.append(
                f"{clock_emoji(start)} {start:%H:%M}–{end:%H:%M} · {booking['client_name']}"
                f" · {booking['service_name']} · {texts.money(booking['price'])} {icon}"
            )
        free_ranges = compress_free_slots(free_slots, timedelta(minutes=master["slot_step_min"]))
        blocks = db.conn.execute(
            "SELECT * FROM blocks WHERE master_id = ? AND date = ? ORDER BY start_time",
            (db.master_id, day.isoformat()),
        ).fetchall()
        if free_slots:
            full = "🟢 Свободно: " + ", ".join(
                f"{item['start']}–{item['end']}" for item in free_ranges
            )
            collapsed = (
                f"🟢 Свободно: {len(free_slots)} "
                f"{texts.plural(len(free_slots), 'окно', 'окна', 'окон')} "
                f"по {master['slot_step_min']} мин "
                f"({free_ranges[0]['start']}–{free_ranges[0]['end']} и ещё)"
            )
            prospective = len(lines) + 1 + len(blocks) + 2
            if schedule["break_start"] and schedule["break_end"]:
                prospective += 1
            lines.append(collapsed if prospective > MAX_CARD_LINES else full)
        if schedule["break_start"] and schedule["break_end"]:
            lines.append(f"☕ Перерыв {schedule['break_start']}–{schedule['break_end']}")
        for block in blocks:
            lines.append(f"🚫 {block['reason'] or 'Блок'} {block['start_time']}–{block['end_time']}")
    lines += [
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
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text=texts.DAY_PICK, callback_data="admin_day_pick")
    ])
    if config.WEBAPP_PUBLIC_URL:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text="🗓 Открыть день",
                web_app=WebAppInfo(url=f"{config.WEBAPP_PUBLIC_URL}/app/master?date={day.isoformat()}"),
            )
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


def week_schedule_text(db: SalonDB, today: date | None = None) -> str:
    schedules = {row["weekday"]: row for row in db.get_schedules()}
    groups = []
    for weekday in range(7):
        row = schedules.get(weekday)
        if not row:
            signature = ("unset",)
        elif not row["is_working"]:
            signature = ("off",)
        else:
            signature = (
                "working", row["work_start"], row["work_end"],
                row["break_start"], row["break_end"],
            )
        if groups and groups[-1][0] == signature:
            groups[-1][2] = weekday
        else:
            groups.append([signature, weekday, weekday])
    today = today or utc_now().astimezone(LOCAL_TZ).date()
    lines = [texts.WEEK_SCHEDULE_TITLE, ""]
    for signature, first, last in groups:
        label = texts.WEEKDAYS[first] if first == last else f"{texts.WEEKDAYS[first]}–{texts.WEEKDAYS[last]}"
        if signature[0] == "unset":
            value = "не настроено"
        elif signature[0] == "off":
            value = "выходной"
        else:
            value = f"{signature[1]}–{signature[2]}"
            if signature[3] and signature[4]:
                value += f" · перерыв {signature[3]}–{signature[4]}"
        marker = "   ← сегодня" if first <= today.weekday() <= last else ""
        lines.append(f"{label} — {value}{marker}")
    return "\n".join(lines)


def week_schedule_keyboard():
    keyboard = inline_keyboard([
        (name, f"admin_edit_day:{weekday}")
        for weekday, name in enumerate(texts.WEEKDAYS)
    ], columns=7)
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="← Меню", callback_data="admin_menu")
    ])
    return keyboard
