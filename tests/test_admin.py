from datetime import timedelta

import pytest

from database import SalonDB, db_time, utc_now


@pytest.fixture
def db():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    yield database, service_id
    database.close()


def test_service_disable_and_delete_preserve_history(db):
    database, service_id = db
    database.set_service_active(service_id, False)
    assert database.list_services() == []
    assert database.available_slots(service_id, utc_now().date()) == []
    database.set_service_active(service_id, True)
    database.delete_service(service_id)
    assert database.get_service(service_id)["is_active"] == 0


def test_bookings_list_covers_today_and_tomorrow(db):
    database, service_id = db
    now = utc_now()
    slots = database.next_slots(service_id, limit=2, days=3, now=now)
    client_id = database.create_client(None, "Анна", "+79990000000")
    for index in range(2):
        database.create_booking(client_id, service_id, slots[0] + timedelta(hours=2 * index), source="manual", now=now)
    rows = database.upcoming_bookings(now=now, days=3)
    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["client_name"] == "Анна"


def test_statistics_distinguishes_sources_cancellations_and_revenue(db):
    database, service_id = db
    now = utc_now()
    first_start = database.next_slots(service_id, limit=1, days=3, now=now)[0]
    starts = [first_start + timedelta(hours=2 * index) for index in range(3)]
    link_client = database.upsert_client(100, "Анна", "+79990000000")
    manual_client = database.create_client(None, "Мария", "+79990000001")
    returning_client = database.upsert_client(200, "Ольга", "+79990000002")
    link_id = database.create_booking(link_client, service_id, starts[0], source="link", now=now)
    manual_id = database.create_booking(manual_client, service_id, starts[1], source="manual", now=now)
    database.create_booking(returning_client, service_id, starts[2], source="reinvite", now=now)
    database.conn.execute("UPDATE bookings SET status = 'done' WHERE id = ?", (link_id,))
    database.cancel_booking(manual_id)
    database.mark_reminder_sent(link_id, "reminder24_sent")
    with database.transaction() as conn:
        conn.execute(
            """
            INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at)
            VALUES (1, ?, ?, ?, ?, 'done', 'link', ?)
            """,
            (
                link_client,
                service_id,
                db_time(now - timedelta(days=40)),
                db_time(now - timedelta(days=40) + timedelta(hours=1)),
                db_time(now - timedelta(days=40)),
            ),
        )
    stats = database.statistics(now)
    assert stats["all"]["link"] == 2
    assert stats["all"]["manual"] == 0
    assert stats["all"]["reinvite"] == 1
    assert stats["all"]["cancelled"] == 1
    assert stats["all"]["reminders"] == 1
    assert stats["all"]["revenue"] == 4000
    assert stats["last30"]["link"] == 1
    assert stats["last30"]["revenue"] == 2000
