# Salon Booking Bot

Telegram-бот записи к мастеру маникюра (aiogram 3 + SQLite). Деплой: Amvera (amvera.yml), БД в `/data/salon.db` (путь из env `DB_PATH`).

## Структура
- `bot.py` — точка входа, запуск polling.
- `config.py` — env: BOT_TOKEN, MASTER_ID, TZ, DB_PATH, DEMO.
- `database.py` — SQLite: схема, записи, блоки, реинвайты (INVITE_AFTER_DAYS=21).
- `client.py` — сценарии клиента (запись, отмена, перенос, реинвайт).
- `admin.py` — панель мастера (расписание, блоки, отмены/переносы, статистика).
- `widget.py` — виджет записи/reinvite (Bot API 10.4 Widgets).
- `day_widget.py` — виджет «расписание дня» (компактный payload v3, лимит 1000 символов, кап 9 строк).
- `keyboards.py`, `views.py`, `texts.py` — клавиатуры, тексты, рендер.
- `scheduler.py`, `notifications.py` — напоминания и уведомления мастеру.
- `demo.py` — демо-режимы; `cleanup_demo_data` трогает только данные с меткой «(демо)».
- `tests/` — pytest.

## Запуск и тесты
- Установка: `pip install -r requirements.txt`, конфиг — скопировать `.env.example` в `.env`.
- Запуск: `python bot.py`.
- Тесты: `pytest` (все должны быть зелёными перед коммитом).

## Ограничения виджетов Telegram
Нельзя: `querySelectorAll`, `Intl`, `Array.find`, `hover:`-стили, именованные шрифты, внутренний `overflow:auto`. Высота виджета — авто по контенту с капом строк. Не менять `.env`, `amvera.yml` и схему существующих таблиц без явного запроса.
