from datetime import date, datetime

from database import LOCAL_TZ, local_time

WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

WELCOME = "Здравствуйте! Здесь можно выбрать удобное время для маникюра."
CHOOSE_SERVICE = "Выберите услугу:"
CHOOSE_DATE = "Выберите дату:"
CHOOSE_TIME = "Выберите свободное время:"
NO_DATES = "В ближайшие 21 день свободного времени нет. Попробуйте выбрать другую услугу."
NO_TIMES = "На этот день свободного времени уже нет. Выберите другую дату."
ASK_NAME = "Как к вам обращаться? Введите имя."
ASK_PHONE = "Введите номер телефона или поделитесь контактом кнопкой ниже."
INVALID_NAME = "Введите имя буквами, без цифр и специальных символов."
INVALID_PHONE = "Проверьте номер телефона: нужно от 10 до 15 цифр."
CONFIRM = "Проверьте детали записи и подтвердите:"
BOOKED = "Вы записаны!"
SLOT_TAKEN = "Это время только что заняли. Выберите другое свободное время."
BOOKING_NOT_FOUND = "Активная запись не найдена."
CANCEL_QUESTION = "Отменить эту запись? Время снова станет доступно другим клиентам."
CANCELLED = "Запись отменена. Время снова свободно."
RESCHEDULED = "Запись перенесена."
OPT_OUT = "Хорошо, больше не буду напоминать о следующем визите."
REMINDER_24 = "Напоминаем: ваш маникюр завтра. Если планы изменились, запись можно перенести или отменить."
REMINDER_1 = "Напоминаем: ваш маникюр начнётся через час."
DEMO_STARTED = "ДЕМО запущено: через 10 секунд придёт новая запись, через 20 — напоминание, примерно через 60 — приглашение вернуться."


def format_day(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def format_slot(value: str | datetime) -> str:
    local = local_time(value) if isinstance(value, str) else value.astimezone(LOCAL_TZ)
    return f"{format_day(local.date())} в {local:%H:%M}"


def booking_card(booking) -> str:
    return (
        f"Услуга: {booking['service_name']}\n"
        f"Цена: {booking['price']} ₽\n"
        f"Когда: {format_slot(booking['start_at'])}\n"
        f"Имя: {booking['client_name']}\n"
        f"Телефон: {booking['phone']}"
    )


def confirmation(booking) -> str:
    return f"{BOOKED}\n\n{booking_card(booking)}"


def reinvite_text(name: str, days: int) -> str:
    weeks = max(1, round(days / 7))
    return (
        f"Здравствуйте, {name}! Прошло уже {weeks} недель с вашего маникюра. "
        "Подобрать новое удобное время?"
    )


def master_notification(booking, action: str = "Новая запись", demo: bool = False) -> str:
    source = {
        "link": "по ссылке",
        "manual": "добавлена вручную",
        "reinvite": "вернулся по приглашению",
    }[booking["source"]]
    prefix = "ДЕМО · " if demo else ""
    return f"{prefix}{action} ({source})\n\n{booking_card(booking)}"


ADMIN_MENU = "Меню мастера"
ADMIN_NO_BOOKINGS = "На сегодня и завтра записей нет."
ADMIN_LINK = "Ваша ссылка для клиентов:"
ADMIN_MANUAL_NAME = "Введите имя клиента."
ADMIN_MANUAL_PHONE = "Введите телефон клиента."
ADMIN_MANUAL_DONE = "Запись добавлена вручную."
ADMIN_BLOCK_DATE = "Введите дату блокировки в формате ДД.ММ.ГГГГ."
ADMIN_BLOCK_INTERVAL = "Введите интервал, например 12:00-13:00."
ADMIN_BLOCK_REASON = "Введите причину или «нет»."
ADMIN_BLOCK_DONE = "Время заблокировано."
ADMIN_INVALID_DATE = "Не удалось распознать дату. Используйте ДД.ММ.ГГГГ."
ADMIN_INVALID_INTERVAL = "Используйте интервал ЧЧ:ММ-ЧЧ:ММ, конец должен быть позже начала."
ADMIN_SERVICE_NAME = "Введите название услуги."
ADMIN_SERVICE_PRICE = "Введите цену в рублях, целым числом."
ADMIN_SERVICE_DURATION = "Введите длительность в минутах."
ADMIN_SERVICE_DONE = "Услуга сохранена."
ADMIN_SCHEDULE_DAY = "Введите часы для {day}, например 10:00-19:00, или «выходной»."
ADMIN_SCHEDULE_BREAK = "Введите общий перерыв, например 14:00-14:30, или «нет»."
ADMIN_SCHEDULE_DONE = "Расписание сохранено."
ADMIN_SETTING_VALUE = "Введите новое числовое значение."
ADMIN_SETTING_DONE = "Настройка сохранена."
ADMIN_CLIENT_CANCELLED = "Мастер отменил вашу запись. Выберите другое время через /start."
