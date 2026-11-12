from datetime import timedelta
from types import SimpleNamespace

import pytest

from database import SalonDB, db_time, utc_now
from scheduler import process_pending


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    yield database, service_id
    database.close()


def completed_visit(database, service_id, client_id, end, source="link"):
    cursor = database.conn.execute(
        """
        INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at)
        VALUES (?, ?, ?, ?, ?, 'done', ?, ?)
        """,
        (1, client_id, service_id, db_time(end - timedelta(hours=1)), db_time(end), source, db_time(end)),
    )
    return cursor.lastrowid


@pytest.mark.asyncio
async def test_reminders_are_caught_up_and_sent_exactly_once(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = database.next_slots(service_id, limit=1)[0]
    database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))
    bot = FakeBot()
    now = start - timedelta(hours=23)
    await process_pending(bot, database, 1, now=now)
    await process_pending(bot, database, 1, now=now)
    assert len(bot.messages) == 1
    assert database.get_booking(1)["reminder24_sent"] == 1
    await process_pending(bot, database, 1, now=start - timedelta(minutes=30))
    await process_pending(bot, database, 1, now=start - timedelta(minutes=30))
    assert len(bot.messages) == 2
    assert database.get_booking(1)["reminder1_sent"] == 1


@pytest.mark.asyncio
async def test_reinvite_is_sent_once_after_21_days(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    now = utc_now()
    visit_id = completed_visit(database, service_id, client_id, now - timedelta(days=21))
    sent = []

    async def send(bot, booking):
        sent.append(booking["id"])
        return True

    await process_pending(FakeBot(), database, 1, now=now, reinvite_sender=send)
    await process_pending(FakeBot(), database, 1, now=now, reinvite_sender=send)
    assert sent == [visit_id]
    assert database.get_booking(visit_id)["reinvite_sent"] == 1


@pytest.mark.asyncio
async def test_reinvite_skips_active_booking_and_opt_out(db):
    database, service_id = db
    active_client = database.upsert_client(100, "Анна", "+79990000000")
    opted_client = database.upsert_client(200, "Мария", "+79990000001")
    now = utc_now()
    completed_visit(database, service_id, active_client, now - timedelta(days=21))
    completed_visit(database, service_id, opted_client, now - timedelta(days=21))
    start = database.next_slots(service_id, limit=1, now=now)[0]
    database.create_booking(active_client, service_id, start, now=now)
    database.set_reinvite_opt_out(opted_client, True)
    sent = []

    async def send(bot, booking):
        sent.append(booking["client_id"])
        return True

    await process_pending(FakeBot(), database, 1, now=now, reinvite_sender=send)
    assert sent == []


@pytest.mark.asyncio
async def test_failed_delivery_does_not_mark_reminder_sent(db):
    database, service_id = db
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = database.next_slots(service_id, limit=1)[0]
    booking_id = database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))

    class FailingBot:
        async def send_message(self, *args, **kwargs):
            raise RuntimeError("network down")

    await process_pending(FailingBot(), database, 1, now=start - timedelta(hours=23))
    assert database.get_booking(booking_id)["reminder24_sent"] == 0
