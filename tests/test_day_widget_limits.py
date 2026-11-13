import json
from datetime import datetime, time, timedelta

from database import LOCAL_TZ, SalonDB, db_time
from day_widget import CHAT_DATA_LIMIT, day_widget_state


def make_db():
    database = SalonDB(":memory:", master_id=1)
    database.update_master(slot_step_min=30)
    service_id = database.add_service("Маникюр с покрытием гель-лак", 3500, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", "14:00", "14:30")
    return database, service_id


def test_busy_day_state_fits_chat_data_limit():
    database, service_id = make_db()
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    now = datetime.combine(day, time(9), tzinfo=LOCAL_TZ) - timedelta(hours=3)
    names = ["Александра", "Екатерина", "Марьям", "Валентина", "Ольга", "Дарья"]
    for i, name in enumerate(names):
        client_id = database.upsert_client(300 + i, name, f"+799900000{i}")
        start = datetime.combine(day, time(10 + i if i < 4 else 11 + i), tzinfo=LOCAL_TZ)
        database.create_booking(client_id, service_id, start, now=now)
    database.add_block(day, "17:30", "18:00", "Личные дела")
    state = day_widget_state(database, day, now=now)
    assert len(state.encode("utf-8")) <= CHAT_DATA_LIMIT
    payload = json.loads(state)
    assert len([item for item in payload["items"] if item["t"] == "b"]) == 6
    database.close()


def test_fragmented_free_time_aggregated_into_one_row():
    database, service_id = make_db()
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    now = datetime.combine(day, time(9), tzinfo=LOCAL_TZ) - timedelta(hours=3)
    short = database.add_service("Коррекция", 1000, 30)
    for i, hour in enumerate((10, 10.5, 12, 12.5, 16, 16.5)):
        client_id = database.upsert_client(400 + i, f"К{i}", f"+799911111{i}")
        start = datetime.combine(day, time(int(hour), 30 if hour % 1 else 0), tzinfo=LOCAL_TZ)
        database.create_booking(client_id, short, start, now=now)
    state = json.loads(day_widget_state(database, day, now=now))
    free_rows = [item for item in state["items"] if item["t"] == "f"]
    more_rows = [item for item in state["items"] if item["t"] == "m"]
    assert len(free_rows) <= 2
    assert len(more_rows) == 1
    assert more_rows[0]["min"] > 0
    database.close()


def test_past_bookings_collapse_only_when_day_is_full():
    database, service_id = make_db()
    day = datetime.now(LOCAL_TZ).date()
    client_id = database.upsert_client(500, "Анна", "+79990000000")
    start = datetime.combine(day, time(10), tzinfo=LOCAL_TZ)
    database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))
    state = json.loads(day_widget_state(database, day, now=start + timedelta(hours=2)))
    booking_rows = [item for item in state["items"] if item["t"] == "b"]
    assert len(booking_rows) == 1
    assert booking_rows[0]["pst"] is True
    database.close()


def test_overloaded_day_is_capped_and_summarized_without_oversize_payload():
    database, service_id = make_db()
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    create_now = datetime.combine(day, time(8), tzinfo=LOCAL_TZ) - timedelta(days=1)
    for index, hour in enumerate((10, 11, 12, 13, 15, 16, 17, 18)):
        client_id = database.upsert_client(600 + index, f"Клиент {index}", f"+799900006{index}")
        database.create_booking(
            client_id, service_id, datetime.combine(day, time(hour), tzinfo=LOCAL_TZ), now=create_now
        )
    for index in range(2):
        client_id = database.upsert_client(700 + index, f"Прошлая {index}", f"+799900007{index}")
        start = datetime.combine(day, time(8, index * 30), tzinfo=LOCAL_TZ)
        database.conn.execute(
            "INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at) VALUES (1, ?, ?, ?, ?, 'active', 'link', ?)",
            (client_id, service_id, db_time(start), db_time(start + timedelta(minutes=30)), db_time(create_now)),
        )
    database.add_block(day, "12:30", "12:45", "Звонок")
    database.add_block(day, "17:30", "17:45", "Личное дело")
    state = day_widget_state(database, day, now=datetime.combine(day, time(18, 30), tzinfo=LOCAL_TZ))
    payload = json.loads(state)
    assert len(state.encode("utf-8")) <= CHAT_DATA_LIMIT
    assert len(payload["items"]) <= 9
    assert any(item["t"] == "d" and item["n"] >= 2 for item in payload["items"])
    database.close()
