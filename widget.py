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
<html lang="ru"><head><meta charset="utf-8"><meta name="color-scheme" content="light dark"><title>Время для маникюра</title>
<style>
:root{color-scheme:light dark;--target:44px;--salon-text:#573B47;--salon-muted:#8B6A78;--salon-accent:#B85C82;--salon-chip:#F2C9D9;--salon-chip-text:#5B3445;--salon-selected:#A94C74;--salon-selected-text:#FFF}
@media(prefers-color-scheme:dark){:root{--salon-text:#F9EEF3;--salon-muted:#D5B8C4;--salon-accent:#E6A4BD;--salon-chip:#714A5C;--salon-chip-text:#FCEBF2;--salon-selected:#D988A8;--salon-selected-text:#24151C}}
body{margin:0;background:var(--tg-theme-bg-color,#FFF9FB)}main{position:relative;overflow:hidden;padding:16px;border-radius:22px;font-family:inherit;color:var(--salon-text);background:linear-gradient(145deg,#F6DDE6,#FFF9FB)}
@media(prefers-color-scheme:dark){main{background:linear-gradient(145deg,#5A414D,var(--tg-theme-bg-color,#1F1B1E))}}
main::before,main::after{content:'';position:absolute;border-radius:50%;background:rgba(255,255,255,.3);pointer-events:none}main::before{width:120px;height:120px;right:-35px;top:-42px}main::after{width:140px;height:140px;left:-48px;bottom:-65px}
@media(prefers-color-scheme:dark){main::before,main::after{background:rgba(230,164,189,.1)}}main>*{position:relative;z-index:1}
h1{font-size:19px;line-height:1.25;margin:0 0 7px}#title{font-size:14px;font-weight:600;margin:0 0 3px}#subtitle{font-size:13px;color:var(--salon-muted);margin:0 0 12px}
h2{font-size:14px;font-weight:700;margin:12px 0 6px}ul{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:8px}li{margin:0}
button{min-block-size:var(--target);min-inline-size:var(--target);padding:8px 15px;border:1px solid rgba(133,73,96,.16);border-radius:999px;background:var(--salon-chip);color:var(--salon-chip-text);font:inherit;font-weight:600;cursor:pointer;transition:background-color .16s,color .16s,opacity .16s,transform .16s}
button:focus-visible{outline:3px solid var(--salon-accent);outline-offset:2px}button:disabled{opacity:.5;cursor:default}button.selected{background:var(--salon-selected);color:var(--salon-selected-text);opacity:1;transform:scale(1.04)}
button.leaving{opacity:0;transform:scale(.85)}@media(hover:hover){button:hover{transform:translateY(-1px)}}
#status{min-height:20px;color:var(--salon-muted);font-size:13px;line-height:1.4;margin:12px 0 0}.trust{font-size:12px;color:var(--salon-muted);margin:14px 0 0;padding-top:10px;border-top:1px solid rgba(139,106,120,.18)}
#success{text-align:center;padding:18px 4px 8px}.success-icon{font-size:36px}.success-title{font-size:20px;font-weight:700;margin:5px 0}#success-details{font-size:15px;margin:0}#success-note{font-size:12px;color:var(--salon-muted);margin:7px 0 0}
@media(prefers-reduced-motion:reduce){button{transition-duration:.01s}}
</style></head><body><main><h1 id="headline">💅 Пора обновить маникюр! ✨</h1><p id="title"></p><p id="subtitle"></p><div id="slots"></div><p id="status" aria-live="polite"></p><div id="success" hidden><div class="success-icon">💅</div><div class="success-title">Вы записаны!</div><p id="success-details"></p><p id="success-note">Напомним за 24 часа</p></div><p class="trust">Перенос и отмена — в один тап</p></main>
<script>
const W=window.TelegramWidget,root=document.getElementById('slots'),status=document.getElementById('status');
function showSuccess(label){root.hidden=true;status.hidden=true;document.getElementById('success').hidden=false;document.getElementById('success-details').textContent=label}
function render(data){
 root.hidden=false;status.hidden=false;document.getElementById('success').hidden=true;status.textContent=data.notice||'';let day='',list=null;
 (data.slots||[]).forEach(slot=>{
  if(slot.d!==day){day=slot.d;let heading=document.createElement('h2');heading.textContent=day;root.appendChild(heading);list=document.createElement('ul');root.appendChild(list)}
  let item=document.createElement('li'),button=document.createElement('button');button.type='button';button.textContent=slot.t;button.setAttribute('data-slot',slot.s);
  button.addEventListener('click',()=>{
   root.querySelectorAll('button').forEach(b=>b.disabled=true);button.classList.add('selected');button.setAttribute('aria-pressed','true');status.textContent='Проверяем…';
   W.request('book:'+data.o+':'+slot.s).then(answer=>{
    let result={};try{result=JSON.parse(answer.result||'{}')}catch(e){}
    if(result.status==='booked'){showSuccess(result.label||slot.d+', '+slot.t);return}
    if(result.status==='exists'){status.textContent='У вас уже есть активная запись.';return}
    status.textContent=result.status==='stale'?'Это время только что заняли, выберите другое':'Не удалось записаться. Попробуйте ещё раз.';
    button.classList.remove('selected');button.removeAttribute('aria-pressed');root.querySelectorAll('button').forEach(b=>b.disabled=false);
   },error=>{status.textContent='Ошибка: '+error.code;button.classList.remove('selected');button.removeAttribute('aria-pressed');root.querySelectorAll('button').forEach(b=>b.disabled=false)});
  });item.appendChild(button);list.appendChild(item);
 });
 if(!(data.slots||[]).length&&!data.notice)status.textContent='Ближайшие две недели заняты — выберите «Другая дата» под сообщением.';
}
function draw(){
 let data={};try{data=JSON.parse(W.chatData||'{}')}catch(e){}
 document.getElementById('headline').textContent=data.headline||'💅 Пора обновить маникюр! ✨';
 document.getElementById('title').textContent=data.title||'';document.getElementById('subtitle').textContent=data.subtitle||'';
 if(data.success){showSuccess(data.success);return}
 let fresh=data.slots||[],stale=false;root.querySelectorAll('button[data-slot]').forEach(button=>{if(!fresh.some(slot=>slot.s===button.getAttribute('data-slot'))){button.classList.add('leaving');stale=true}});
 if(stale){setTimeout(()=>{root.innerHTML='';render(data)},160);return}
 root.innerHTML='';render(data);
}
W.onEvent('chatDataChanged',draw);draw();W.ready();
</script></body></html>"""


def widget_header(booking) -> dict:
    return {
        "headline": texts.WIDGET_HEADLINE,
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
    return min(400, max(220, 175 + 55 * max(1, len(days))))


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
