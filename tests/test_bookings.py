import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta

import pytest

from database import LOCAL_TZ, UTC, SalonDB, SlotUnavailable


@pytest.fixture
def db(tmp_path):
    database = SalonDB(tmp_path / "bookings.db", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    yield database, service_id
    database.close()


def slot_at(database, service_id, hour=12):
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    return datetime.combine(day, time(hour), tzinfo=LOCAL_TZ)


def test_create_booking_stores_utc_and_rejects_overlap(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = slot_at(database, service_id)
    booking_id = database.create_booking(client_id, service_id, start)
    booking = database.get_booking(booking_id)
    assert booking["start_at"].endswith("+00:00")
    assert booking["start_at"] == start.astimezone(UTC).isoformat(timespec="seconds")
    other_id = database.upsert_client(200, "Мария", "+79990000001")
    with pytest.raises(SlotUnavailable):
        database.create_booking(other_id, service_id, start + timedelta(minutes=30))


def test_cancelled_time_becomes_available(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = slot_at(database, service_id)
    booking_id = database.create_booking(client_id, service_id, start)
    database.cancel_booking(booking_id)
    assert database.get_booking(booking_id)["status"] == "cancelled"
    other_id = database.upsert_client(200, "Мария", "+79990000001")
    assert database.create_booking(other_id, service_id, start)


def test_reschedule_rolls_back_when_cancelling_old_fails(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    old_id = database.create_booking(client_id, service_id, slot_at(database, service_id, 12))
    database.conn.execute(
        f"CREATE TRIGGER fail_reschedule BEFORE UPDATE OF status ON bookings "
        f"WHEN OLD.id = {old_id} AND NEW.status = 'cancelled' "
        f"BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.reschedule_booking(old_id, slot_at(database, service_id, 15))
    assert database.get_booking(old_id)["status"] == "active"
    assert database.conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'active'").fetchone()[0] == 1


def test_two_database_connections_cannot_book_same_slot(tmp_path):
    path = tmp_path / "race.db"
    first = SalonDB(path, master_id=1)
    second = SalonDB(path, master_id=1)
    service_id = first.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        first.set_schedule(weekday, True, "10:00", "19:00", None, None)
    first_client = first.upsert_client(100, "Анна", "+79990000000")
    second_client = second.upsert_client(200, "Мария", "+79990000001")
    start = slot_at(first, service_id)

    def book(database, client_id):
        try:
            return database.create_booking(client_id, service_id, start)
        except SlotUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: book(*args), [(first, first_client), (second, second_client)]))
    assert sum(result is not None for result in results) == 1
    assert first.conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'active'").fetchone()[0] == 1
    first.close()
    second.close()


def test_rejected_booking_does_not_create_client_side_effects(db):
    database, service_id = db
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    database.set_schedule(day.weekday(), False, "10:00", "19:00", None, None)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    with pytest.raises(SlotUnavailable):
        database.create_booking(client_id, service_id, datetime.combine(day, time(12), tzinfo=LOCAL_TZ))
    assert database.conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
