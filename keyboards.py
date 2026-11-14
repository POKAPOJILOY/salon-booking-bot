from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

import config
import texts
from database import SalonDB, local_time


def inline_keyboard(buttons: list[tuple[str, str]], columns: int = 1) -> InlineKeyboardMarkup:
    rows = [buttons[index:index + columns] for index in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def master_reply_menu() -> ReplyKeyboardMarkup:
    labels = [
        texts.MASTER_BOOKINGS, texts.MASTER_ADD,
        texts.MASTER_BLOCK, texts.MASTER_SERVICES,
        texts.MASTER_SCHEDULE, texts.MASTER_SETTINGS,
        texts.MASTER_LINK, texts.MASTER_STATS,
        texts.MASTER_DEMO,
    ]
    rows = [labels[index:index + 2] for index in range(0, len(labels), 2)]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True,
        input_field_placeholder="Меню мастера",
    )


def client_reply_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(text=texts.CLIENT_BOOK),
            KeyboardButton(text=texts.CLIENT_BOOKINGS),
        ]],
        resize_keyboard=True,
        input_field_placeholder="Запись и ваши визиты",
    )


def next_step_keyboard(scenario: str) -> InlineKeyboardMarkup:
    actions = {
        "booking": [
            (texts.NEXT_BOOKINGS_TODAY, "admin_bookings"),
            (texts.NEXT_ADD_ANOTHER, "admin_manual"),
            (texts.NEXT_BLOCK, "admin_block"),
        ],
        "cancel": [
            (texts.MASTER_BOOKINGS, "admin_bookings"),
            (texts.MASTER_ADD, "admin_manual"),
        ],
        "block": [
            (texts.MASTER_BOOKINGS, "admin_bookings"),
            (texts.NEXT_SCHEDULE, "admin_schedule"),
        ],
        "service": [
            (texts.NEXT_ALL_SERVICES, "admin_services"),
            (texts.NEXT_LINK, "admin_link"),
        ],
        "schedule": [
            (texts.NEXT_SCHEDULE, "admin_schedule"),
            (texts.MASTER_BOOKINGS, "admin_bookings"),
        ],
        "settings": [
            (texts.NEXT_SETTINGS, "admin_settings"),
            (texts.NEXT_STATS, "admin_stats"),
        ],
        "client": [
            (texts.CLIENT_BOOKINGS, "client_bookings"),
            (texts.CLIENT_BOOK, "book"),
        ],
    }
    return inline_keyboard(actions[scenario])


def services_keyboard(db: SalonDB) -> InlineKeyboardMarkup:
    return inline_keyboard([
        (f"{service['name']} · {texts.money(service['price'])} · {service['duration_min']} мин", f"service:{service['id']}")
        for service in db.list_services()
    ])


def dates_keyboard(db: SalonDB, service_id: int) -> InlineKeyboardMarkup:
    return inline_keyboard([
        (texts.format_day(day), f"date:{day.isoformat()}")
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
        ("🔄 Перенести", f"reschedule:{booking_id}"),
        ("❌ Отменить", f"cancel:{booking_id}"),
    ], columns=2)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def reinvite_fallback(booking_id: int) -> InlineKeyboardMarkup:
    return inline_keyboard([
        ("Другая дата", f"reinvite:{booking_id}"),
        ("Больше не напоминать", f"optout:{booking_id}"),
    ])


def reinvite_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    if not config.WEBAPP_PUBLIC_URL:
        return reinvite_fallback(booking_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📅 Выбрать время",
            web_app=WebAppInfo(url=f"{config.WEBAPP_PUBLIC_URL}/app?invite={booking_id}"),
        )],
        [InlineKeyboardButton(text="Больше не напоминать", callback_data=f"optout:{booking_id}")],
    ])


def start_webapp_keyboard() -> InlineKeyboardMarkup | None:
    if not config.WEBAPP_PUBLIC_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📅 Записаться",
            web_app=WebAppInfo(url=f"{config.WEBAPP_PUBLIC_URL}/app"),
        )
    ]])
