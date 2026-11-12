import json
import logging
from datetime import datetime

from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.methods.base import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message

import texts
from config import WIDGETS_ENABLED
from database import SalonDB, SlotUnavailable, local_time
from keyboards import booking_actions, reinvite_fallback
from notifications import notify_master


class SendWidget(TelegramMethod[Message]):
    chat_id: int
    html: str
    height: int = 320
    chat_data: str
    caption: str
    allow_queries: bool = True
    reply_markup: InlineKeyboardMarkup

    @property
    def __returning__(self):
        return Message

    @property
    def __api_method__(self):
        return "sendWidget"


class AnswerWidgetQuery(TelegramMethod[bool]):
    widget_query_id: str
    data: str

    @property
    def __returning__(self):
        return bool

    @property
    def __api_method__(self):
        return "answerWidgetQuery"


class EditMessageWidgetData(TelegramMethod[bool]):
    chat_id: int
    message_id: int
    chat_data: str

    @property
    def __returning__(self):
        return bool

    @property
    def __api_method__(self):
        return "editMessageWidgetData"


WIDGET_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Свободное время</title>
<style>
:root{--target:24px}@media(pointer:coarse){:root{--target:44px}}
main{font-family:inherit;color:var(--tg-theme-text-color,#17212B)}h1{font-size:17px;line-height:1.25;margin:0 0 4px}#subtitle{font-size:13px;color:var(--tg-theme-hint-color,#7A8A99);margin:0 0 12px}
h2{font-size:14px;font-weight:700;margin:12px 0 6px}ul{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:7px}li{margin:0}
button{min-block-size:var(--target);min-inline-size:var(--target);padding:7px 13px;border:1px solid transparent;border-radius:999px;background:var(--tg-theme-secondary-bg-color,#F1F3F5);color:var(--tg-theme-accent-text-color,#4F8FCC);font:inherit;font-weight:600;cursor:pointer}
button:focus-visible{outline:3px solid var(--tg-theme-accent-text-color,#4F8FCC);outline-offset:2px}button:disabled{opacity:.5;cursor:default}
button.selected{background:var(--tg-theme-button-color,#4F8FCC);color:var(--tg-theme-button-text-color,#FFFFFF);opacity:1}
#status{min-height:20px;color:var(--tg-theme-hint-color,#7A8A99);font-size:13px;line-height:1.4;margin:12px 0 0}
</style></head><body><main><h1 id="title"></h1><p id="subtitle"></p><div id="slots"></div><p id="status" aria-live="polite"></p></main>
<script>
const W=window.TelegramWidget,root=document.getElementById('slots'),status=document.getElementById('status');
function draw(){
 let data={};try{data=JSON.parse(W.chatData||'{}')}catch(e){}
 document.getElementById('title').textContent=data.title||'Свободное время';
 document.getElementById('subtitle').textContent=data.subtitle||'';
 if(data.success){status.textContent='✅ Вы записаны: '+data.success;root.querySelectorAll('button').forEach(b=>b.disabled=true);return}
 root.innerHTML='';status.textContent=data.notice||'';let day='',list=null;
 (data.slots||[]).forEach(slot=>{
  if(slot.d!==day){day=slot.d;let heading=document.createElement('h2');heading.textContent=day;root.appendChild(heading);list=document.createElement('ul');root.appendChild(list)}
  let item=document.createElement('li'),button=document.createElement('button');button.type='button';button.textContent=slot.t;
  button.addEventListener('click',()=>{
   root.querySelectorAll('button').forEach(b=>b.disabled=true);button.classList.add('selected');button.setAttribute('aria-pressed','true');
   status.textContent='Проверяем время…';
   W.request('book:'+data.o+':'+slot.s).then(answer=>{
    let result={};try{result=JSON.parse(answer.result||'{}')}catch(e){}
    if(result.status==='booked'){status.textContent='✅ Вы записаны: '+(result.label||slot.d+', '+slot.t);return}
    if(result.status==='exists'){status.textContent='У вас уже есть активная запись.';return}
    status.textContent=result.status==='stale'?'Это время только что заняли, выберите другое':'Не удалось записаться. Попробуйте ещё раз.';
    button.classList.remove('selected');button.removeAttribute('aria-pressed');root.querySelectorAll('button').forEach(b=>b.disabled=false);
   },error=>{status.textContent='Ошибка: '+error.code;button.classList.remove('selected');button.removeAttribute('aria-pressed');root.querySelectorAll('button').forEach(b=>b.disabled=false)});
  });item.appendChild(button);list.appendChild(item);
 });
 if(!(data.slots||[]).length&&!data.notice)status.textContent='Ближайшие две недели заняты — выберите «Другая дата» под сообщением.';
}
W.onEvent('chatDataChanged',draw);draw();W.ready();
</script></body></html>"""


def widget_header(booking) -> dict:
    return {
        "title": f"{booking['service_name']} · {texts.money(booking['price'])}",
        "subtitle": texts.WIDGET_SUBTITLE,
    }


def widget_state(db: SalonDB, booking, notice: str = "") -> str:
    slots = db.next_slots(booking["service_id"], limit=7, days=14)
    return json.dumps(
        {
            "o": booking["id"],
            **widget_header(booking),
            "slots": [
                {
                    "d": texts.format_day(local_time(slot.isoformat()).date()),
                    "t": f"{local_time(slot.isoformat()):%H:%M}",
                    "s": slot.isoformat(),
                }
                for slot in slots
            ],
            "notice": notice,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def widget_height(db: SalonDB, booking) -> int:
    slots = db.next_slots(booking["service_id"], limit=7, days=14)
    days = {local_time(slot.isoformat()).date() for slot in slots}
    return min(400, max(200, 145 + 55 * max(1, len(days))))


async def send_reinvite_message(bot, db: SalonDB, booking) -> bool:
    caption = texts.reinvite_text(booking["client_name"], booking["reinvite_days"])
    fallback = reinvite_fallback(booking["id"])
    if WIDGETS_ENABLED and booking["is_active"] and db.next_slots(booking["service_id"], limit=1, days=14):
        try:
            await bot(SendWidget(
                chat_id=booking["tg_id"],
                html=WIDGET_HTML,
                height=widget_height(db, booking),
                chat_data=widget_state(db, booking),
                caption=caption,
                reply_markup=fallback,
            ))
            return True
        except Exception as exc:
            logging.warning("Виджет недоступен, отправляем кнопки: %s", exc)
    await bot.send_message(booking["tg_id"], caption, reply_markup=fallback)
    return True


async def handle_widget_update(update, bot, db: SalonDB, master_id: int):
    query = getattr(update, "widget_query", None)
    if not query:
        return UNHANDLED

    async def answer(status: str, label: str | None = None) -> None:
        payload = {"status": status}
        if label:
            payload["label"] = label
        await bot(AnswerWidgetQuery(
            widget_query_id=query["id"],
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ))

    try:
        action, old_id, start_text = query["data"].split(":", 2)
        old = db.get_booking(int(old_id))
        if (
            action != "book" or not old or old["status"] != "done"
            or old["tg_id"] != query["from"]["id"] or not old["is_active"]
        ):
            await answer("invalid")
            return True
        active = db.active_booking_for_client(old["client_id"])
        if active:
            await answer("exists")
            return True
        start = datetime.fromisoformat(start_text)
        if start not in db.next_slots(old["service_id"], limit=7, days=14):
            refreshed = widget_state(db, old, "Это время только что заняли, выберите другое")
            try:
                await bot(EditMessageWidgetData(
                    chat_id=query["chat"]["id"], message_id=query["message_id"], chat_data=refreshed
                ))
            except Exception:
                logging.exception("Не удалось обновить виджет записи %s", old["id"])
            await answer("stale")
            return True
        booking_id = db.create_booking(
            old["client_id"], old["service_id"], start,
            source="reinvite", reinvited_from_id=old["id"],
        )
        local = local_time(start.isoformat())
        label = f"{texts.format_day(local.date())}, {local:%H:%M}"
        await answer("booked", label)
        try:
            await bot(EditMessageWidgetData(
                chat_id=query["chat"]["id"], message_id=query["message_id"],
                chat_data=json.dumps({
                    "o": old["id"], **widget_header(old), "slots": [], "success": label,
                }, ensure_ascii=False, separators=(",", ":")),
            ))
        except Exception:
            logging.exception("Не удалось обновить виджет после записи %s", booking_id)
        booking = db.get_booking(booking_id)
        await bot.send_message(
            booking["tg_id"], texts.confirmation(booking), reply_markup=booking_actions(booking_id)
        )
        await notify_master(bot, master_id, booking)
        return True
    except (SlotUnavailable, ValueError, KeyError):
        try:
            old = db.get_booking(int(query["data"].split(":", 2)[1]))
            if old:
                refreshed = widget_state(db, old, "Это время только что заняли, выберите другое")
                await bot(EditMessageWidgetData(
                    chat_id=query["chat"]["id"], message_id=query["message_id"], chat_data=refreshed
                ))
            await answer("stale")
        except Exception:
            logging.exception("Не удалось ответить виджету")
        return True
    except Exception:
        logging.exception("Ошибка обработки widget_query")
        await answer("error")
        return True
