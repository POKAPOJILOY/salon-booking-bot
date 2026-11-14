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
        f"Цена: {money(booking['price'])}\n"
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


MENU_CANCEL_HINT = "\n\nИли нажмите любую кнопку меню внизу, чтобы отменить диалог."
ADMIN_MENU = "Меню мастера"
ADMIN_NO_BOOKINGS = "На сегодня и завтра записей нет."
ADMIN_LINK = "Ваша ссылка для клиентов:"
ADMIN_MANUAL_NAME = "Введите имя клиента." + MENU_CANCEL_HINT
ADMIN_MANUAL_PHONE = "Введите телефон клиента." + MENU_CANCEL_HINT
ADMIN_MANUAL_DONE = "Запись добавлена вручную."
ADMIN_BLOCK_DATE = "Введите дату блокировки в формате ДД.ММ.ГГГГ." + MENU_CANCEL_HINT
ADMIN_BLOCK_INTERVAL = "Введите интервал, например 12:00-13:00." + MENU_CANCEL_HINT
ADMIN_BLOCK_REASON = "Введите причину или «нет»." + MENU_CANCEL_HINT
ADMIN_BLOCK_DONE = "Время заблокировано."
ADMIN_INVALID_DATE = "Не удалось распознать дату. Используйте ДД.ММ.ГГГГ."
ADMIN_INVALID_INTERVAL = "Используйте интервал ЧЧ:ММ-ЧЧ:ММ, конец должен быть позже начала."
ADMIN_SERVICE_NAME = "Введите название услуги." + MENU_CANCEL_HINT
ADMIN_SERVICE_PRICE = "Введите цену в рублях, целым числом." + MENU_CANCEL_HINT
ADMIN_SERVICE_DURATION = "Введите длительность в минутах." + MENU_CANCEL_HINT
ADMIN_SERVICE_DONE = "Услуга сохранена."
ADMIN_SCHEDULE_DAY = "Введите часы для {day}, например 10:00-19:00, или «выходной»." + MENU_CANCEL_HINT
ADMIN_SCHEDULE_BREAK = "Введите общий перерыв, например 14:00-14:30, или «нет»." + MENU_CANCEL_HINT
ADMIN_SCHEDULE_DONE = "Расписание сохранено."
ADMIN_SETTING_VALUE = "Введите новое числовое значение." + MENU_CANCEL_HINT
ADMIN_SETTING_DONE = "Настройка сохранена."
ADMIN_CLIENT_CANCELLED = "Мастер отменил вашу запись. Выберите другое время через /start."


MASTER_BOOKINGS = "📋 Записи"
MASTER_ADD = "➕ Добавить запись"
MASTER_BLOCK = "🔒 Блок время"
MASTER_SERVICES = "💅 Услуги"
MASTER_SCHEDULE = "🕐 Расписание"
MASTER_SETTINGS = "⚙️ Настройки"
MASTER_LINK = "🔗 Моя ссылка"
MASTER_STATS = "📊 Статистика"
MASTER_DEMO = "🎬 Демо"
CLIENT_BOOK = "📝 Записаться"
CLIENT_BOOKINGS = "📋 Мои записи"
CLIENT_NO_BOOKINGS = "У вас пока нет активных записей. Выберите удобное время — это займёт меньше минуты."
CLIENT_MENU_HINT = "Выберите действие кнопками под полем ввода."
NEXT_BOOKINGS_TODAY = "📋 Записи на сегодня"
NEXT_ADD_ANOTHER = "➕ Ещё одна запись"
NEXT_BLOCK = "🔒 Заблокировать время"
NEXT_ALL_SERVICES = "💅 Все услуги"
NEXT_LINK = "🔗 Моя ссылка"
NEXT_SCHEDULE = "🕐 Расписание"
NEXT_SETTINGS = "⚙️ Настройки"
NEXT_STATS = "📊 Статистика"
CANCEL_KEEP = "Оставить запись"
CANCEL_CONFIRM_ADMIN = "Отменить запись {client} на {slot}? Клиент получит уведомление."
WIDGET_SUBTITLE = "Выберите удобное время"
WIDGET_NO_SLOTS = "Ближайшие две недели заняты — выберите «Другая дата» под сообщением."


def money(value: int) -> str:
    return f"{value:,} ₽".replace(",", " ")


def done_text(action: str) -> str:
    return f"✅ Готово: {action}.\nЧто дальше?"


DAY_NONWORKING = "Выходной. Свободных окон для записи нет."
WEEK_SCHEDULE_TITLE = "🕐 Моё расписание"
DAY_PICK = "📅 Выбрать дату"
DAY_REVENUE = "💰 Выручка по записи: {amount}"

BLOCK_MENU_TITLE = "🔒 Блоки времени"
BLOCK_NEW = "➕ Новый блок"
BLOCKS_MY = "📋 Мои блоки"
BLOCKS_EMPTY = "Нет запланированных блоков."
BLOCK_CANCEL = "✖ Отмена"
BLOCK_DELETE_CONFIRM = "Удалить блок {interval} ({reason}) {day}?"
BLOCK_NOT_FOUND = "Блок не найден."


def plural(value: int, one: str, few: str, many: str) -> str:
    if 11 <= value % 100 <= 14:
        return many
    if value % 10 == 1:
        return one
    if 2 <= value % 10 <= 4:
        return few
    return many


def day_title(day: date, today: date) -> str:
    weekday = WEEKDAYS[day.weekday()].lower()
    date_text = f"{weekday} {day.day} {MONTHS[day.month - 1]}"
    if day == today:
        return f"📅 Сегодня, {date_text}"
    if day == today.fromordinal(today.toordinal() + 1):
        return f"📅 Завтра, {date_text}"
    return f"📅 {WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def day_summary(booking_count: int, free_count: int) -> str:
    booking_word = plural(booking_count, "запись", "записи", "записей")
    free_word = plural(free_count, "свободное окно", "свободных окна", "свободных окон")
    return f"{booking_count} {booking_word} · {free_count} {free_word}"


WIDGET_HEADLINE = "💅 Пора обновить маникюр! ✨"


ASK_NAME += MENU_CANCEL_HINT
ASK_PHONE += MENU_CANCEL_HINT


DEMO_MENU = "🎬 Выберите демо-сценарий. Каждый показывает конкретную выгоду для мастера."
DEMO_FULL = "▶️ Полный прогон"
DEMO_BUSY = "📊 Показать перегруженный день"
DEMO_CLIENT = "🙋‍♀️ Сыграть клиента"
DEMO_DISABLE = "Выключить ДЕМО и очистить данные"
DEMO_BOOKING_NOTE = "Новая запись: мастер сразу видит клиента и время, без переписки."
DEMO_REMINDER_NOTE = "Автоматическое напоминание снижает риск забытых визитов."
DEMO_CLIENT_LINK = "Клиентка открыла ссылку: ей не нужно ждать ответа мастера."
DEMO_CLIENT_SERVICE = "Она выбрала услугу: цена и длительность понятны сразу."
DEMO_CLIENT_TIME = "Она выбрала свободное время: занятые окна не предлагаются."
DEMO_CLIENT_CONFIRM = "Запись подтверждена: у мастера появилась готовая карточка."
DEMO_CLIENT_REMINDER = "Перед визитом клиентка получает напоминание автоматически."
DEMO_CLIENT_RETURN = "Через 3 недели бот предлагает вернуться с прежней услугой — без нового ввода данных."
