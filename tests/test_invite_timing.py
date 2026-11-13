from datetime import datetime, timedelta

import pytest

from database import INVITE_AFTER_DAYS, SalonDB, UTC, db_time
from scheduler import process_pending


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    yield database, service_id, client_id
    database.close()


def completed_at(database, service_id, client_id, end):
    cursor = database.conn.execute(
        "INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at) VALUES (1, ?, ?, ?, ?, 'done', 'link', ?)",
        (client_id, service_id, db_time(end - timedelta(hours=1)), db_time(end), db_time(end)),
    )
    return cursor.lastrowid


@pytest.mark.asyncio
async def test_reinvite_at_exact_21_days_not_before(db):
    database, service_id, client_id = db
    assert database.get_master()["reinvite_days"] == INVITE_AFTER_DAYS == 21
    end = datetime(2026, 12, 31, 20, 59, tzinfo=UTC)
    booking_id = completed_at(database, service_id, client_id, end)
    target = end + timedelta(days=INVITE_AFTER_DAYS)
    assert target == datetime(2027, 1, 21, 20, 59, tzinfo=UTC)
    sent = []

    async def send(bot, booking):
        sent.append(booking["id"])
        return True

    await process_pending(object(), database, 1, now=target - timedelta(seconds=1), reinvite_sender=send)
    assert sent == []
    await process_pending(object(), database, 1, now=target, reinvite_sender=send)
    assert sent == [booking_id]


def test_reinvite_at_midnight_moscow(db):
    database, service_id, client_id = db
    end = datetime(2026, 12, 31, 20, 59, 59, tzinfo=UTC)
    completed_at(database, service_id, client_id, end)
    target = end + timedelta(days=21)
    assert target.astimezone().hour == 23  # UTC; в MSK следующая полночь — 21:00 UTC.
    assert database.reinvites_due(target - timedelta(milliseconds=1)) == []
    assert len(database.reinvites_due(target)) == 1
