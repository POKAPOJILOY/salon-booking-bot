from keyboards import client_reply_menu, master_reply_menu, next_step_keyboard
from texts import done_text


def test_master_reply_menu_has_nine_actions_in_compact_rows():
    menu = master_reply_menu()
    assert menu.resize_keyboard
    assert [len(row) for row in menu.keyboard] == [2, 2, 2, 2, 1]
    assert [button.text for row in menu.keyboard for button in row] == [
        "📋 Записи", "➕ Добавить запись",
        "🔒 Блок время", "💅 Услуги",
        "🕐 Расписание", "⚙️ Настройки",
        "🔗 Моя ссылка", "📊 Статистика",
        "🎬 Демо",
    ]


def test_client_reply_menu_has_booking_and_active_bookings():
    menu = client_reply_menu()
    assert [[button.text for button in row] for row in menu.keyboard] == [["📝 Записаться", "📋 Мои записи"]]


def test_every_completed_action_has_contextual_next_steps():
    for scenario in ("booking", "cancel", "block", "service", "schedule", "settings"):
        keyboard = next_step_keyboard(scenario)
        assert 2 <= sum(len(row) for row in keyboard.inline_keyboard) <= 3
    text = done_text("услуга сохранена")
    assert text.startswith("✅ Готово: услуга сохранена.")
    assert text.endswith("Что дальше?")
