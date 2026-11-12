from datetime import timedelta

from database import SalonDB, utc_now


def test_booking_and_reminder_flag_survive_reopen(tmp_path):
    path = tmp_path / "persistent.db"
    database = SalonDB(path, master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = database.next_slots(service_id, limit=1)[0]
    booking_id = database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))
    database.mark_reminder_sent(booking_id, "reminder24_sent")
    database.close()

    reopened = SalonDB(path, master_id=1)
    booking = reopened.get_booking(booking_id)
    assert booking["status"] == "active"
    assert booking["client_name"] == "Анна"
    assert booking["reminder24_sent"] == 1
    assert reopened.due_reminders("reminder24_sent", start - timedelta(hours=23)) == []
    reopened.close()
