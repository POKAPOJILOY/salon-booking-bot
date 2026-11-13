from day_widget import DAY_WIDGET_HTML
from widget import WIDGET_HTML


def test_widgets_do_not_use_undocumented_quickjs_dom_or_css():
    for html in (WIDGET_HTML, DAY_WIDGET_HTML):
        assert "querySelectorAll" not in html
        assert "min-block-size" not in html
        assert "min-inline-size" not in html
        assert "@media(hover" not in html
        assert "Avenir Next Rounded" not in html
        assert "SF Pro Rounded" not in html
        assert "Segoe UI Rounded" not in html
        assert "ui-rounded" in html


def test_booking_widget_tracks_buttons_without_querying_dom():
    assert "let buttons=[]" in WIDGET_HTML
    assert "buttons.push(button)" in WIDGET_HTML
    assert "buttons.forEach" in WIDGET_HTML
