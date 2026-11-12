import json
from datetime import timedelta

import pytest

from database import SalonDB, db_time, utc_now
from widget import WIDGET_HTML, widget_height, widget_state


def test_widget_has_service_header_compact_height_and_selected_success_states():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    for weekday in range(7):
        database.set_schedule(weekday, True, "10:00", "19:00", None, None)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    now = utc_now()
    cursor = database.conn.execute(
        "INSERT INTO bookings(master_id, client_id, service_id, start_at, end_at, status, source, created_at) VALUES (1, ?, ?, ?, ?, 'done', 'link', ?)",
        (client_id, service_id, db_time(now - timedelta(days=22)), db_time(now - timedelta(days=21)), db_time(now)),
    )
    booking = database.get_booking(cursor.lastrowid)
    state = json.loads(widget_state(database, booking))
    assert state["title"] == "Маникюр · 2 000 ₽"
    assert state["subtitle"] == "Выберите удобное время"
    assert 200 <= widget_height(database, booking) <= 400
    assert "selected" in WIDGET_HTML
    assert "result.label" in WIDGET_HTML
    assert "Ближайшие две недели заняты" in WIDGET_HTML
    database.close()
