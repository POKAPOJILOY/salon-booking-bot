import logging
import re
from datetime import date, datetime, time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message

import texts
from client import valid_name, valid_phone
from database import LOCAL_TZ, SalonDB, SlotUnavailable, utc_now
from demo import run_demo_scenario
from keyboards import inline_keyboard, master_reply_menu, next_step_keyboard
from views import bookings_for_day, day_card, day_keyboard, week_schedule_text

router = Router()


class MasterOnly(BaseFilter):
    async def __call__(self, event, master_id: int) -> bool:
        return bool(event.from_user and event.from_user.id == master_id)


router.message.filter(MasterOnly())
router.callback_query.filter(MasterOnly())


@router.message.middleware()
async def reset_reply_menu_state(handler, message: Message, data):
    menu_labels = {
        texts.MASTER_BOOKINGS, texts.MASTER_ADD, texts.MASTER_BLOCK,
        texts.MASTER_SERVICES, texts.MASTER_SCHEDULE, texts.MASTER_SETTINGS,
        texts.MASTER_LINK, texts.MASTER_STATS, texts.MASTER_DEMO,
    }
    if message.text in menu_labels:
        await data["state"].clear()
    return await handler(message, data)


class ManualStates(StatesGroup):
    name = State()
    phone = State()


class BlockStates(StatesGroup):
    day = State()
    interval = State()
    reason = State()


class ServiceStates(StatesGroup):
    name = State()
    price = State()
    duration = State()


class ScheduleStates(StatesGroup):
    days = State()
    break_time = State()


class SettingStates(StatesGroup):
    value = State()


class DayPickStates(StatesGroup):
    day = State()


def admin_menu(db: SalonDB) -> InlineKeyboardMarkup:
    buttons = [
        (texts.MASTER_LINK, "admin_link"),
        (texts.MASTER_BOOKINGS, "admin_bookings"),
        (texts.MASTER_ADD, "admin_manual"),
        (texts.MASTER_BLOCK, "admin_block"),
        (texts.MASTER_SERVICES, "admin_services"),
        (texts.MASTER_SCHEDULE, "admin_schedule"),
        (texts.MASTER_SETTINGS, "admin_settings"),
        (texts.MASTER_STATS, "admin_stats"),
        (texts.MASTER_DEMO, "admin_demo"),
    ]
    return inline_keyboard(buttons, columns=2)


def menu_title(db: SalonDB) -> str:
    return f"{'ДЕМО · ' if db.get_master()['demo_mode'] else ''}{texts.ADMIN_MENU}"


async def present(event, text: str, reply_markup=None) -> None:
    if isinstance(event, Message):
        await event.answer(text, reply_markup=reply_markup)
    else:
        await event.message.edit_text(text, reply_markup=reply_markup)


async def acknowledge(event, text: str | None = None, show_alert: bool = False) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=show_alert)


def parse_day(value: str) -> date:
    value = value.strip()
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return date.fromisoformat(value)


def parse_interval(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*", value)
    if not match:
        raise ValueError("invalid interval")
    start = time.fromisoformat(match.group(1))
    end = time.fromisoformat(match.group(2))
    if start >= end:
        raise ValueError("invalid interval")
    return start.strftime("%H:%M"), end.strftime("%H:%M")


def stats_text(db: SalonDB) -> str:
    stats = db.statistics()
    lines = [f"{'ДЕМО · ' if db.get_master()['demo_mode'] else ''}Статистика"]
    for key, title in (("all", "За всё время"), ("last30", "За 30 дней")):
        row = stats[key]
        lines.extend([
            "",
            title,
            f"Через ссылку: {row['link']}",
            f"Вручную: {row['manual']}",
            f"Вернулись по приглашению: {row['reinvite']}",
            f"Отменено: {row['cancelled']}",
            f"Напоминаний отправлено: {row['reminders']}",
            f"Выручка по завершённым визитам: {texts.money(row['revenue'])}",
        ])
    return "\n".join(lines)


async def show_day(event, db: SalonDB, day: date) -> None:
    await present(event, day_card(db, day), day_keyboard(db, day))


@router.message(CommandStart())
@router.message(Command("menu"))
@router.message(F.text == "Меню")
async def admin_start(message: Message, state: FSMContext, db: SalonDB) -> None:
    await state.clear()
    db.update_master(username=message.from_user.username)
    await message.answer(menu_title(db), reply_markup=master_reply_menu())


@router.callback_query(F.data == "admin_menu")
async def admin_back(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    await state.clear()
    await callback.message.edit_text(menu_title(db), reply_markup=admin_menu(db))
    await callback.answer()


@router.callback_query(F.data == "admin_link")
@router.message(F.text == texts.MASTER_LINK)
async def my_link(event, bot, db: SalonDB) -> None:
    me = await bot.get_me()
    link = f"https://t.me/{me.username}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скопировать", copy_text=CopyTextButton(text=link))],
        [InlineKeyboardButton(text="← Меню", callback_data="admin_menu")],
    ])
    await present(event, f"{texts.ADMIN_LINK}\n{link}", keyboard)
    await acknowledge(event)


@router.callback_query(F.data == "admin_bookings")
@router.message(F.text == texts.MASTER_BOOKINGS)
async def bookings(event, db: SalonDB) -> None:
    day = utc_now().astimezone(LOCAL_TZ).date()
    await show_day(event, db, day)
    await acknowledge(event)


@router.callback_query(F.data.startswith("admin_day:"))
async def day_navigation(callback: CallbackQuery, db: SalonDB) -> None:
    day = date.fromisoformat(callback.data.split(":")[1])
    await show_day(callback, db, day)
    await callback.answer()


@router.callback_query(F.data == "admin_day_pick")
async def day_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DayPickStates.day)
    await callback.message.edit_text(texts.ADMIN_BLOCK_DATE)
    await callback.answer()


@router.message(DayPickStates.day)
async def day_picked(message: Message, state: FSMContext, db: SalonDB) -> None:
    try:
        day = parse_day(message.text or "")
    except ValueError:
        await message.answer(texts.ADMIN_INVALID_DATE)
        return
    await state.clear()
    await show_day(message, db, day)


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel(callback: CallbackQuery, db: SalonDB) -> None:
    booking = db.get_booking(int(callback.data.split(":")[1]))
    if not booking or booking["status"] != "active":
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    keyboard = inline_keyboard([
        ("Да, отменить", f"admin_cancel_yes:{booking['id']}"),
        (texts.CANCEL_KEEP, f"admin_cancel_no:{texts.local_time(booking['start_at']).date().isoformat()}"),
    ])
    question = texts.CANCEL_CONFIRM_ADMIN.format(
        client=booking["client_name"], slot=texts.format_slot(booking["start_at"])
    )
    await callback.message.edit_text(question, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel_no:"))
async def admin_cancel_no(callback: CallbackQuery, db: SalonDB) -> None:
    await show_day(callback, db, date.fromisoformat(callback.data.split(":")[1]))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel_yes:"))
async def admin_cancel_yes(callback: CallbackQuery, db: SalonDB, bot) -> None:
    try:
        booking = db.cancel_booking(int(callback.data.split(":")[1]))
    except ValueError:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    if booking["tg_id"]:
        try:
            await bot.send_message(booking["tg_id"], texts.ADMIN_CLIENT_CANCELLED)
        except TelegramAPIError:
            logging.exception("Не удалось уведомить клиента об отмене")
    action = f"запись отменена: {booking['client_name']}, {texts.format_slot(booking['start_at'])}"
    await callback.message.edit_text(
        texts.done_text(action), reply_markup=next_step_keyboard("cancel")
    )
    await callback.answer()


@router.callback_query(F.data == "admin_manual")
@router.message(F.text == texts.MASTER_ADD)
async def manual_start(event, db: SalonDB) -> None:
    await present(
        event,
        texts.CHOOSE_SERVICE,
        inline_keyboard([
            (f"{row['name']} · {row['duration_min']} мин", f"manual_service:{row['id']}")
            for row in db.list_services()
        ]),
    )
    await acknowledge(event)


@router.callback_query(F.data.startswith("manual_service:"))
async def manual_service(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    service_id = int(callback.data.split(":")[1])
    await state.update_data(service_id=service_id)
    buttons = [(texts.format_day(day), f"manual_date:{day.isoformat()}") for day in db.available_dates(service_id)]
    await callback.message.edit_text(texts.CHOOSE_DATE, reply_markup=inline_keyboard(buttons, columns=3))
    await callback.answer()


@router.callback_query(F.data.startswith("manual_date:"))
async def manual_date(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    data = await state.get_data()
    day = date.fromisoformat(callback.data.split(":")[1])
    buttons = [
        (f"{texts.local_time(slot.isoformat()):%H:%M}", f"manual_time:{slot.isoformat()}")
        for slot in db.available_slots(data["service_id"], day)
    ]
    await callback.message.edit_text(texts.CHOOSE_TIME, reply_markup=inline_keyboard(buttons, columns=4))
    await callback.answer()


@router.callback_query(F.data.startswith("manual_time:"))
async def manual_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(start_at=callback.data.split(":", 1)[1])
    await state.set_state(ManualStates.name)
    await callback.message.edit_text(texts.ADMIN_MANUAL_NAME)
    await callback.answer()


@router.message(ManualStates.name)
async def manual_name(message: Message, state: FSMContext) -> None:
    if not valid_name(message.text or ""):
        await message.answer(texts.INVALID_NAME)
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(ManualStates.phone)
    await message.answer(texts.ADMIN_MANUAL_PHONE)


@router.message(ManualStates.phone)
async def manual_phone(message: Message, state: FSMContext, db: SalonDB) -> None:
    if not valid_phone(message.text or ""):
        await message.answer(texts.INVALID_PHONE)
        return
    data = await state.get_data()
    client_id = db.create_client(None, data["name"], message.text.strip())
    try:
        booking_id = db.create_booking(
            client_id, data["service_id"], datetime.fromisoformat(data["start_at"]), source="manual"
        )
    except SlotUnavailable:
        await message.answer(texts.SLOT_TAKEN)
        return
    await state.clear()
    booking = db.get_booking(booking_id)
    action = f"запись создана: {booking['client_name']}, {booking['service_name']}, {texts.format_slot(booking['start_at'])}"
    await message.answer(texts.done_text(action), reply_markup=next_step_keyboard("booking"))


@router.callback_query(F.data == "admin_block")
@router.message(F.text == texts.MASTER_BLOCK)
async def block_start(event, state: FSMContext) -> None:
    await state.set_state(BlockStates.day)
    await present(event, texts.ADMIN_BLOCK_DATE)
    await acknowledge(event)


@router.message(BlockStates.day)
async def block_day(message: Message, state: FSMContext) -> None:
    try:
        day = parse_day(message.text or "")
    except ValueError:
        await message.answer(texts.ADMIN_INVALID_DATE)
        return
    await state.update_data(day=day.isoformat())
    await state.set_state(BlockStates.interval)
    await message.answer(texts.ADMIN_BLOCK_INTERVAL)


@router.message(BlockStates.interval)
async def block_interval(message: Message, state: FSMContext) -> None:
    try:
        start, end = parse_interval(message.text or "")
    except ValueError:
        await message.answer(texts.ADMIN_INVALID_INTERVAL)
        return
    await state.update_data(start_time=start, end_time=end)
    await state.set_state(BlockStates.reason)
    await message.answer(texts.ADMIN_BLOCK_REASON)


@router.message(BlockStates.reason)
async def block_reason(message: Message, state: FSMContext, db: SalonDB) -> None:
    data = await state.get_data()
    reason = (message.text or "").strip()
    db.add_block(
        date.fromisoformat(data["day"]), data["start_time"], data["end_time"],
        None if reason.lower() in {"", "-", "нет"} else reason,
    )
    await state.clear()
    action = f"время заблокировано: {texts.format_day(date.fromisoformat(data['day']))}, {data['start_time']}–{data['end_time']}"
    await message.answer(texts.done_text(action), reply_markup=next_step_keyboard("block"))


@router.callback_query(F.data == "admin_services")
@router.message(F.text == texts.MASTER_SERVICES)
async def services(event, db: SalonDB) -> None:
    rows = db.list_services(include_inactive=True)
    lines = [f"{'ДЕМО · ' if db.get_master()['demo_mode'] else ''}Мои услуги"]
    buttons = [("Добавить услугу", "service_add")]
    for service in rows:
        status = "вкл" if service["is_active"] else "выкл"
        lines.append(f"{service['name']} · {texts.money(service['price'])} · {service['duration_min']} мин · {status}")
        buttons.append((f"{'Выключить' if service['is_active'] else 'Включить'}: {service['name']}", f"service_toggle:{service['id']}:{not service['is_active']}"))
        if service["is_active"]:
            buttons.append((f"Удалить: {service['name']}", f"service_delete:{service['id']}"))
    buttons.append(("← Меню", "admin_menu"))
    await present(event, "\n".join(lines), inline_keyboard(buttons))
    await acknowledge(event)


@router.callback_query(F.data.startswith("service_toggle:"))
async def service_toggle(callback: CallbackQuery, db: SalonDB) -> None:
    _, service_id, active = callback.data.split(":")
    db.set_service_active(int(service_id), active == "True")
    action = "услуга включена" if active == "True" else "услуга выключена"
    await callback.message.edit_text(texts.done_text(action), reply_markup=next_step_keyboard("service"))
    await callback.answer()


@router.callback_query(F.data.startswith("service_delete:"))
async def service_delete(callback: CallbackQuery, db: SalonDB) -> None:
    db.delete_service(int(callback.data.split(":")[1]))
    await callback.message.edit_text(
        texts.done_text("услуга удалена"), reply_markup=next_step_keyboard("service")
    )
    await callback.answer()


@router.callback_query(F.data == "service_add")
async def service_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ServiceStates.name)
    await callback.message.edit_text(texts.ADMIN_SERVICE_NAME)
    await callback.answer()


@router.message(ServiceStates.name)
async def service_name(message: Message, state: FSMContext) -> None:
    if not (message.text or "").strip():
        await message.answer(texts.ADMIN_SERVICE_NAME)
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(ServiceStates.price)
    await message.answer(texts.ADMIN_SERVICE_PRICE)


@router.message(ServiceStates.price)
async def service_price(message: Message, state: FSMContext) -> None:
    try:
        price = int(message.text or "")
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer(texts.ADMIN_SERVICE_PRICE)
        return
    await state.update_data(price=price)
    await state.set_state(ServiceStates.duration)
    await message.answer(texts.ADMIN_SERVICE_DURATION)


@router.message(ServiceStates.duration)
async def service_duration(message: Message, state: FSMContext, db: SalonDB) -> None:
    try:
        duration = int(message.text or "")
        if duration <= 0:
            raise ValueError
    except ValueError:
        await message.answer(texts.ADMIN_SERVICE_DURATION)
        return
    data = await state.get_data()
    db.add_service(data["name"], data["price"], duration)
    await state.clear()
    await message.answer(texts.done_text("услуга сохранена"), reply_markup=next_step_keyboard("service"))


@router.callback_query(F.data == "admin_schedule")
@router.message(F.text == texts.MASTER_SCHEDULE)
async def schedule(event, db: SalonDB) -> None:
    keyboard = inline_keyboard([
        ("✏️ Изменить день", "schedule_edit"),
        ("← Меню", "admin_menu"),
    ])
    await present(event, week_schedule_text(db), keyboard)
    await acknowledge(event)


@router.callback_query(F.data == "schedule_edit")
async def schedule_edit(callback: CallbackQuery) -> None:
    buttons = [
        (name, f"schedule_weekday:{weekday}")
        for weekday, name in enumerate(("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"))
    ]
    await callback.message.edit_text("Какой день изменить?", reply_markup=inline_keyboard(buttons, columns=2))
    await callback.answer()


@router.callback_query(F.data.startswith("schedule_weekday:"))
async def schedule_weekday(callback: CallbackQuery, state: FSMContext) -> None:
    weekday = int(callback.data.split(":")[1])
    names = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
    await state.set_data({"weekday": weekday, "days": {}})
    await state.set_state(ScheduleStates.days)
    await callback.message.edit_text(texts.ADMIN_SCHEDULE_DAY.format(day=names[weekday]))
    await callback.answer()


@router.message(ScheduleStates.days)
async def schedule_day(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    weekday = data["weekday"]
    value = (message.text or "").strip()
    if value.lower() == "выходной":
        work_start, work_end, working = "10:00", "19:00", False
    else:
        try:
            work_start, work_end = parse_interval(value)
            working = True
        except ValueError:
            await message.answer(texts.ADMIN_INVALID_INTERVAL)
            return
    await state.update_data(days={str(weekday): {"working": working, "start": work_start, "end": work_end}})
    await state.set_state(ScheduleStates.break_time)
    await message.answer(texts.ADMIN_SCHEDULE_BREAK)


@router.message(ScheduleStates.break_time)
async def schedule_break(message: Message, state: FSMContext, db: SalonDB) -> None:
    value = (message.text or "").strip()
    if value.lower() in {"нет", "-", ""}:
        break_start = break_end = None
    else:
        try:
            break_start, break_end = parse_interval(value)
        except ValueError:
            await message.answer(texts.ADMIN_INVALID_INTERVAL)
            return
    data = await state.get_data()
    changed = {int(key): value for key, value in data["days"].items()}
    existing = {row["weekday"]: row for row in db.get_schedules()}
    for weekday in range(7):
        if weekday in changed:
            row = changed[weekday]
            working, work_start, work_end = row["working"], row["start"], row["end"]
        elif weekday in existing:
            row = existing[weekday]
            working, work_start, work_end = row["is_working"], row["work_start"], row["work_end"]
        else:
            working, work_start, work_end = False, "10:00", "19:00"
        db.set_schedule(weekday, working, work_start, work_end, break_start, break_end)
    await state.clear()
    await message.answer(texts.done_text("расписание сохранено"), reply_markup=next_step_keyboard("schedule"))


@router.callback_query(F.data == "admin_settings")
@router.message(F.text == texts.MASTER_SETTINGS)
async def settings(event, db: SalonDB) -> None:
    master = db.get_master()
    text = (
        f"{'ДЕМО · ' if master['demo_mode'] else ''}Настройки\n"
        f"Повторное приглашение: {master['reinvite_days']} дней\n"
        f"Минимум до записи: {master['min_notice_hours']} часов\n"
        f"Шаг слотов: {master['slot_step_min']} минут\n"
        f"Демо-режим: {'включён' if master['demo_mode'] else 'выключен'}"
    )
    buttons = [
        ("Интервал приглашения", "setting:reinvite_days"),
        ("Минимум до записи", "setting:min_notice_hours"),
        ("Шаг слотов", "setting:slot_step_min"),
        (f"{'Выключить' if master['demo_mode'] else 'Включить'} ДЕМО", "demo_toggle"),
        ("← Меню", "admin_menu"),
    ]
    await present(event, text, inline_keyboard(buttons, columns=2))
    await acknowledge(event)


@router.callback_query(F.data == "demo_toggle")
async def demo_toggle(callback: CallbackQuery, db: SalonDB) -> None:
    enabled = not db.get_master()["demo_mode"]
    db.update_master(demo_mode=enabled)
    action = "демо-режим включён" if enabled else "демо-режим выключен"
    await callback.message.edit_text(texts.done_text(action), reply_markup=next_step_keyboard("settings"))
    await callback.answer()


@router.callback_query(F.data.startswith("setting:"))
async def setting_start(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":")[1]
    if key not in {"reinvite_days", "min_notice_hours", "slot_step_min"}:
        await callback.answer()
        return
    await state.update_data(setting=key)
    await state.set_state(SettingStates.value)
    await callback.message.edit_text(texts.ADMIN_SETTING_VALUE)
    await callback.answer()


@router.message(SettingStates.value)
async def setting_value(message: Message, state: FSMContext, db: SalonDB) -> None:
    data = await state.get_data()
    limits = {"reinvite_days": (1, 365), "min_notice_hours": (0, 72), "slot_step_min": (5, 180)}
    try:
        value = int(message.text or "")
        low, high = limits[data["setting"]]
        if not low <= value <= high:
            raise ValueError
    except (ValueError, KeyError):
        await message.answer(texts.ADMIN_SETTING_VALUE)
        return
    db.update_master(**{data["setting"]: value})
    await state.clear()
    await message.answer(texts.done_text("настройка сохранена"), reply_markup=next_step_keyboard("settings"))


@router.callback_query(F.data == "admin_stats")
@router.message(F.text == texts.MASTER_STATS)
async def statistics(event, db: SalonDB) -> None:
    await present(event, stats_text(db), inline_keyboard([("← Меню", "admin_menu")]))
    await acknowledge(event)


@router.callback_query(F.data == "admin_demo")
@router.message(F.text == texts.MASTER_DEMO)
async def demo(event, db: SalonDB, bot, master_id: int) -> None:
    try:
        run_demo_scenario(bot, db, master_id)
    except SlotUnavailable as exc:
        if isinstance(event, Message):
            await event.answer(str(exc))
        else:
            await acknowledge(event, str(exc), show_alert=True)
        return
    action = "демо запущено. Новая запись — через 10 секунд, напоминание — через 20, приглашение — примерно через 60"
    await present(event, texts.done_text(action), next_step_keyboard("settings"))
    await acknowledge(event)
