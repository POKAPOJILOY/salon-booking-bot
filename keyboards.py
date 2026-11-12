from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from database import SalonDB, local_time
from texts import format_day


def inline_keyboard(buttons: list[tuple[str, str]], columns: int = 1) -> InlineKeyboardMarkup:
    rows = [buttons[index:index + columns] for index in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def services_keyboard(db: SalonDB) -> InlineKeyboardMarkup:
    return inline_keyboard([
        (f"{service['name']} · {service['price']} ₽ · {service['duration_min']} мин", f"service:{service['id']}")
        for service in db.list_services()
    ])


def dates_keyboard(db: SalonDB, service_id: int) -> InlineKeyboardMarkup:
    return inline_keyboard([
        (format_day(day), f"date:{day.isoformat()}")
        for day in db.available_dates(service_id)
    ], columns=3)


def times_keyboard(db: SalonDB, service_id: int, day: date) -> InlineKeyboardMarkup:
    buttons = [
        (f"{local_time(slot.isoformat()):%H:%M}", f"time:{slot.isoformat()}")
        for slot in db.available_slots(service_id, day)
    ]
    keyboard = inline_keyboard(buttons, columns=4)
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="← Другая дата", callback_data="dates")])
    return keyboard


def booking_actions(booking_id: int) -> InlineKeyboardMarkup:
    return inline_keyboard([
        ("Перенести", f"reschedule:{booking_id}"),
        ("Отменить", f"cancel:{booking_id}"),
    ], columns=2)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def reinvite_fallback(booking_id: int) -> InlineKeyboardMarkup:
    return inline_keyboard([
        ("Подобрать время", f"reinvite:{booking_id}"),
        ("Больше не напоминать", f"optout:{booking_id}"),
    ])
