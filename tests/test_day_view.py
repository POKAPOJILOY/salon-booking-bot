from datetime import datetime, time, timedelta

import pytest

from admin import day_card, day_keyboard, week_schedule_text
from database import LOCAL_TZ, SalonDB


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    database.update_master(slot_step_min=60)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(6):
        database.set_schedule(weekday, True, "09:00", "18:00", "15:00", "15:30")
    database.set_schedule(6, False)
    yield database, service_id
    database.close()


def test_day_card_shows_booking_block_break_free_slots_and_revenue(db):
    database, service_id = db
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    while day.weekday() == 6:
        day += timedelta(days=1)
    start = datetime.combine(day, time(12), tzinfo=LOCAL_TZ)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))
    database.add_block(day, "14:00", "15:00", "Обед")
    text = day_card(database, day)
    assert "📅" in text
    assert "1 запис" in text
    assert "свободн" in text
    assert "🕛 12:00–13:00 · Анна · Маникюр · 2 000 ₽ 📱" in text
    assert "🚫 Обед 14:00–15:00" in text
    assert "☕ Перерыв 15:00–15:30" in text
    assert "🟢 Свободно:" in text
    assert text.endswith("💰 Выручка по записи: 2 000 ₽")


def test_day_card_collapses_free_ranges_when_day_is_overloaded(db, monkeypatch):
    import views

    monkeypatch.setattr(views, "MAX_CARD_LINES", 8)
    database, service_id = db
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    while day.weekday() == 6:
        day += timedelta(days=1)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    for hour in (9, 10, 11, 12):
        start = datetime.combine(day, time(hour), tzinfo=LOCAL_TZ)
        database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))
    text = day_card(database, day)
    assert "🟢 Свободно: " in text
    assert "окна по 60 мин" in text or "окон по 60 мин" in text
    assert "и ещё" in text
    assert text.count("🕛") + text.count("🕙") + text.count("🕚") >= 3  # записи показаны полностью


def test_day_navigation_and_week_schedule(db):
    database, service_id = db
    day = datetime.now(LOCAL_TZ).date()
    keyboard = day_keyboard(database, day)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert f"admin_day:{(day - timedelta(days=1)).isoformat()}" in callbacks
    assert f"admin_day:{(day + timedelta(days=1)).isoformat()}" in callbacks
    assert "admin_day_pick" in callbacks
    text = week_schedule_text(database)
    assert "Пн–Сб — 09:00–18:00 · перерыв 15:00–15:30" in text
    assert "Вс — выходной" in text
