import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import date, datetime
from datetime import time as day_time
from datetime import timedelta
from urllib.parse import parse_qsl

from aiohttp import web

import texts
from client import valid_name, valid_phone
from database import LOCAL_TZ, SalonDB, SlotUnavailable, local_time, utc_now
from day_widget import compress_free_slots
from keyboards import booking_actions
from notifications import notify_master
from views import bookings_for_day, free_slots_for_day

MAX_INIT_DATA_AGE = 86400

BOT_KEY = web.AppKey("bot")
DB_KEY = web.AppKey("db")
MASTER_ID_KEY = web.AppKey("master_id")
BOT_TOKEN_KEY = web.AppKey("bot_token")
TG_USER_KEY = web.RequestKey("tg_user")

APP_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Запись на маникюр</title>
<style>
:root{color-scheme:light dark;--target:44px;--text:#573B47;--muted:#8B6A78;--accent:#B85C82;--pink:#F2C9D9;--chip-text:#5B3445;--sel:#A94C74;--sel-text:#FFF;--card:#FFF5F9;--line:rgba(139,106,120,.18);--bg:#FFF9FB}
@media(prefers-color-scheme:dark){:root{--text:#F9EEF3;--muted:#D5B8C4;--accent:#E6A4BD;--pink:#714A5C;--chip-text:#FCEBF2;--sel:#D988A8;--sel-text:#24151C;--card:#3C2B33;--bg:#1F1B1E}}
*{box-sizing:border-box}
body{margin:0;background:var(--tg-theme-bg-color,var(--bg));color:var(--tg-theme-text-color,var(--text));font-family:ui-rounded,system-ui,sans-serif;line-height:1.45}
main{position:relative;overflow:hidden;min-height:100vh;padding:18px 16px 28px;background:linear-gradient(145deg,#F6DDE6,var(--tg-theme-bg-color,#FFF9FB))}
@media(prefers-color-scheme:dark){main{background:linear-gradient(145deg,#5A414D,var(--tg-theme-bg-color,#1F1B1E))}}
main::before,main::after{content:'';position:absolute;border-radius:50%;background:rgba(255,255,255,.3);pointer-events:none}
main::before{width:130px;height:130px;right:-40px;top:-48px}main::after{width:150px;height:150px;left:-55px;bottom:-70px}
@media(prefers-color-scheme:dark){main::before,main::after{background:rgba(230,164,189,.1)}}
main>*{position:relative;z-index:1}
h1{font-size:20px;line-height:1.25;margin:0 0 6px}
.sub{font-size:13px;color:var(--muted);margin:0 0 14px}
.grid{display:grid;gap:8px;margin:0 0 6px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 6px}
button{font:inherit;cursor:pointer;border:none}
.chip{min-height:var(--target);padding:9px 16px;border:1px solid rgba(133,73,96,.16);border-radius:999px;background:var(--pink);color:var(--chip-text);font-weight:600;transition:transform .15s,background .15s}
.chip:active{transform:scale(.96)}
.chip:disabled{opacity:.4}
.chip.on{background:var(--sel);color:var(--sel-text)}
.chip.small{min-height:36px;padding:6px 12px;font-size:13px}
.wd{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin:0 0 4px;text-align:center;font-size:12px;color:var(--muted)}
.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin:0 0 8px}
.cal .chip{padding:8px 2px;font-size:13px;border-radius:14px}
.cal .off{visibility:hidden}
.back{background:none;color:var(--accent);font-weight:600;padding:6px 0;margin:0 0 8px;min-height:32px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin:0 0 12px}
.card p{margin:0 0 6px}.card p:last-child{margin:0}
.price{font-weight:700}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
input{width:100%;min-height:var(--target);padding:9px 14px;border:1px solid var(--line);border-radius:14px;background:var(--tg-theme-bg-color,#fff);color:inherit;font:inherit;font-size:16px}
input:focus{outline:2px solid var(--accent)}
.cta{width:100%;min-height:52px;margin:16px 0 0;border-radius:999px;background:var(--sel);color:var(--sel-text);font-size:16px;font-weight:700}
.cta:disabled{opacity:.5}
.err{color:#B4463F;font-size:13px;min-height:18px;margin:8px 0 0}
@media(prefers-color-scheme:dark){.err{color:#E89B93}}
.success{text-align:center;padding:46px 6px 20px}
.success .icon{font-size:46px}
.success h2{font-size:22px;margin:6px 0}
.success p{margin:4px 0}
.note{font-size:12px;color:var(--muted)}
.trust{font-size:12px;color:var(--muted);text-align:center;margin:18px 0 0;padding-top:12px;border-top:1px solid var(--line)}
.bk{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;width:100%;min-height:var(--target);padding:10px 12px;border:1px solid var(--line);border-radius:14px;background:var(--pink);color:var(--text);text-align:left}
.bk.past{opacity:.55}
.bk .t{font-weight:700;white-space:nowrap}
.bk .who{font-weight:600}
.bk .svc{font-size:12px;color:var(--muted)}
.bk .pr{font-size:13px;font-weight:600;white-space:nowrap}
.row{display:flex;align-items:center;min-height:var(--target);padding:9px 12px;border-radius:12px;background:var(--card);color:var(--muted);font-size:13px;margin:0 0 8px}
.row.free{color:var(--text)}
.items{display:grid;gap:8px}
.nav{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:0 0 14px}
.confirmbar{margin:10px 0 0;display:flex;gap:8px}
.danger{background:#B4463F;color:#fff;border-radius:999px;padding:9px 16px;min-height:var(--target);font-weight:600}
.ghost{background:none;color:var(--muted);border-radius:999px;padding:9px 12px;min-height:var(--target)}
.closed{text-align:center;padding:40px 0;color:var(--muted)}
</style></head><body><main id="app"><h1>💅 Загружаем…</h1></main>
<script>
const app=document.getElementById('app');
const initData=(new URLSearchParams(location.hash.slice(1))).get('tgWebAppData')||'';
const params=new URLSearchParams(location.search);
const masterMode=location.pathname.indexOf('master')>-1;
const money=n=>new Intl.NumberFormat('ru-RU').format(n)+' ₽';
const esc=(t)=>{const s=document.createElement('span');s.textContent=t;return s};
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
async function api(path,opts){
 opts=opts||{};opts.headers=Object.assign({'X-Telegram-Init-Data':initData},opts.headers||{});
 if(opts.body)opts.headers['Content-Type']='application/json';
 const r=await fetch(path,opts);let data={};try{data=await r.json()}catch(e){}
 if(!r.ok)throw new Error(data.error||('Ошибка '+r.status));
 return data;
}
function header(title,sub,back){
 app.innerHTML='';
 if(back){const b=el('button','back','← Назад');b.onclick=back;app.appendChild(b)}
 app.appendChild(el('h1','',title));
 if(sub)app.appendChild(el('p','sub',sub));
}
function fail(msg){app.innerHTML='';app.appendChild(el('h1','','💅'));app.appendChild(el('p','sub',msg))}

/* ---------- клиент ---------- */
const S={step:'service',invite:params.get('invite'),service:null,day:null,slot:null,info:null};
async function startClient(){
 try{
  if(S.invite){
   S.info=await api('/api/invite?token='+encodeURIComponent(S.invite));
   S.service={id:S.info.service_id,name:S.info.service_name,price:S.info.price,duration_min:S.info.duration_min};
   S.step='day';
  }else{
   S.services=(await api('/api/services')).services;
   if(!S.services.length){fail('Пока нет доступных услуг. Загляните позже!');return}
  }
  render();
 }catch(e){fail(e.message)}
}
function render(){
 if(S.step==='service')return renderServices();
 if(S.step==='day')return renderDays();
 if(S.step==='slot')return renderSlots();
 if(S.step==='confirm')return renderConfirm();
}
function renderServices(){
 header('💅 Запись на маникюр','Выберите услугу');
 const list=el('div','grid');
 S.services.forEach(s=>{
  const b=el('button','chip',s.name+' · '+money(s.price)+' · '+s.duration_min+' мин');
  b.style.width='100%';b.onclick=()=>{S.service=s;S.step='day';render()};
  list.appendChild(b);
 });
 app.appendChild(list);
 app.appendChild(el('p','trust','Перенос и отмена — в один тап'));
}
async function renderDays(){
 header(S.invite?'💅 Пора обновить маникюр! ✨':'📅 Выберите дату',
  S.service.name+' · '+money(S.service.price),
  S.invite?null:()=>{S.step='service';render()});
 try{
  const data=await api('/api/days?service_id='+S.service.id);
  const open={};data.days.forEach(d=>open[d.date]=d.label);
  const wd=el('div','wd');['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].forEach(d=>wd.appendChild(el('span','',d)));
  const cal=el('div','cal');
  let first=null,cells=[];
  for(let i=0;i<14;i++){
   const d=new Date(data.today+'T00:00:00');d.setDate(d.getDate()+i);
   const iso=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
   cells.push({iso:iso,day:d.getDate(),wd:(d.getDay()+6)%7,on:!!open[iso]});
  }
  for(let i=0;i<cells[0].wd;i++)cal.appendChild(el('span','off'));
  cells.forEach(c=>{
   const b=el('button','chip',String(c.day));
   if(!c.on){b.disabled=true}else{b.onclick=()=>{S.day=c.iso;S.step='slot';render()}}
   cal.appendChild(b);
  });
  app.appendChild(wd);app.appendChild(cal);
  if(!data.days.length)app.appendChild(el('p','sub','Ближайшие две недели заняты — загляните позже.'));
 }catch(e){app.appendChild(el('p','err',e.message))}
}
async function renderSlots(){
 header('🕐 Выберите время',S.service.name+' · '+money(S.service.price),
  ()=>{S.step='day';render()});
 try{
  const data=await api('/api/slots?service_id='+S.service.id+'&date='+S.day);
  app.appendChild(el('p','sub',data.label));
  const chips=el('div','chips');
  data.slots.forEach(s=>{
   const b=el('button','chip',s.time);
   b.onclick=()=>{S.slot=s;S.step='confirm';render()};
   chips.appendChild(b);
  });
  app.appendChild(chips);
  if(!data.slots.length)app.appendChild(el('p','sub','На этот день свободного времени уже нет.'));
 }catch(e){app.appendChild(el('p','err',e.message))}
}
function renderConfirm(){
 header('✨ Проверьте детали','',()=>{S.step='slot';render()});
 const card=el('div','card');
 card.appendChild(el('p','',S.service.name));
 card.appendChild(el('p','price',money(S.service.price)));
 card.appendChild(el('p','',S.slot.label+', '+S.slot.time));
 app.appendChild(card);
 app.appendChild(el('label','','Ваше имя'));
 const name=el('input');name.value=(S.info&&S.info.name)||'';app.appendChild(name);
 app.appendChild(el('label','','Телефон'));
 const phone=el('input');phone.type='tel';phone.value=(S.info&&S.info.phone)||'';app.appendChild(phone);
 const err=el('p','err','');app.appendChild(err);
 const cta=el('button','cta','Записаться');
 cta.onclick=async()=>{
  err.textContent='';cta.disabled=true;cta.textContent='Записываем…';
  try{
   const data=await api('/api/booking',{method:'POST',body:JSON.stringify({
    service_id:S.service.id,date:S.day,time:S.slot.time,
    invite_token:S.invite||undefined,name:name.value,phone:phone.value})});
   renderSuccess(data.booking);
  }catch(e){err.textContent=e.message;cta.disabled=false;cta.textContent='Записаться'}
 };
 app.appendChild(cta);
 app.appendChild(el('p','trust','Перенос и отмена — в один тап'));
}
function renderSuccess(b){
 app.innerHTML='';
 const box=el('div','success');
 box.appendChild(el('div','icon','💅'));
 box.appendChild(el('h2','','Вы записаны!'));
 box.appendChild(el('p','',b.day_label+', '+b.time));
 box.appendChild(el('p','',b.service_name+' · '+money(b.price)));
 box.appendChild(el('p','note','Напомним за 24 часа'));
 app.appendChild(box);
 app.appendChild(el('p','trust','Детали и кнопки переноса — в сообщении от бота'));
}

/* ---------- мастер ---------- */
const M={date:params.get('date'),data:null,selected:null};
async function loadDay(){
 try{
  M.data=await api('/api/day'+(M.date?'?date='+M.date:''));
  M.date=M.data.date;M.selected=null;renderMaster();
 }catch(e){fail(e.message)}
}
function renderMaster(){
 const d=M.data;
 header('📅 '+d.title,d.summary);
 const nav=el('div','nav');
 const prev=el('button','chip small','⬅ Вчера');prev.onclick=()=>{M.date=d.prev;loadDay()};
 const today=el('button','chip small','Сегодня');today.onclick=()=>{M.date=null;loadDay()};
 const next=el('button','chip small','Завтра ➡');next.onclick=()=>{M.date=d.next;loadDay()};
 nav.appendChild(prev);nav.appendChild(today);nav.appendChild(next);app.appendChild(nav);
 if(d.closed){app.appendChild(el('div','closed','Выходной день'));return}
 const items=el('div','items');
 d.items.forEach(item=>{
  if(item.type==='booking'){
   const b=el('button','bk'+(item.past?' past':''));
   b.appendChild(el('span','t',item.start+'–'+item.end));
   const who=el('span','');who.appendChild(el('span','who',item.client));who.appendChild(el('span','svc',' '+item.service));
   b.appendChild(who);
   const icon=item.source==='manual'?'📞':item.source==='reinvite'?'🔁':'📱';
   b.appendChild(el('span','pr',icon+' '+item.price));
   b.onclick=()=>{M.selected=M.selected===item.id?null:item.id;renderMaster()};
   items.appendChild(b);
   if(M.selected===item.id){
    const bar=el('div','confirmbar');
    const yes=el('button','danger','❌ Отменить запись');
    yes.onclick=()=>cancelBooking(item.id);
    const no=el('button','ghost','Оставить');
    no.onclick=()=>{M.selected=null;renderMaster()};
    bar.appendChild(yes);bar.appendChild(no);items.appendChild(bar);
   }
   return;
  }
  const row=el('div','row'+(item.type==='free'?' free':''));
  if(item.type==='free')row.textContent='🟢 Свободно '+item.start+'–'+item.end;
  else if(item.type==='break')row.textContent='🍽 Перерыв '+item.start+'–'+item.end;
  else row.textContent='🚫 '+item.reason+' '+item.start+'–'+item.end;
  items.appendChild(row);
 });
 app.appendChild(items);
 app.appendChild(el('p','trust',d.revenue));
}
async function cancelBooking(id){
 try{await api('/api/day/cancel',{method:'POST',body:JSON.stringify({booking_id:id})});await loadDay()}
 catch(e){fail(e.message)}
}

if(masterMode){loadDay()}else{startClient()}
</script></body></html>"""


def validate_init_data(init_data: str, bot_token: str, max_age: int = MAX_INIT_DATA_AGE) -> dict | None:
    if not init_data or not bot_token:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        return None
    if time.time() - auth_date > max_age:
        return None
    try:
        return json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    init_data = request.headers.get("X-Telegram-Init-Data", "") or request.query.get("init_data", "")
    user = validate_init_data(init_data, request.app[BOT_TOKEN_KEY])
    if not user or not user.get("id"):
        raise web.HTTPUnauthorized(text="Недействительные данные Telegram")
    if (request.path == "/api/day" or request.path.startswith("/api/day/")) and user["id"] != request.app[MASTER_ID_KEY]:
        raise web.HTTPForbidden(text="Этот раздел доступен только мастеру")
    request[TG_USER_KEY] = user
    return await handler(request)


async def page(request: web.Request) -> web.Response:
    return web.Response(text=APP_HTML, content_type="text/html")


async def services_list(request: web.Request) -> web.Response:
    db: SalonDB = request.app[DB_KEY]
    return web.json_response({
        "services": [
            {"id": row["id"], "name": row["name"], "price": row["price"], "duration_min": row["duration_min"]}
            for row in db.list_services()
        ]
    })


def _query_int(request: web.Request, name: str) -> int:
    try:
        return int(request.query[name])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(text=f"Некорректный параметр {name}")


async def days_list(request: web.Request) -> web.Response:
    db: SalonDB = request.app[DB_KEY]
    service_id = _query_int(request, "service_id")
    days = db.available_dates(service_id, days=14)
    today = utc_now().astimezone(LOCAL_TZ).date()
    return web.json_response({
        "today": today.isoformat(),
        "days": [{"date": day.isoformat(), "label": texts.format_day(day)} for day in days],
    })


async def slots_list(request: web.Request) -> web.Response:
    db: SalonDB = request.app[DB_KEY]
    service_id = _query_int(request, "service_id")
    try:
        day = date.fromisoformat(request.query["date"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(text="Некорректная дата")
    slots = db.available_slots(service_id, day)
    return web.json_response({
        "label": texts.format_day(day),
        "slots": [
            {"time": f"{local_time(slot.isoformat()):%H:%M}", "start": slot.isoformat(), "label": texts.format_day(day)}
            for slot in slots
        ],
    })


async def invite_info(request: web.Request) -> web.Response:
    db: SalonDB = request.app[DB_KEY]
    user = request[TG_USER_KEY]
    try:
        old = db.get_booking(int(request.query.get("token", "")))
    except ValueError:
        old = None
    if not old or old["status"] != "done" or old["tg_id"] != user["id"]:
        raise web.HTTPForbidden(text="Приглашение недействительно")
    return web.json_response({
        "service_id": old["service_id"],
        "service_name": old["service_name"],
        "price": old["price"],
        "duration_min": old["duration_min"],
        "name": old["client_name"],
        "phone": old["phone"],
    })


async def booking_create(request: web.Request) -> web.Response:
    db: SalonDB = request.app[DB_KEY]
    bot = request.app[BOT_KEY]
    master_id = request.app[MASTER_ID_KEY]
    user = request[TG_USER_KEY]
    try:
        data = await request.json()
        service_id = int(data["service_id"])
        day = date.fromisoformat(data["date"])
        start = datetime.combine(day, day_time.fromisoformat(data["time"]), LOCAL_TZ)
    except (ValueError, KeyError, TypeError):
        raise web.HTTPBadRequest(text="Некорректные данные записи")

    invite_token = data.get("invite_token")
    source, reinvited_from_id = "link", None
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    if invite_token:
        try:
            old = db.get_booking(int(invite_token))
        except ValueError:
            old = None
        if not old or old["status"] != "done" or old["tg_id"] != user["id"]:
            raise web.HTTPForbidden(text="Приглашение недействительно")
        if db.active_booking_for_client(old["client_id"]):
            return web.json_response({"error": "У вас уже есть активная запись"}, status=409)
        name = name or old["client_name"]
        phone = phone or old["phone"]
        source, reinvited_from_id = "reinvite", old["id"]
    if not name:
        name = user.get("first_name", "")
    if not valid_name(name):
        return web.json_response({"error": texts.INVALID_NAME}, status=400)
    if not valid_phone(phone):
        return web.json_response({"error": texts.INVALID_PHONE}, status=400)
    client_id = db.upsert_client(user["id"], name, phone)
    try:
        booking_id = db.create_booking(
            client_id, service_id, start, source=source, reinvited_from_id=reinvited_from_id
        )
    except SlotUnavailable:
        return web.json_response({"error": texts.SLOT_TAKEN}, status=409)
    except ValueError:
        return web.json_response({"error": "Не удалось создать запись"}, status=400)

    booking = db.get_booking(booking_id)
    await bot.send_message(
        booking["tg_id"], texts.confirmation(booking), reply_markup=booking_actions(booking_id)
    )
    await notify_master(bot, master_id, booking)
    from day_widget import refresh_open_day

    await refresh_open_day(bot, db, master_id, local_time(booking["start_at"]).date())
    local = local_time(booking["start_at"])
    return web.json_response({
        "ok": True,
        "booking": {
            "id": booking_id,
            "service_name": booking["service_name"],
            "price": booking["price"],
            "day_label": texts.format_day(local.date()),
            "time": f"{local:%H:%M}",
        },
    })


def master_day_payload(db: SalonDB, day: date, now: datetime | None = None) -> dict:
    now = now or utc_now()
    bookings = bookings_for_day(db, day)
    free_slots = free_slots_for_day(db, day, now)
    schedule = db.conn.execute(
        "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
        (db.master_id, day.weekday()),
    ).fetchone()
    closed = not schedule or not schedule["is_working"]
    items = []
    if not closed:
        for booking in bookings:
            start_local = local_time(booking["start_at"])
            end_local = local_time(booking["end_at"])
            items.append({
                "type": "booking", "id": booking["id"],
                "start": f"{start_local:%H:%M}", "end": f"{end_local:%H:%M}",
                "client": booking["client_name"], "service": booking["service_name"],
                "price": texts.money(booking["price"]), "source": booking["source"],
                "past": end_local <= now,
            })
        items.extend(
            {"type": "free", "start": slot["start"], "end": slot["end"]}
            for slot in compress_free_slots(free_slots, timedelta(minutes=db.get_master()["slot_step_min"]))
        )
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
        items.sort(key=lambda item: item["start"])
    today = now.astimezone(LOCAL_TZ).date()
    return {
        "date": day.isoformat(),
        "title": texts.day_title(day, today).removeprefix("📅 "),
        "summary": texts.day_summary(len(bookings), len(free_slots)),
        "revenue": f"Выручка по записи: {texts.money(sum(row['price'] for row in bookings))}",
        "closed": closed,
        "items": items,
        "prev": (day - timedelta(days=1)).isoformat(),
        "next": (day + timedelta(days=1)).isoformat(),
    }


async def day_view(request: web.Request) -> web.Response:
    db: SalonDB = request.app[DB_KEY]
    raw = request.query.get("date")
    try:
        day = date.fromisoformat(raw) if raw else utc_now().astimezone(LOCAL_TZ).date()
    except ValueError:
        raise web.HTTPBadRequest(text="Некорректная дата")
    return web.json_response(master_day_payload(db, day))


async def day_cancel(request: web.Request) -> web.Response:
    db: SalonDB = request.app[DB_KEY]
    bot = request.app[BOT_KEY]
    master_id = request.app[MASTER_ID_KEY]
    try:
        data = await request.json()
        booking_id = int(data["booking_id"])
    except (ValueError, KeyError, TypeError):
        raise web.HTTPBadRequest(text="Некорректный номер записи")
    try:
        booking = db.cancel_booking(booking_id)
    except ValueError:
        return web.json_response({"error": texts.BOOKING_NOT_FOUND}, status=404)
    if booking["tg_id"]:
        try:
            await bot.send_message(booking["tg_id"], texts.ADMIN_CLIENT_CANCELLED)
        except Exception:
            logging.exception("Не удалось уведомить клиента об отмене записи %s", booking_id)
    from day_widget import refresh_open_day

    await refresh_open_day(bot, db, master_id, local_time(booking["start_at"]).date())
    return web.json_response({"ok": True})


def create_app(bot, db: SalonDB, master_id: int, bot_token: str) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app[BOT_KEY] = bot
    app[DB_KEY] = db
    app[MASTER_ID_KEY] = master_id
    app[BOT_TOKEN_KEY] = bot_token
    app.router.add_get("/", page)
    app.router.add_get("/app", page)
    app.router.add_get("/app/master", page)
    app.router.add_get("/api/services", services_list)
    app.router.add_get("/api/days", days_list)
    app.router.add_get("/api/slots", slots_list)
    app.router.add_get("/api/invite", invite_info)
    app.router.add_post("/api/booking", booking_create)
    app.router.add_get("/api/day", day_view)
    app.router.add_post("/api/day/cancel", day_cancel)
    return app


async def run(bot, db: SalonDB, master_id: int, bot_token: str, port: int) -> None:
    runner = web.AppRunner(create_app(bot, db, master_id, bot_token))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("Mini App сервер слушает порт %s", port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
