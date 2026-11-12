from datetime import datetime, time, timedelta

import pytest

from database import LOCAL_TZ, SalonDB


@pytest.fixture
def db(tmp_path):
    database = SalonDB(tmp_path / "slots.db", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", "14:00", "14:30")
    yield database, service_id
    database.close()


def tomorrow():
    return (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()


def test_slots_respect_break_and_work_hours(db):
    database, service_id = db
    slots = database.available_slots(service_id, tomorrow())
    labels = [slot.astimezone(LOCAL_TZ).strftime("%H:%M") for slot in slots]
    assert labels[0] == "10:00"
    assert labels[-1] == "18:00"
    assert "13:30" not in labels
    assert "14:00" not in labels
    assert "14:30" in labels


def test_nonworking_day_returns_empty(db):
    database, service_id = db
    day = tomorrow()
    database.set_schedule(day.weekday(), False, "10:00", "19:00", None, None)
    assert database.available_slots(service_id, day) == []


def test_minimum_notice_filters_early_slots(db):
    database, service_id = db
    day = tomorrow()
    now = datetime.combine(day, time(9), tzinfo=LOCAL_TZ)
    slots = database.available_slots(service_id, day, now)
    assert slots[0].astimezone(LOCAL_TZ).hour == 11


def test_service_must_finish_before_closing(db):
    database, service_id = db
    long_id = database.add_service("Сложная услуга", 5000, 600)
    assert database.available_slots(long_id, tomorrow()) == []


def test_service_longer_than_step_blocks_overlapping_starts(db):
    database, service_id = db
    day = tomorrow()
    start = datetime.combine(day, time(12), tzinfo=LOCAL_TZ)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    database.create_booking(client_id, service_id, start)
    labels = [slot.astimezone(LOCAL_TZ).strftime("%H:%M") for slot in database.available_slots(service_id, day)]
    assert "11:30" not in labels
    assert "12:00" not in labels
    assert "12:30" not in labels
    assert "13:00" in labels


def test_past_and_exact_minimum_notice(db):
    database, service_id = db
    day = tomorrow()
    now = datetime.combine(day, time(9, 30), tzinfo=LOCAL_TZ)
    labels = [slot.astimezone(LOCAL_TZ).strftime("%H:%M") for slot in database.available_slots(service_id, day, now)]
    assert "11:00" not in labels
    assert "11:30" in labels
    yesterday = day - timedelta(days=2)
    assert database.available_slots(service_id, yesterday) == []


def test_block_removes_overlapping_slots(db):
    database, service_id = db
    day = tomorrow()
    database.add_block(day, "12:00", "13:00", "Личное дело")
    labels = [slot.astimezone(LOCAL_TZ).strftime("%H:%M") for slot in database.available_slots(service_id, day)]
    assert "12:00" not in labels
    assert "12:30" not in labels
    assert "13:00" in labels
