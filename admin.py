import logging
import re
from datetime import date, datetime, time, timedelta
from functools import wraps

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.methods import DeleteMessage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message

import texts
from client import valid_name, valid_phone
from database import LOCAL_TZ, SalonDB, SlotUnavailable, utc_now
from demo import cleanup_demo_data, create_busy_demo_day, run_client_demo, run_demo_scenario
from day_widget import refresh_open_day, send_day_widget
from keyboards import inline_keyboard, master_reply_menu, next_step_keyboard
from views import day_card, day_keyboard, week_schedule_keyboard, week_schedule_text

router = Router()


class MasterOnly(BaseFilter):
    async def __call__(self, event, master_id: int) -> bool:
        return bool(event.from_user and event.from_user.id == master_id)


router.message.filter(MasterOnly())
router.callback_query.filter(MasterOnly())

MENU_LABELS = frozenset({
    texts.MASTER_BOOKINGS, texts.MASTER_ADD, texts.MASTER_BLOCK,
    texts.MASTER_SERVICES, texts.MASTER_SCHEDULE, texts.MASTER_SETTINGS,
    texts.MASTER_LINK, texts.MASTER_STATS, texts.MASTER_DEMO,
})


async def dispatch_menu_action(message, state, db, bot=None, master_id=None):
    actions = {
        texts.MASTER_BOOKINGS: lambda: bookings(message, db, bot),
        texts.MASTER_ADD: lambda: manual_start(message, db),
        texts.MASTER_BLOCK: lambda: block_start(message, state),
        texts.MASTER_SERVICES: lambda: services(message, db),
        texts.MASTER_SCHEDULE: lambda: schedule(message, db),
        texts.MASTER_SETTINGS: lambda: settings(message, db),
        texts.MASTER_LINK: lambda: my_link(message, bot, db),
        texts.MASTER_STATS: lambda: statistics(message, db),
        texts.MASTER_DEMO: lambda: demo(message, db, bot, master_id or db.master_id),
    }
    await actions[message.text]()


def menu_interruptible(handler):
    @wraps(handler)
    async def wrapper(message, state, *args, **kwargs):
        db = kwargs.get("db") or (args[0] if args and isinstance(args[0], SalonDB) else None)
        text = getattr(message, "text", None)
        if text in MENU_LABELS and db is not None and await state.get_state() is not None:
            await state.clear()
            return await dispatch_menu_action(
                message, state, db,
                bot=kwargs.get("bot"), master_id=kwargs.get("master_id"),
            )
        return await handler(message, state, *args, **kwargs)
    return wrapper


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


async def edit_callback_message(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=reply_markup)


async def present(event, text: str, reply_markup=None) -> None:
    if isinstance(event, CallbackQuery) or hasattr(event, "message"):
        await edit_callback_message(event, text, reply_markup)
    else:
        await event.answer(text, reply_markup=reply_markup)


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
    sections = [("all", "За всё время")]
    if stats["all"] != stats["last30"]:
        sections.append(("last30", "За 30 дней"))
    for key, title in sections:
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


async def show_day(event, db: SalonDB, day: date, bot) -> None:
    if not hasattr(event, "message"):
        await send_day_widget(bot, db, day, event.from_user.id)
        return
    if getattr(event.message, "widget", None):
        try:
            await send_day_widget(bot, db, day, event.from_user.id, fallback=False)
        except Exception:
            logging.exception("Не удалось отправить виджет дня при навигации")
            await present(event, day_card(db, day), day_keyboard(db, day))
        else:
            try:
                await bot(DeleteMessage(
                    chat_id=event.message.chat.id, message_id=event.message.message_id
                ))
            except Exception:
                pass
        return
    await present(event, day_card(db, day), day_keyboard(db, day))


@menu_interruptible
@router.message(CommandStart())
@menu_interruptible
@router.message(Command("menu"))
@menu_interruptible
@router.message(F.text == "Меню")
async def admin_start(message: Message, state: FSMContext, db: SalonDB) -> None:
    await state.clear()
    db.update_master(username=message.from_user.username)
    await message.answer(menu_title(db), reply_markup=master_reply_menu())


@router.callback_query(F.data == "admin_menu")
async def admin_back(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    await state.clear()
    await edit_callback_message(callback, menu_title(db), reply_markup=admin_menu(db))
    await callback.answer()


@router.callback_query(F.data == "admin_link")
@menu_interruptible
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
@menu_interruptible
@router.message(F.text == texts.MASTER_BOOKINGS)
async def bookings(event, db: SalonDB, bot) -> None:
    day = utc_now().astimezone(LOCAL_TZ).date()
    await show_day(event, db, day, bot)
    await acknowledge(event)


@router.callback_query(F.data.startswith("admin_day:"))
@router.callback_query(F.data.startswith("admin_pick_day:"))
async def day_navigation(callback: CallbackQuery, db: SalonDB, bot) -> None:
    day = date.fromisoformat(callback.data.split(":")[1])
    await show_day(callback, db, day, bot)
    await callback.answer()


@router.callback_query(F.data == "admin_day_pick")
async def day_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DayPickStates.day)
    today = utc_now().astimezone(LOCAL_TZ).date()
    buttons = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        buttons.append((texts.format_day(day), f"admin_pick_day:{day.isoformat()}"))
    calendar_kb = inline_keyboard(buttons, columns=3)
    await edit_callback_message(callback, texts.ADMIN_BLOCK_DATE, calendar_kb)
    await callback.answer()


@menu_interruptible
@router.message(DayPickStates.day)
async def day_picked(message: Message, state: FSMContext, db: SalonDB, bot) -> None:
    try:
        day = parse_day(message.text or "")
    except ValueError:
        await message.answer(texts.ADMIN_INVALID_DATE)
        return
    await state.clear()
    await show_day(message, db, day, bot)


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
    await callback.message.answer(question, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel_no:"))
async def admin_cancel_no(callback: CallbackQuery, db: SalonDB, bot) -> None:
    await show_day(callback, db, date.fromisoformat(callback.data.split(":")[1]), bot)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel_yes:"))
async def admin_cancel_yes(callback: CallbackQuery, db: SalonDB, bot, master_id: int) -> None:
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
    await callback.message.answer(
        texts.done_text(action), reply_markup=next_step_keyboard("cancel")
    )
    await refresh_open_day(bot, db, master_id, texts.local_time(booking["start_at"]).date())
    await callback.answer()


@router.callback_query(F.data.startswith("admin_reschedule:"))
async def admin_reschedule(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    booking = db.get_booking(int(callback.data.split(":")[1]))
    if not booking or booking["status"] != "active":
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    await state.set_data({"reschedule_id": booking["id"], "service_id": booking["service_id"]})
    buttons = [
        (texts.format_day(day), f"admin_reschedule_date:{day.isoformat()}")
        for day in db.available_dates(booking["service_id"])
    ]
    await edit_callback_message(callback, texts.CHOOSE_DATE, inline_keyboard(buttons, columns=3))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_reschedule_date:"))
async def admin_reschedule_date(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    data = await state.get_data()
    day = date.fromisoformat(callback.data.split(":")[1])
    buttons = [
        (f"{texts.local_time(slot.isoformat()):%H:%M}", f"admin_reschedule_time:{slot.isoformat()}")
        for slot in db.available_slots(data["service_id"], day)
    ]
    await edit_callback_message(callback, texts.CHOOSE_TIME, inline_keyboard(buttons, columns=4))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_reschedule_time:"))
async def admin_reschedule_time(callback: CallbackQuery, state: FSMContext, db: SalonDB, bot, master_id: int) -> None:
    data = await state.get_data()
    old = db.get_booking(data["reschedule_id"])
    try:
        new_id = db.reschedule_booking(old["id"], datetime.fromisoformat(callback.data.split(":", 1)[1]))
    except (ValueError, SlotUnavailable):
        await callback.answer(texts.SLOT_TAKEN, show_alert=True)
        return
    booking = db.get_booking(new_id)
    await state.clear()
    if booking["tg_id"]:
        try:
            await bot.send_message(booking["tg_id"], texts.confirmation(booking))
        except TelegramAPIError:
            logging.exception("Не удалось уведомить клиента о переносе")
    await edit_callback_message(
        callback, texts.done_text("запись перенесена"), next_step_keyboard("schedule")
    )
    await refresh_open_day(bot, db, master_id, texts.local_time(old["start_at"]).date())
    await refresh_open_day(bot, db, master_id, texts.local_time(booking["start_at"]).date())
    await callback.answer()


@router.callback_query(F.data == "admin_manual")
@menu_interruptible
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
    await edit_callback_message(callback, texts.CHOOSE_DATE, reply_markup=inline_keyboard(buttons, columns=3))
    await callback.answer()


@router.callback_query(F.data.startswith("manual_date:"))
async def manual_date(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    data = await state.get_data()
    day = date.fromisoformat(callback.data.split(":")[1])
    buttons = [
        (f"{texts.local_time(slot.isoformat()):%H:%M}", f"manual_time:{slot.isoformat()}")
        for slot in db.available_slots(data["service_id"], day)
    ]
    await edit_callback_message(callback, texts.CHOOSE_TIME, reply_markup=inline_keyboard(buttons, columns=4))
    await callback.answer()


@router.callback_query(F.data.startswith("manual_time:"))
async def manual_time(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(start_at=callback.data.split(":", 1)[1])
    await state.set_state(ManualStates.name)
    await edit_callback_message(callback, texts.ADMIN_MANUAL_NAME)
    await callback.answer()


@menu_interruptible
@router.message(ManualStates.name)
async def manual_name(message: Message, state: FSMContext) -> None:
    if not valid_name(message.text or ""):
        await message.answer(texts.INVALID_NAME)
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(ManualStates.phone)
    await message.answer(texts.ADMIN_MANUAL_PHONE)


@menu_interruptible
@router.message(ManualStates.phone)
async def manual_phone(message: Message, state: FSMContext, db: SalonDB, bot, master_id: int) -> None:
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
    await refresh_open_day(bot, db, master_id, texts.local_time(booking["start_at"]).date())


@router.callback_query(F.data == "admin_block")
@menu_interruptible
@router.message(F.text == texts.MASTER_BLOCK)
async def block_start(event, state: FSMContext) -> None:
    await state.set_state(BlockStates.day)
    await present(event, texts.ADMIN_BLOCK_DATE)
    await acknowledge(event)


@menu_interruptible
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


@menu_interruptible
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


@menu_interruptible
@router.message(BlockStates.reason)
async def block_reason(message: Message, state: FSMContext, db: SalonDB, bot, master_id: int) -> None:
    data = await state.get_data()
    reason = (message.text or "").strip()
    db.add_block(
        date.fromisoformat(data["day"]), data["start_time"], data["end_time"],
        None if reason.lower() in {"", "-", "нет"} else reason,
    )
    await state.clear()
    action = f"время заблокировано: {texts.format_day(date.fromisoformat(data['day']))}, {data['start_time']}–{data['end_time']}"
    await message.answer(texts.done_text(action), reply_markup=next_step_keyboard("block"))
    await refresh_open_day(bot, db, master_id, date.fromisoformat(data["day"]))


@router.callback_query(F.data == "admin_services")
@menu_interruptible
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
    await edit_callback_message(callback, texts.done_text(action), reply_markup=next_step_keyboard("service"))
    await callback.answer()


@router.callback_query(F.data.startswith("service_delete:"))
async def service_delete(callback: CallbackQuery, db: SalonDB) -> None:
    db.delete_service(int(callback.data.split(":")[1]))
    await edit_callback_message(
        callback, texts.done_text("услуга удалена"), reply_markup=next_step_keyboard("service")
    )
    await callback.answer()


@router.callback_query(F.data == "service_add")
async def service_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ServiceStates.name)
    await edit_callback_message(callback, texts.ADMIN_SERVICE_NAME)
    await callback.answer()


@menu_interruptible
@router.message(ServiceStates.name)
async def service_name(message: Message, state: FSMContext) -> None:
    if not (message.text or "").strip():
        await message.answer(texts.ADMIN_SERVICE_NAME)
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(ServiceStates.price)
    await message.answer(texts.ADMIN_SERVICE_PRICE)


@menu_interruptible
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


@menu_interruptible
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
@menu_interruptible
@router.message(F.text == texts.MASTER_SCHEDULE)
async def schedule(event, db: SalonDB) -> None:
    await present(event, week_schedule_text(db), week_schedule_keyboard())
    await acknowledge(event)


@router.callback_query(F.data == "schedule_edit")
async def schedule_edit(callback: CallbackQuery) -> None:
    buttons = [
        (name, f"schedule_weekday:{weekday}")
        for weekday, name in enumerate(("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"))
    ]
    await edit_callback_message(callback, "Какой день изменить?", reply_markup=inline_keyboard(buttons, columns=2))
    await callback.answer()


@router.callback_query(F.data.startswith("schedule_weekday:"))
@router.callback_query(F.data.startswith("admin_edit_day:"))
async def schedule_weekday(callback: CallbackQuery, state: FSMContext) -> None:
    weekday = int(callback.data.split(":")[1])
    names = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
    await state.set_data({"weekday": weekday, "days": {}})
    await state.set_state(ScheduleStates.days)
    await edit_callback_message(callback, texts.ADMIN_SCHEDULE_DAY.format(day=names[weekday]))
    await callback.answer()


@menu_interruptible
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


@menu_interruptible
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
@menu_interruptible
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
    if enabled:
        db.update_master(demo_mode=1)
    else:
        cleanup_demo_data(db)
    action = "демо-режим включён" if enabled else "демо-режим выключен, демо-данные удалены"
    await edit_callback_message(callback, texts.done_text(action), reply_markup=next_step_keyboard("settings"))
    await callback.answer()


@router.callback_query(F.data.startswith("setting:"))
async def setting_start(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":")[1]
    if key not in {"reinvite_days", "min_notice_hours", "slot_step_min"}:
        await callback.answer()
        return
    await state.update_data(setting=key)
    await state.set_state(SettingStates.value)
    await edit_callback_message(callback, texts.ADMIN_SETTING_VALUE)
    await callback.answer()


@menu_interruptible
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
@menu_interruptible
@router.message(F.text == texts.MASTER_STATS)
async def statistics(event, db: SalonDB) -> None:
    await present(event, stats_text(db), inline_keyboard([("← Меню", "admin_menu")]))
    await acknowledge(event)


@router.callback_query(F.data == "admin_demo")
@menu_interruptible
@router.message(F.text == texts.MASTER_DEMO)
async def demo(event, db: SalonDB, bot, master_id: int) -> None:
    keyboard = inline_keyboard([
        (texts.DEMO_FULL, "demo_full"),
        (texts.DEMO_BUSY, "demo_busy"),
        (texts.DEMO_CLIENT, "demo_client"),
        (texts.DEMO_DISABLE, "demo_disable"),
    ])
    await present(event, texts.DEMO_MENU, keyboard)
    await acknowledge(event)


@router.callback_query(F.data == "demo_full")
async def demo_full(callback: CallbackQuery, db: SalonDB, bot, master_id: int) -> None:
    try:
        run_demo_scenario(bot, db, master_id)
    except SlotUnavailable as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    action = "полный прогон запущен: запись — 10 секунд, напоминание — 20, возврат — примерно 60"
    await edit_callback_message(callback, texts.done_text(action), next_step_keyboard("settings"))
    await callback.answer()


@router.callback_query(F.data == "demo_busy")
async def demo_busy(callback: CallbackQuery, db: SalonDB, bot, master_id: int) -> None:
    try:
        day = create_busy_demo_day(db, master_id)
    except SlotUnavailable as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await send_day_widget(bot, db, day, master_id)
    await callback.message.answer(texts.done_text("перегруженный день показан"), reply_markup=next_step_keyboard("schedule"))
    await callback.answer()


@router.callback_query(F.data == "demo_client")
async def demo_client(callback: CallbackQuery, db: SalonDB, bot, master_id: int) -> None:
    run_client_demo(bot, db, master_id)
    await edit_callback_message(callback, texts.done_text("клиентский сценарий запущен"), next_step_keyboard("settings"))
    await callback.answer()


@router.callback_query(F.data == "demo_disable")
async def demo_disable(callback: CallbackQuery, db: SalonDB) -> None:
    cleanup_demo_data(db)
    await edit_callback_message(
        callback, texts.done_text("демо-режим выключен, демо-данные удалены"),
        next_step_keyboard("settings"),
    )
    await callback.answer()
