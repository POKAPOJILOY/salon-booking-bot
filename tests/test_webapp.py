import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import date as date_type
from datetime import datetime, time as time_type, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import widget
from database import LOCAL_TZ, SalonDB, db_time, local_time, utc_now
from keyboards import reinvite_keyboard, start_webapp_keyboard
from views import day_keyboard
from webapp import APP_HTML, create_app, validate_init_data

ROOT = Path(__file__).resolve().parent.parent
BOT_TOKEN = "webapp-test-token"
MASTER = 1
CLIENT = 100


def make_init_data(user_id, token=BOT_TOKEN, auth_date=None):
    pairs = {
        "auth_date": str(int(auth_date or time.time())),
        "query_id": "AAtest",
        "user": json.dumps({"id": user_id, "first_name": "Анна"}, ensure_ascii=False),
    }
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


class FakeBot:
    def __init__(self):
        self.send_message = AsyncMock()
        self.methods = []

    async def __call__(self, method):
        self.methods.append(method)
        return SimpleNamespace(message_id=100)


@pytest.fixture
def env():
    database = SalonDB(":memory:", master_id=MASTER)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "09:00", "20:00", None, None)
    bot = FakeBot()
    app = create_app(bot, database, MASTER, BOT_TOKEN)
    yield database, service_id, bot, app
    database.close()


async def web_client(env):
    client = TestClient(TestServer(env[3]))
    await client.start_server()
    return client


def master_headers():
    return {"X-Telegram-Init-Data": make_init_data(MASTER)}


def client_headers():
    return {"X-Telegram-Init-Data": make_init_data(CLIENT)}


def first_slot(database, service_id):
    slot = database.next_slots(service_id, limit=1)[0]
    local = local_time(slot.isoformat())
    return local.date().isoformat(), f"{local:%H:%M}"


def slot_datetime(day, start_time):
    return datetime.combine(date_type.fromisoformat(day), time_type.fromisoformat(start_time), LOCAL_TZ)


def completed_visit(database, service_id, tg_id=CLIENT):
    client_id = database.upsert_client(tg_id, "Анна", "+79990000000")
    now = utc_now()
    cursor = database.conn.execute(
        "INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at) VALUES (?, ?, ?, ?, ?, 'done', 'link', ?)",
        (database.master_id, client_id, service_id, db_time(now - timedelta(days=22)), db_time(now - timedelta(days=21)), db_time(now)),
    )
    return cursor.lastrowid


def test_widgets_disabled_by_default(tmp_path):
    code = "import os;os.environ.pop('WIDGETS_ENABLED',None);import config;print(config.WIDGETS_ENABLED)"
    env_vars = {key: value for key, value in os.environ.items() if key != "WIDGETS_ENABLED"}
    env_vars["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path, env=env_vars
    )
    assert result.stdout.strip() == "False", result.stderr


def test_validate_init_data_accepts_valid_signature():
    user = validate_init_data(make_init_data(CLIENT), BOT_TOKEN)
    assert user["id"] == CLIENT


def test_validate_init_data_rejects_bad_hash():
    init_data = make_init_data(CLIENT)
    forged = init_data.replace("query_id=AAtest", "query_id=AAhack")
    assert validate_init_data(forged, BOT_TOKEN) is None
    assert validate_init_data(make_init_data(CLIENT, token="other-token"), BOT_TOKEN) is None
    assert validate_init_data("", BOT_TOKEN) is None


def test_validate_init_data_rejects_stale_auth_date():
    stale = make_init_data(CLIENT, auth_date=time.time() - 90000)
    assert validate_init_data(stale, BOT_TOKEN) is None


@pytest.mark.asyncio
async def test_api_requires_init_data(env):
    client = await web_client(env)
    response = await client.get("/api/services")
    assert response.status == 401
    await client.close()


@pytest.mark.asyncio
async def test_services_listed_for_authorized_user(env):
    client = await web_client(env)
    response = await client.get("/api/services", headers=client_headers())
    assert response.status == 200
    data = await response.json()
    assert data["services"] == [{"id": 1, "name": "Маникюр", "price": 2000, "duration_min": 60}]
    await client.close()


@pytest.mark.asyncio
async def test_client_can_list_booking_days(env):
    """Клиент (не мастер) должен получать список дат для календаря — регрессия на баг 403."""
    database, service_id, bot, app = env
    client = await web_client(env)
    response = await client.get(f"/api/days?service_id={service_id}", headers=client_headers())
    assert response.status == 200
    data = await response.json()
    assert data["days"]  # список дат не пуст
    await client.close()


@pytest.mark.asyncio
async def test_master_endpoints_reject_regular_client(env):
    client = await web_client(env)
    response = await client.get("/api/day", headers=client_headers())
    assert response.status == 403
    response = await client.post("/api/day/cancel", headers=client_headers(), json={"booking_id": 1})
    assert response.status == 403
    await client.close()


@pytest.mark.asyncio
async def test_master_day_view_matches_database(env):
    database, service_id, bot, app = env
    day, start_time = first_slot(database, service_id)
    client_id = database.upsert_client(CLIENT, "Анна", "+79990000000")
    database.create_booking(client_id, service_id, slot_datetime(day, start_time))
    client = await web_client(env)
    response = await client.get(f"/api/day?date={day}", headers=master_headers())
    assert response.status == 200
    data = await response.json()
    bookings = [item for item in data["items"] if item["type"] == "booking"]
    assert len(bookings) == 1
    assert bookings[0]["client"] == "Анна"
    assert bookings[0]["start"] == start_time
    assert any(item["type"] == "free" for item in data["items"])
    assert "1 запись" in data["summary"]
    await client.close()


@pytest.mark.asyncio
async def test_slots_match_available_slots_and_skip_booked(env):
    database, service_id, bot, app = env
    day, start_time = first_slot(database, service_id)
    client = await web_client(env)
    response = await client.get(f"/api/slots?service_id={service_id}&date={day}", headers=client_headers())
    data = await response.json()
    expected = {f"{local_time(slot.isoformat()):%H:%M}" for slot in database.available_slots(service_id, date_type.fromisoformat(day))}
    assert {slot["time"] for slot in data["slots"]} == expected
    client_id = database.upsert_client(CLIENT, "Анна", "+79990000000")
    database.create_booking(client_id, service_id, slot_datetime(day, start_time))
    response = await client.get(f"/api/slots?service_id={service_id}&date={day}", headers=client_headers())
    data = await response.json()
    assert start_time not in {slot["time"] for slot in data["slots"]}
    await client.close()


@pytest.mark.asyncio
async def test_booking_creates_record_and_notifies_both_sides(env):
    database, service_id, bot, app = env
    day, start_time = first_slot(database, service_id)
    client = await web_client(env)
    response = await client.post("/api/booking", headers=client_headers(), json={
        "service_id": service_id, "date": day, "time": start_time,
        "name": "Анна", "phone": "+79990000000",
    })
    assert response.status == 200
    data = await response.json()
    assert data["booking"]["service_name"] == "Маникюр"
    booking = database.get_booking(data["booking"]["id"])
    assert booking["source"] == "link"
    assert booking["tg_id"] == CLIENT
    bot.send_message.assert_awaited()  # подтверждение клиенту
    assert any(method.__api_method__ == "sendWidget" for method in bot.methods)  # уведомление мастеру
    # конфликт слота → 409, запись остаётся одна
    response = await client.post("/api/booking", headers=client_headers(), json={
        "service_id": service_id, "date": day, "time": start_time,
        "name": "Анна", "phone": "+79990000000",
    })
    assert response.status == 409
    assert database.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 1
    await client.close()


@pytest.mark.asyncio
async def test_booking_with_invite_token_marks_reinvite(env):
    database, service_id, bot, app = env
    old_id = completed_visit(database, service_id)
    day, start_time = first_slot(database, service_id)
    client = await web_client(env)
    response = await client.get(f"/api/invite?token={old_id}", headers=client_headers())
    assert response.status == 200
    info = await response.json()
    assert info["service_name"] == "Маникюр" and info["name"] == "Анна"
    response = await client.post("/api/booking", headers=client_headers(), json={
        "service_id": service_id, "date": day, "time": start_time,
        "invite_token": str(old_id), "name": "Анна", "phone": "+79990000000",
    })
    assert response.status == 200
    data = await response.json()
    booking = database.get_booking(data["booking"]["id"])
    assert booking["source"] == "reinvite"
    assert booking["reinvited_from_id"] == old_id
    await client.close()


@pytest.mark.asyncio
async def test_invite_token_of_another_user_is_forbidden(env):
    database, service_id, bot, app = env
    old_id = completed_visit(database, service_id, tg_id=999)
    day, start_time = first_slot(database, service_id)
    client = await web_client(env)
    response = await client.get(f"/api/invite?token={old_id}", headers=client_headers())
    assert response.status == 403
    response = await client.post("/api/booking", headers=client_headers(), json={
        "service_id": service_id, "date": day, "time": start_time,
        "invite_token": str(old_id), "name": "Анна", "phone": "+79990000000",
    })
    assert response.status == 403
    await client.close()


@pytest.mark.asyncio
async def test_day_cancel_by_master_cancels_and_notifies_client(env):
    database, service_id, bot, app = env
    day, start_time = first_slot(database, service_id)
    client_id = database.upsert_client(CLIENT, "Анна", "+79990000000")
    booking_id = database.create_booking(client_id, service_id, slot_datetime(day, start_time))
    client = await web_client(env)
    response = await client.post("/api/day/cancel", headers=master_headers(), json={"booking_id": booking_id})
    assert response.status == 200
    assert database.get_booking(booking_id)["status"] == "cancelled"
    bot.send_message.assert_awaited_once_with(CLIENT, "Мастер отменил вашу запись. Выберите другое время через /start.")
    response = await client.post("/api/day/cancel", headers=master_headers(), json={"booking_id": booking_id})
    assert response.status == 404
    await client.close()


@pytest.mark.asyncio
async def test_html_page_served_compact_with_title(env):
    assert len(APP_HTML.encode("utf-8")) <= 100 * 1024
    client = await web_client(env)
    for path in ("/", "/app", "/app/master"):
        response = await client.get(path)
        assert response.status == 200
        body = await response.text()
        assert "Запись на маникюр" in body
    await client.close()


def test_reinvite_keyboard_uses_webapp_when_url_configured(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_PUBLIC_URL", "https://salon.example")
    markup = reinvite_keyboard(42)
    buttons = [button for row in markup.inline_keyboard for button in row]
    web_buttons = [button for button in buttons if button.web_app]
    assert len(web_buttons) == 1
    assert web_buttons[0].web_app.url == "https://salon.example/app?invite=42"
    assert any(button.callback_data == "optout:42" for button in buttons)
    assert not any(button.callback_data == "reinvite:42" for button in buttons)
    monkeypatch.setattr(config, "WEBAPP_PUBLIC_URL", "")
    fallback = reinvite_keyboard(42)
    callbacks = [button.callback_data for row in fallback.inline_keyboard for button in row]
    assert "reinvite:42" in callbacks
    assert start_webapp_keyboard() is None


def test_day_keyboard_has_open_day_button_when_url_configured(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_PUBLIC_URL", "https://salon.example")
    database = SalonDB(":memory:", master_id=MASTER)
    day = utc_now().astimezone(LOCAL_TZ).date()
    markup = day_keyboard(database, day)
    web_buttons = [button for row in markup.inline_keyboard for button in row if button.web_app]
    assert len(web_buttons) == 1
    assert web_buttons[0].text == "🗓 Открыть день"
    assert web_buttons[0].web_app.url == f"https://salon.example/app/master?date={day.isoformat()}"
    database.close()


@pytest.mark.asyncio
async def test_reinvite_message_prefers_webapp_over_widget(monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_PUBLIC_URL", "https://salon.example")
    database = SalonDB(":memory:", master_id=MASTER)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "09:00", "20:00", None, None)
    old_id = completed_visit(database, service_id)
    bot = FakeBot()
    assert await widget.send_reinvite_message(bot, database, database.get_booking(old_id))
    assert not bot.methods  # виджет не отправлялся
    bot.send_message.assert_awaited_once()
    markup = bot.send_message.await_args.kwargs["reply_markup"]
    web_buttons = [button for row in markup.inline_keyboard for button in row if button.web_app]
    assert web_buttons and web_buttons[0].web_app.url.endswith(f"/app?invite={old_id}")
    database.close()
