import json
import logging
from datetime import date, datetime, timedelta

from aiogram.methods import DeleteMessage

import texts
from config import WIDGETS_ENABLED
from database import LOCAL_TZ, SalonDB, local_time, utc_now
from keyboards import inline_keyboard
from views import bookings_for_day, day_card, day_keyboard, free_slots_for_day
from widget import EditMessageWidgetData, SendWidget

_day_widgets = {}


DAY_WIDGET_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="color-scheme" content="light dark"><title>Расписание дня</title>
<style>
:root{color-scheme:light dark;--text:#573B47;--muted:#8B6A78;--accent:#B85C82;--pink:#F2C9D9;--card:#FFF5F9;--line:rgba(139,106,120,.18)}
@media(prefers-color-scheme:dark){:root{--text:#F9EEF3;--muted:#D5B8C4;--accent:#E6A4BD;--pink:#714A5C;--card:#3C2B33}}
body{margin:0;background:var(--tg-theme-bg-color,#FFF9FB)}main{position:relative;overflow:hidden;padding:16px;border-radius:22px;color:var(--text);background:linear-gradient(145deg,#F6DDE6,#FFF9FB);font-family:ui-rounded,system-ui,sans-serif;line-height:1.45}
@media(prefers-color-scheme:dark){main{background:linear-gradient(145deg,#5A414D,var(--tg-theme-bg-color,#1F1B1E))}}
main::before,main::after{content:'';position:absolute;border-radius:50%;background:rgba(255,255,255,.28);pointer-events:none}main::before{width:120px;height:120px;right:-35px;top:-42px}main::after{width:140px;height:140px;left:-48px;bottom:-65px}main>*{position:relative;z-index:1}
h1{font-size:18px;line-height:1.25;margin:0 0 4px}#summary{font-size:13px;color:var(--muted);margin:0 0 12px}#items{display:grid;gap:8px}
.booking{display:grid;grid-template-columns:auto 1fr auto;gap:9px;align-items:center;width:100%;min-height:44px;padding:10px 12px;border:1px solid var(--line);border-radius:14px;background:var(--pink);color:var(--text);font:inherit;text-align:left;cursor:pointer}
.booking:focus-visible{outline:3px solid var(--accent);outline-offset:2px}.booking.past{opacity:.5}.time{font-weight:700;white-space:nowrap}.details{min-width:0}.client{display:block;font-weight:600}.service{display:block;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.price{font-size:13px;font-weight:600;white-space:nowrap}.source{font-size:12px;font-weight:400}
.row{min-height:44px;display:flex;align-items:center;padding:9px 12px;border-radius:12px;background:var(--card);color:var(--muted);font-size:13px}.free{color:var(--text);background:rgba(255,255,255,.55)}
#revenue{margin:14px 0 0;padding-top:11px;border-top:1px solid var(--line);font-size:13px;font-weight:600}.closed{text-align:center;min-height:100px;justify-content:center}
</style></head><body><main><h1 id="title"></h1><p id="summary"></p><div id="items"></div><p id="revenue"></p></main>
<script>
const W=window.TelegramWidget,items=document.getElementById('items');
function draw(){
 let data={};try{data=JSON.parse(W.chatData||'{}')}catch(e){}
 document.getElementById('title').textContent=data.title||'Расписание дня';document.getElementById('summary').textContent=data.summary||'';document.getElementById('revenue').textContent=data.revenue||'';items.innerHTML='';
 (data.items||[]).forEach(item=>{
  if(item.type==='booking'){
   let button=document.createElement('button');button.type='button';button.className='booking'+(item.past?' past':'');
   let time=document.createElement('span');time.className='time';time.textContent=item.start+'–'+item.end;
   let details=document.createElement('span');details.className='details';
   let client=document.createElement('span');client.className='client';client.textContent=item.client;
   let service=document.createElement('span');service.className='service';service.textContent=item.service;
   let price=document.createElement('span');price.className='price';let icon=item.source==='manual'?'📞':item.source==='reinvite'?'🔁':'📱';price.textContent=icon+' '+item.price;
   details.appendChild(client);details.appendChild(service);button.appendChild(time);button.appendChild(details);button.appendChild(price);
   button.setAttribute('aria-label',item.client+', '+item.service+', '+item.start+', '+item.price);
   button.addEventListener('click',()=>W.request('open:'+item.id));items.appendChild(button);return;
  }
  let row=document.createElement('div');row.className='row '+item.type;
  if(item.type==='free')row.textContent='🟢 Свободно '+item.start+'–'+item.end;
  else if(item.type==='break')row.textContent='🍽 Перерыв '+item.start+'–'+item.end;
  else if(item.type==='block')row.textContent='🚫 '+item.reason+' '+item.start+'–'+item.end;
  else{row.textContent='Выходной день';row.classList.add('closed')}
  items.appendChild(row);
 });
}
W.onEvent('chatDataChanged',draw);draw();W.ready();
</script></body></html>"""


def compress_free_slots(slots: list[datetime], step: timedelta) -> list[dict]:
    ranges = []
    for slot in sorted(slots):
        if ranges and slot == ranges[-1]["_end"]:
            ranges[-1]["_end"] = slot + step
            ranges[-1]["end"] = f"{slot + step:%H:%M}"
        else:
            ranges.append({"type": "free", "start": f"{slot:%H:%M}", "end": f"{slot + step:%H:%M}", "_end": slot + step})
    for item in ranges:
        del item["_end"]
    return ranges


def day_widget_state(db: SalonDB, day: date, now: datetime | None = None) -> str:
    now = now or utc_now()
    bookings = bookings_for_day(db, day)
    free_slots = free_slots_for_day(db, day, now)
    schedule = db.conn.execute(
        "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
        (db.master_id, day.weekday()),
    ).fetchone()
    items = []
    if not schedule or not schedule["is_working"]:
        items = [{"type": "closed"}]
    else:
        for booking in bookings:
            start = local_time(booking["start_at"])
            end = local_time(booking["end_at"])
            items.append({
                "type": "booking", "id": booking["id"],
                "start": f"{start:%H:%M}", "end": f"{end:%H:%M}",
                "client": booking["client_name"], "service": booking["service_name"],
                "price": texts.money(booking["price"]), "source": booking["source"],
                "past": end <= now,
            })
        items.extend(compress_free_slots(free_slots, timedelta(minutes=db.get_master()["slot_step_min"])))
        if schedule["break_start"] and schedule["break_end"]:
            items.append({"type": "break", "start": schedule["break_start"], "end": schedule["break_end"]})
        blocks = db.conn.execute(
            "SELECT * FROM blocks WHERE master_id = ? AND date = ?",
            (db.master_id, day.isoformat()),
        ).fetchall()
        for block in blocks:
            items.append({
                "type": "block", "start": block["start_time"], "end": block["end_time"],
                "reason": block["reason"] or "Блок",
            })
        items.sort(key=lambda item: item.get("start", "99:99"))
    return json.dumps({
        "d": day.isoformat(),
        "title": texts.day_title(day, now.astimezone(LOCAL_TZ).date()).removeprefix("📅 "),
        "summary": texts.day_summary(len(bookings), len(free_slots)),
        "revenue": f"Выручка по записи: {texts.money(sum(row['price'] for row in bookings))}",
        "items": items,
    }, ensure_ascii=False, separators=(",", ":"))


async def send_day_widget(
    bot,
    db: SalonDB,
    day: date,
    master_id: int,
    reply_markup=None,
    fallback: bool = True,
) -> bool:
    if WIDGETS_ENABLED:
        try:
            state = day_widget_state(db, day)
            if len(state.encode("utf-8")) > 1024:
                raise ValueError("Слишком много элементов для состояния виджета")
            message = await bot(SendWidget(
                chat_id=master_id,
                html=DAY_WIDGET_HTML,
                chat_data=state,
                caption=f"📅 Расписание · {texts.format_day(day)}",
                reply_markup=reply_markup or day_keyboard(db, day),
            ))
            message_id = getattr(message, "message_id", None)
            if message_id is not None:
                _day_widgets[master_id] = {"message_id": message_id, "day": day}
            return True
        except Exception as exc:
            if not fallback:
                raise
            logging.warning("Виджет дня недоступен, отправляем текст: %s", exc)
    if fallback:
        _day_widgets.pop(master_id, None)
        await bot.send_message(
            master_id, day_card(db, day), reply_markup=reply_markup or day_keyboard(db, day)
        )
        return False
    return False


async def refresh_open_day(bot, db: SalonDB, master_id: int, day: date | None = None) -> bool:
    current = _day_widgets.get(master_id)
    if not current or (day is not None and current["day"] != day):
        return False
    state = day_widget_state(db, current["day"])
    try:
        await bot(EditMessageWidgetData(
            chat_id=master_id, message_id=current["message_id"], chat_data=state
        ))
        return True
    except Exception:
        old = current.copy()
        try:
            await send_day_widget(bot, db, old["day"], master_id, fallback=False)
            await bot(DeleteMessage(chat_id=master_id, message_id=old["message_id"]))
            return True
        except Exception:
            logging.exception("Не удалось обновить виджет дня мастера %s", master_id)
            _day_widgets.pop(master_id, None)
            await bot.send_message(
                master_id, day_card(db, old["day"]), reply_markup=day_keyboard(db, old["day"])
            )
            return False


async def handle_day_open(query, bot, db: SalonDB, master_id: int, answer) -> bool:
    booking_id = int(query["data"].split(":", 1)[1])
    booking = db.get_booking(booking_id)
    if query["from"]["id"] != master_id or not booking or booking["status"] != "active":
        await answer("invalid")
        return True
    await answer("ok")
    keyboard = inline_keyboard([("❌ Отменить запись", f"admin_cancel:{booking_id}")])
    await bot.send_message(
        query["from"]["id"], texts.booking_card(booking), reply_markup=keyboard
    )
    return True
