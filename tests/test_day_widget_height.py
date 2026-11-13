import json
from datetime import datetime, time, timedelta

from database import LOCAL_TZ, SalonDB
from day_widget import DAY_WIDGET_HTML, day_widget_height, day_widget_state


def test_day_widget_scrolls_and_height_uses_documented_api_maximum():
    assert "height:100%" in DAY_WIDGET_HTML
    assert "overflow-y:auto" in DAY_WIDGET_HTML
    assert "-webkit-overflow-scrolling:touch" in DAY_WIDGET_HTML
    state = json.dumps({"items": [{"type": "free"}] * 20})
    assert day_widget_height(state) == 600


def test_late_evening_booking_is_kept_in_widget_items():
    database = SalonDB(":memory:", master_id=1)
    service_id = database.add_service("Маникюр", 2000, 60)
    day = (datetime.now(LOCAL_TZ) + timedelta(days=1)).date()
    database.set_schedule(day.weekday(), True, "09:00", "20:00", None, None)
    client_id = database.upsert_client(100, "Анна", "+79990000000")
    start = datetime.combine(day, time(19), tzinfo=LOCAL_TZ)
    database.create_booking(client_id, service_id, start, now=start - timedelta(hours=3))
    state = json.loads(day_widget_state(database, day))
    booking = next(item for item in state["items"] if item["type"] == "booking")
    assert booking["start"] == "19:00"
    assert booking["end"] == "20:00"
    database.close()
