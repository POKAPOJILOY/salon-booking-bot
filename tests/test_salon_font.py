from day_widget import DAY_WIDGET_HTML
from widget import WIDGET_HTML


def test_widgets_use_soft_rounded_system_fonts_without_external_assets():
    for html in (WIDGET_HTML, DAY_WIDGET_HTML):
        assert "SF Pro Rounded" in html
        assert "Segoe UI Rounded" in html
        assert "Trebuchet MS" in html
        assert "@import" not in html
        assert "fonts.googleapis.com" not in html
