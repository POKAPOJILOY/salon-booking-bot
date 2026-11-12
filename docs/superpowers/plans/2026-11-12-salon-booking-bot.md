# Salon Booking Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Create a separate Telegram bot that lets a private manicure master accept bookings and brings clients back after a completed visit.

**Architecture:** One bot and one SQLite database per master. Aiogram handles Telegram flows, a synchronous SQLite data layer performs all booking writes inside `BEGIN IMMEDIATE` transactions, an asyncio scheduler sends reminders and re-invitations, and an optional raw Bot API 10.4 widget supplements the button fallback.

**Tech Stack:** Python 3.11, aiogram 3, SQLite, python-dotenv, pytest, Telegram Bot API 10.4.

## Global Constraints

- Keep `C:/tutor-schedule-bot` unchanged.
- Store timestamps in UTC and display Europe/Moscow.
- One `MASTER_ID` per deployment; all other users are clients.
- No payments, waiting list, Mini App, web admin, multi-master cabinet, or external integrations.
- Put all user-facing strings in `texts.py`.
- Every booking write and reschedule must be atomic and recheck slot availability.
- Test slot generation, overlap rules, booking races, rescheduling rollback, reminders, opt-out, demo, and widget fallback.

---

## Execution Order

Tasks 1–2 provide the minimum storage needed by the demo. Then Tasks 3 and 5 are implemented together as the minimal client path and accelerated demo; Task 4 completes the administration core, Task 6 adds the widget, and Task 7 verifies and publishes the result. Demo clients use separate database client records but send messages to `MASTER_ID`, so the two independent scenarios can be demonstrated in one Telegram chat.

### Task 1: Project configuration and slot generator

**Files:**
- Create: `requirements.txt`, `.env.example`, `.gitignore`, `config.py`, `database.py`
- Test: `tests/test_slots.py`

**Interfaces:**
- `SalonDB.available_slots(service_id: int, day: date, now: datetime | None = None) -> list[datetime]`
- `SalonDB.add_service(name: str, price: int, duration_min: int) -> int`
- `SalonDB.set_schedule(weekday: int, is_working: bool, work_start: str, work_end: str, break_start: str | None, break_end: str | None) -> None`

- [x] Create the package and a test that seeds one service and working hours.
- [x] Test nonworking days, minimum notice, break boundaries, duration beyond closing, and overlapping blocks.
- [x] Run `pytest tests/test_slots.py -v` and confirm failures before implementation.
- [x] Implement schema creation and slot generation with half-open interval overlap checks.
- [x] Run the tests and require PASS.

### Task 2: Clients, bookings, cancellation, and atomic rescheduling

**Files:**
- Create: `database.py`
- Test: `tests/test_bookings.py`

**Interfaces:**
- `SalonDB.create_booking(client_id: int, service_id: int, start_at: datetime, source: str = "link", reinvited_from_id: int | None = None) -> int`
- `SalonDB.reschedule_booking(booking_id: int, start_at: datetime) -> int`
- `SalonDB.cancel_booking(booking_id: int) -> None`
- `SalonDB.upsert_client(tg_id: int, name: str, phone: str) -> int`

- [x] Test duplicate booking rejection and free time after cancellation.
- [x] Test that a forced failure during rescheduling leaves the original active.
- [x] Run tests before implementation and confirm expected failures.
- [x] Implement `BEGIN IMMEDIATE`, fresh conflict checks, client upsert, and rollback.
- [x] Run all booking tests and require PASS.

### Task 3: Public client booking flow and master notifications

**Files:**
- Create: `bot.py`, `texts.py`

**Interfaces:**
- Public `/start`: service → date → time → name → phone → confirmation.
- Client actions: `book`, `reschedule`, `cancel`.
- Master notification: service, client, phone, local start time, source.

- [x] Use fake messages/callbacks to verify the complete flow without calling Telegram.
- [x] Implement FSM states and preserve client data for later re-invitations.
- [x] Verify that the master receives one notification and the client receives action buttons.
- [x] Run flow tests and require PASS.

### Task 4: Master administration

**Files:**
- Create: `bot.py`

**Interfaces:**
- Admin-only menu: link, today/tomorrow bookings, manual booking, block, services, schedule, settings, statistics.
- `SalonDB.statistics() -> dict[str, int]`

- [x] Test that non-master users cannot call admin handlers.
- [x] Implement services, schedules, blocks, manual bookings, settings, and source-based statistics.
- [x] Verify blocked time disappears from slots and statistics distinguish `link`, `manual`, and `reinvite`.
- [x] Run admin tests and require PASS.

### Task 5: Scheduler and accelerated demo

**Files:**
- Create: `scheduler.py`, `demo.py`

**Interfaces:**
- `run_scheduler(bot, db, master_id) -> None`
- `run_demo_scenario(bot, db, master_id) -> None`
- Demo re-invitation after 60 seconds; production interval from `masters.reinvite_days`.

- [x] Test 24-hour and 1-hour reminder flags exactly once.
- [x] Test done transitions and no re-invitation when active, opted out, or blocked.
- [x] Test the accelerated demo creates both tomorrow’s booking and a completed past visit.
- [x] Implement restart catch-up, done status, opt-out, and the two independent demo scenarios.
- [x] Run scheduler and demo tests and require PASS.

### Task 6: Bot API 10.4 widget and button fallback

**Files:**
- Create: `widget.py`, `scheduler.py`

**Interfaces:**
- `send_reinvite_widget(bot, client, service, slots) -> bool`
- Widget tap: atomically create with `source="reinvite"` and stored client data.
- Fallback: ordinary inline buttons when disabled or the API call fails.

- [x] Test disabled and failed-widget fallback.
- [x] Test that two taps create only one booking and a stale slot is replaced.
- [x] Implement raw API calls, slot refresh, and source attribution.
- [x] Run widget tests and require PASS.

### Task 7: Documentation, deployment, verification, and publication

**Files:**
- Create: `README.md`, `deploy/salon-bot.service`

**Interfaces:**
- Local start: copy `.env.example` to `.env`, fill credentials, run `python bot.py`.
- VPS start: systemd service with restart policy and environment file.

- [x] Document accepted decisions and demo instructions.
- [x] Run `pytest -q`, `python -m compileall`, and dependency checks.
- [x] Verify the real Telegram scenario when credentials are available; otherwise report it as unverified.
- [x] Commit the completed project and create a public GitHub repository using `gh`.
