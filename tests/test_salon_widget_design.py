import zlib

from widget import WIDGET_HTML


def test_salon_widget_has_both_themes_decor_and_compact_accessible_chips():
    assert '<meta name="color-scheme" content="light dark">' in WIDGET_HTML
    assert "linear-gradient" in WIDGET_HTML
    assert "prefers-color-scheme:dark" in WIDGET_HTML
    assert "--tg-theme-bg-color" in WIDGET_HTML
    assert "main::before" in WIDGET_HTML and "main::after" in WIDGET_HTML
    assert "💅 Пора обновить маникюр!" in WIDGET_HTML
    assert "--target:44px" in WIDGET_HTML
    assert "border-radius:999px" in WIDGET_HTML
    assert "Напомним за 24 часа" in WIDGET_HTML
    assert "Перенос и отмена — в один тап" in WIDGET_HTML
    assert "Вы записаны!" in WIDGET_HTML
    assert "leaving" in WIDGET_HTML
    assert "prefers-reduced-motion:reduce" in WIDGET_HTML
    assert "getElementById('title').hidden=true" in WIDGET_HTML
    assert "getElementById('subtitle').hidden=true" in WIDGET_HTML
    assert "success-service" in WIDGET_HTML


def test_salon_widget_still_fits_compressed_telegram_limit():
    assert len(zlib.compress(WIDGET_HTML.encode("utf-8"), level=9)) <= 4096
