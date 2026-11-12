from datetime import date

from database import SalonDB
from views import week_schedule_keyboard, week_schedule_text


def test_week_schedule_groups_identical_days_and_marks_today():
    database = SalonDB(":memory:", master_id=1)
    for weekday in range(6):
        database.set_schedule(weekday, True, "09:00", "18:00", "15:00", "15:30")
    database.set_schedule(6, False)
    text = week_schedule_text(database, today=date(2026, 11, 13))
    assert "Пн–Сб — 09:00–18:00 · перерыв 15:00–15:30" in text
    assert text.count("← сегодня") == 1
    assert "Вс — выходной" in text
    assert "🍽" not in text
    database.close()


def test_week_keyboard_has_seven_day_shortcuts():
    database = SalonDB(":memory:", master_id=1)
    keyboard = week_schedule_keyboard()
    assert [button.text for row in keyboard.inline_keyboard for button in row][:7] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    assert [button.callback_data for row in keyboard.inline_keyboard for button in row][:7] == [f"admin_edit_day:{weekday}" for weekday in range(7)]
    database.close()
