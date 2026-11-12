import re
from datetime import date, datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import texts
from database import SalonDB, SlotUnavailable
from keyboards import (
    booking_actions,
    client_reply_menu,
    dates_keyboard,
    inline_keyboard,
    next_step_keyboard,
    phone_keyboard,
    services_keyboard,
    times_keyboard,
)
from notifications import notify_master
from day_widget import send_day_widget

router = Router()


async def refresh_master_day(bot, db: SalonDB, master_id: int, booking) -> None:
    await send_day_widget(bot, db, texts.local_time(booking["start_at"]).date(), master_id)


@router.message.middleware()
async def reset_reply_menu_state(handler, message: Message, data):
    if message.text in {texts.CLIENT_BOOK, texts.CLIENT_BOOKINGS}:
        await data["state"].clear()
    return await handler(message, data)


class BookingStates(StatesGroup):
    service = State()
    day = State()
    time = State()
    name = State()
    phone = State()
    confirm = State()


def valid_name(value: str) -> bool:
    value = value.strip()
    return 1 <= len(value) <= 80 and any(char.isalpha() for char in value) and all(
        char.isalpha() or char in " -" for char in value
    )


def valid_phone(value: str) -> bool:
    return 10 <= len(re.sub(r"\D", "", value)) <= 15


async def answer_or_edit(message, text: str, reply_markup, new_message: bool = False) -> None:
    if new_message:
        await message.answer(text, reply_markup=reply_markup)
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup)


async def show_services(message, state: FSMContext, db: SalonDB, edit: bool = False) -> None:
    await state.set_state(BookingStates.service)
    keyboard = services_keyboard(db)
    if edit:
        await answer_or_edit(message, texts.CHOOSE_SERVICE, keyboard)
    else:
        await message.answer(texts.CHOOSE_SERVICE, reply_markup=keyboard)


async def show_dates(message, state: FSMContext, db: SalonDB, new_message: bool = False) -> None:
    data = await state.get_data()
    keyboard = dates_keyboard(db, data["service_id"])
    await state.set_state(BookingStates.day)
    if not keyboard.inline_keyboard:
        await answer_or_edit(message, texts.NO_DATES, services_keyboard(db), new_message)
        return
    await answer_or_edit(message, texts.CHOOSE_DATE, keyboard, new_message)


async def show_confirmation(message, state: FSMContext, db: SalonDB) -> None:
    data = await state.get_data()
    service = db.get_service(data["service_id"])
    booking = {
        "service_name": service["name"],
        "price": service["price"],
        "start_at": data["start_at"],
        "client_name": data["name"],
        "phone": data["phone"],
    }
    await state.set_state(BookingStates.confirm)
    text = f"{texts.CONFIRM}\n\n{texts.booking_card(booking)}"
    keyboard = inline_keyboard([("Подтвердить запись", "confirm")])
    if isinstance(message, Message):
        await message.answer(text, reply_markup=keyboard)
    else:
        await answer_or_edit(message, text, keyboard)


@router.message(CommandStart())
async def client_start(message: Message, state: FSMContext, db: SalonDB, master_id: int) -> None:
    if message.from_user.id == master_id:
        return
    await state.clear()
    await message.answer(
        f"{texts.WELCOME}\n\n{texts.CLIENT_MENU_HINT}",
        reply_markup=client_reply_menu(),
    )


@router.message(F.text == texts.CLIENT_BOOK)
async def start_booking_message(message: Message, state: FSMContext, db: SalonDB) -> None:
    await state.clear()
    await show_services(message, state, db)


@router.callback_query(F.data == "book")
async def start_booking(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    await state.clear()
    await show_services(callback.message, state, db, edit=True)
    await callback.answer()


@router.message(F.text == texts.CLIENT_BOOKINGS)
@router.callback_query(F.data == "client_bookings")
async def my_bookings(event, db: SalonDB) -> None:
    message = event.message if isinstance(event, CallbackQuery) else event
    rows = db.conn.execute(
        """
        SELECT b.*, s.name AS service_name, s.price, s.duration_min,
               c.tg_id, c.name AS client_name, c.phone
        FROM bookings b
        JOIN services s ON s.id = b.service_id
        JOIN clients c ON c.id = b.client_id
        WHERE b.master_id = ? AND c.tg_id = ? AND b.status = 'active'
        ORDER BY b.start_at
        """,
        (db.master_id, event.from_user.id),
    ).fetchall()
    if not rows:
        keyboard = inline_keyboard([(texts.CLIENT_BOOK, "book")])
        if isinstance(event, CallbackQuery):
            await message.edit_text(texts.CLIENT_NO_BOOKINGS, reply_markup=keyboard)
            await event.answer()
        else:
            await message.answer(texts.CLIENT_NO_BOOKINGS, reply_markup=keyboard)
        return
    for booking in rows:
        await message.answer(
            texts.booking_card(booking), reply_markup=booking_actions(booking["id"])
        )
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data.startswith("service:"))
async def choose_service(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    service_id = int(callback.data.split(":")[1])
    service = db.get_service(service_id)
    if not service or not service["is_active"]:
        await callback.answer("Услуга больше недоступна.", show_alert=True)
        return
    await state.update_data(service_id=service_id)
    await show_dates(callback.message, state, db)
    await callback.answer()


@router.callback_query(F.data == "dates")
async def back_to_dates(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    await show_dates(callback.message, state, db)
    await callback.answer()


@router.callback_query(F.data.startswith("date:"))
async def choose_date(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    data = await state.get_data()
    day = date.fromisoformat(callback.data.split(":")[1])
    await state.update_data(day=day.isoformat())
    keyboard = times_keyboard(db, data["service_id"], day)
    await state.set_state(BookingStates.time)
    if len(keyboard.inline_keyboard) == 1:
        await show_dates(callback.message, state, db)
        await callback.answer(texts.NO_TIMES, show_alert=True)
        return
    await callback.message.edit_text(
        f"{texts.format_day(day)}\n{texts.CHOOSE_TIME}", reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("time:"))
async def choose_time(callback: CallbackQuery, state: FSMContext, db: SalonDB, bot, master_id: int) -> None:
    start_at = datetime.fromisoformat(callback.data.split(":", 1)[1])
    data = await state.get_data()
    await state.update_data(start_at=start_at.isoformat())
    if data.get("reschedule_id"):
        try:
            new_id = db.reschedule_booking(data["reschedule_id"], start_at)
        except (ValueError, SlotUnavailable):
            await callback.answer(texts.SLOT_TAKEN, show_alert=True)
            await show_dates(callback.message, state, db)
            return
        booking = db.get_booking(new_id)
        await state.clear()
        text = f"{texts.done_text('запись перенесена')}\n\n{texts.booking_card(booking)}"
        await callback.message.edit_text(text, reply_markup=booking_actions(new_id))
        await notify_master(bot, master_id, booking, "Запись перенесена")
        await refresh_master_day(bot, db, master_id, booking)
        await callback.answer()
        return
    if data.get("name") and data.get("phone"):
        await show_confirmation(callback.message, state, db)
    else:
        await state.set_state(BookingStates.name)
        await callback.message.edit_text(texts.ASK_NAME)
    await callback.answer()


@router.message(BookingStates.name)
async def save_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not valid_name(name):
        await message.answer(texts.INVALID_NAME)
        return
    await state.update_data(name=name)
    await state.set_state(BookingStates.phone)
    await message.answer(texts.ASK_PHONE, reply_markup=phone_keyboard())


@router.message(BookingStates.phone)
async def save_phone(message: Message, state: FSMContext, db: SalonDB) -> None:
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if not valid_phone(phone):
        await message.answer(texts.INVALID_PHONE, reply_markup=phone_keyboard())
        return
    await state.update_data(phone=phone)
    await message.answer("Контакт сохранён.", reply_markup=client_reply_menu())
    await show_confirmation(message, state, db)


@router.callback_query(F.data == "confirm", BookingStates.confirm)
async def confirm_booking(callback: CallbackQuery, state: FSMContext, db: SalonDB, bot, master_id: int) -> None:
    data = await state.get_data()
    client_id = data.get("client_id") or db.upsert_client(
        callback.from_user.id, data["name"], data["phone"]
    )
    try:
        booking_id = db.create_booking(
            client_id,
            data["service_id"],
            datetime.fromisoformat(data["start_at"]),
            source=data.get("source", "link"),
            reinvited_from_id=data.get("reinvited_from_id"),
        )
    except (ValueError, SlotUnavailable):
        await callback.answer(texts.SLOT_TAKEN, show_alert=True)
        await show_dates(callback.message, state, db)
        return
    booking = db.get_booking(booking_id)
    await state.clear()
    text = f"{texts.done_text('запись создана')}\n\n{texts.booking_card(booking)}"
    await callback.message.edit_text(text, reply_markup=booking_actions(booking_id))
    await notify_master(bot, master_id, booking)
    await refresh_master_day(bot, db, master_id, booking)
    await callback.answer()


@router.callback_query(F.data.startswith("reschedule:"))
async def reschedule(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = db.get_booking(booking_id)
    if not booking or booking["status"] != "active" or booking["tg_id"] != callback.from_user.id:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    await state.set_data({
        "service_id": booking["service_id"],
        "reschedule_id": booking_id,
        "client_id": booking["client_id"],
        "name": booking["client_name"],
        "phone": booking["phone"],
        "source": booking["source"],
    })
    await show_dates(callback.message, state, db)
    await callback.answer()


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_request(callback: CallbackQuery, db: SalonDB) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = db.get_booking(booking_id)
    if not booking or booking["status"] != "active" or booking["tg_id"] != callback.from_user.id:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    keyboard = inline_keyboard([
        ("Да, отменить", f"cancel_yes:{booking_id}"),
        ("Оставить запись", f"cancel_no:{booking_id}"),
    ])
    await callback.message.edit_text(
        f"{texts.CANCEL_QUESTION}\n\n{texts.booking_card(booking)}", reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_no:"))
async def cancel_no(callback: CallbackQuery, db: SalonDB) -> None:
    booking = db.get_booking(int(callback.data.split(":")[1]))
    if not booking or booking["status"] != "active" or booking["tg_id"] != callback.from_user.id:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    await callback.message.edit_text(
        texts.confirmation(booking), reply_markup=booking_actions(booking["id"])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_yes:"))
async def cancel_yes(callback: CallbackQuery, db: SalonDB, bot, master_id: int) -> None:
    booking_id = int(callback.data.split(":")[1])
    booking = db.get_booking(booking_id)
    if not booking or booking["tg_id"] != callback.from_user.id:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    try:
        booking = db.cancel_booking(booking_id)
    except ValueError:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    await callback.message.edit_text(
        texts.done_text("запись отменена"), reply_markup=next_step_keyboard("client")
    )
    await notify_master(bot, master_id, booking, "Запись отменена")
    await refresh_master_day(bot, db, master_id, booking)
    await callback.answer()


@router.callback_query(F.data.startswith("reinvite:"))
async def start_reinvite(callback: CallbackQuery, state: FSMContext, db: SalonDB) -> None:
    old_id = int(callback.data.split(":")[1])
    old = db.get_booking(old_id)
    if not old or old["status"] != "done" or old["tg_id"] != callback.from_user.id:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    active = db.active_booking_for_client(old["client_id"])
    if active:
        booking = db.get_booking(active["id"])
        await callback.message.answer(
            texts.confirmation(booking), reply_markup=booking_actions(booking["id"])
        )
        await callback.answer()
        return
    await state.set_data({
        "service_id": old["service_id"],
        "client_id": old["client_id"],
        "name": old["client_name"],
        "phone": old["phone"],
        "source": "reinvite",
        "reinvited_from_id": old_id,
    })
    if not old["is_active"]:
        await show_services(callback.message, state, db)
    else:
        await show_dates(callback.message, state, db, new_message=True)
    await callback.answer()


@router.callback_query(F.data.startswith("optout:"))
async def opt_out(callback: CallbackQuery, db: SalonDB) -> None:
    booking = db.get_booking(int(callback.data.split(":")[1]))
    if not booking or booking["tg_id"] != callback.from_user.id:
        await callback.answer(texts.BOOKING_NOT_FOUND, show_alert=True)
        return
    db.set_reinvite_opt_out(booking["client_id"])
    await callback.message.answer(
        texts.done_text("повторные приглашения отключены"),
        reply_markup=next_step_keyboard("client"),
    )
    await callback.answer()
