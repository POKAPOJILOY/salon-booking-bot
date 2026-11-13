import html
import json
import logging

import texts
from config import WIDGETS_ENABLED
from keyboards import inline_keyboard


def booking_notice_html(booking, action: str, demo: bool) -> str:
    fields = {
        "action": f"{'ДЕМО · ' if demo else ''}{action}",
        "client": booking["client_name"],
        "service": booking["service_name"],
        "price": texts.money(booking["price"]),
        "slot": texts.format_slot(booking["start_at"]),
        "phone": booking["phone"],
    }
    content = "".join(f"<p><strong>{html.escape(str(key))}</strong><br>{html.escape(str(value))}</p>" for key, value in fields.items())
    return (
        '<!doctype html><html lang="ru"><head><title>Новая запись</title><style>'
        'body{margin:0}main{padding:16px;border-radius:22px;background:linear-gradient(145deg,#F6DDE6,#FFF9FB);color:#573B47;font-family:ui-rounded,system-ui,sans-serif;line-height:1.45}'
        'p{margin:0 0 10px}p:last-child{margin:0}@media(prefers-color-scheme:dark){main{background:linear-gradient(145deg,#5A414D,#1F1B1E);color:#F9EEF3}}'
        f'</style></head><body><main>{content}</main></body></html>'
    )


async def notify_master(bot, master_id: int, booking, action: str = "Новая запись", demo: bool = False) -> None:
    text = texts.master_notification(booking, action, demo)
    if WIDGETS_ENABLED:
        try:
            from widget import SendWidget

            await bot(SendWidget(
                chat_id=master_id,
                html=booking_notice_html(booking, action, demo),
                chat_data=json.dumps({"booking_id": booking["id"]}, separators=(",", ":")),
                caption=text,
            ))
            keyboard = inline_keyboard([
                ("🔄 Перенести", f"admin_reschedule:{booking['id']}"),
                ("❌ Отменить", f"admin_cancel:{booking['id']}"),
            ], columns=2)
            await bot.send_message(
                master_id,
                f"{booking['client_name']} · {texts.format_slot(booking['start_at'])}",
                reply_markup=keyboard,
            )
            return
        except Exception as exc:
            logging.warning("Виджет уведомления недоступен, отправляем текст: %s", exc)
    try:
        await bot.send_message(master_id, text)
    except Exception:
        logging.exception("Не удалось уведомить мастера %s", master_id)
