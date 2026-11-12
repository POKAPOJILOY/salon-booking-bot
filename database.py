import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from config import DB_PATH, MASTER_ID, TZ

LOCAL_TZ = TZ
UTC = timezone.utc


class SlotUnavailable(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Дата и время должны содержать часовой пояс")
    return value.astimezone(UTC)


def db_time(value: datetime) -> str:
    return to_utc(value).isoformat(timespec="seconds")


def from_db_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def local_time(value: str) -> datetime:
    return from_db_time(value).astimezone(LOCAL_TZ)


class SalonDB:
    def __init__(self, path: str | Path = DB_PATH, master_id: int = MASTER_ID):
        self.path = str(path)
        self.master_id = master_id
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, timeout=5, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS masters (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                reinvite_days INTEGER NOT NULL DEFAULT 21,
                min_notice_hours INTEGER NOT NULL DEFAULT 2,
                slot_step_min INTEGER NOT NULL DEFAULT 30,
                demo_mode INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id INTEGER NOT NULL REFERENCES masters(tg_id),
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                duration_min INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS schedules (
                master_id INTEGER NOT NULL REFERENCES masters(tg_id),
                weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
                is_working INTEGER NOT NULL,
                work_start TEXT NOT NULL,
                work_end TEXT NOT NULL,
                break_start TEXT,
                break_end TEXT,
                PRIMARY KEY(master_id, weekday)
            );
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id INTEGER NOT NULL REFERENCES masters(tg_id),
                tg_id INTEGER,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                reinvite_opt_out INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id INTEGER NOT NULL REFERENCES masters(tg_id),
                client_id INTEGER NOT NULL REFERENCES clients(id),
                service_id INTEGER NOT NULL REFERENCES services(id),
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'cancelled', 'done')),
                source TEXT NOT NULL CHECK(source IN ('link', 'manual', 'reinvite')),
                reinvited_from_id INTEGER REFERENCES bookings(id),
                created_at TEXT NOT NULL,
                reminder24_sent INTEGER NOT NULL DEFAULT 0,
                reminder1_sent INTEGER NOT NULL DEFAULT 0,
                reinvite_sent INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_bookings_master_status_time
                ON bookings(master_id, status, start_at, end_at);
            CREATE INDEX IF NOT EXISTS idx_bookings_client_status
                ON bookings(client_id, status);
            CREATE TABLE IF NOT EXISTS blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id INTEGER NOT NULL REFERENCES masters(tg_id),
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                reason TEXT
            );
            """
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO masters(tg_id, created_at) VALUES (?, ?)",
            (self.master_id, db_time(utc_now())),
        )

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    def get_master(self) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM masters WHERE tg_id = ?", (self.master_id,)).fetchone()

    def update_master(self, **values) -> None:
        allowed = {"username", "reinvite_days", "min_notice_hours", "slot_step_min", "demo_mode"}
        if not values or not set(values) <= allowed:
            raise ValueError("Неизвестные настройки мастера")
        fields = ", ".join(f"{key} = ?" for key in values)
        with self.transaction() as conn:
            conn.execute(
                f"UPDATE masters SET {fields} WHERE tg_id = ?",
                (*values.values(), self.master_id),
            )

    def add_service(self, name: str, price: int, duration_min: int) -> int:
        if not name.strip() or price < 0 or duration_min <= 0:
            raise ValueError("Некорректные параметры услуги")
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO services(master_id, name, price, duration_min) VALUES (?, ?, ?, ?)",
                (self.master_id, name.strip(), price, duration_min),
            )
            return cursor.lastrowid

    def get_service(self, service_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM services WHERE id = ? AND master_id = ?",
            (service_id, self.master_id),
        ).fetchone()

    def list_services(self, include_inactive: bool = False) -> list[sqlite3.Row]:
        condition = "" if include_inactive else "AND is_active = 1"
        return self.conn.execute(
            f"SELECT * FROM services WHERE master_id = ? {condition} ORDER BY id",
            (self.master_id,),
        ).fetchall()

    def set_schedule(
        self,
        weekday: int,
        is_working: bool,
        work_start: str = "10:00",
        work_end: str = "19:00",
        break_start: str | None = None,
        break_end: str | None = None,
    ) -> None:
        if weekday not in range(7):
            raise ValueError("День недели должен быть от 0 до 6")
        if bool(break_start) != bool(break_end):
            raise ValueError("Нужны обе границы перерыва")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO schedules(master_id, weekday, is_working, work_start, work_end, break_start, break_end)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(master_id, weekday) DO UPDATE SET
                    is_working = excluded.is_working,
                    work_start = excluded.work_start,
                    work_end = excluded.work_end,
                    break_start = excluded.break_start,
                    break_end = excluded.break_end
                """,
                (
                    self.master_id,
                    weekday,
                    int(is_working),
                    work_start,
                    work_end,
                    break_start,
                    break_end,
                ),
            )

    def get_schedules(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM schedules WHERE master_id = ? ORDER BY weekday",
            (self.master_id,),
        ).fetchall()

    def add_block(self, day: date, start_time: str, end_time: str, reason: str | None = None) -> int:
        start = time.fromisoformat(start_time)
        end = time.fromisoformat(end_time)
        if start >= end:
            raise ValueError("Конец блокировки должен быть позже начала")
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO blocks(master_id, date, start_time, end_time, reason) VALUES (?, ?, ?, ?, ?)",
                (self.master_id, day.isoformat(), start_time, end_time, reason or None),
            )
            return cursor.lastrowid

    def upsert_client(self, tg_id: int, name: str, phone: str) -> int:
        if not name.strip() or not phone.strip():
            raise ValueError("Имя и телефон обязательны")
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM clients WHERE master_id = ? AND tg_id = ? ORDER BY id LIMIT 1",
                (self.master_id, tg_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE clients SET name = ?, phone = ? WHERE id = ?",
                    (name.strip(), phone.strip(), row["id"]),
                )
                return row["id"]
            cursor = conn.execute(
                "INSERT INTO clients(master_id, tg_id, name, phone, created_at) VALUES (?, ?, ?, ?, ?)",
                (self.master_id, tg_id, name.strip(), phone.strip(), db_time(utc_now())),
            )
            return cursor.lastrowid

    def create_client(self, tg_id: int | None, name: str, phone: str) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO clients(master_id, tg_id, name, phone, created_at) VALUES (?, ?, ?, ?, ?)",
                (self.master_id, tg_id, name.strip(), phone.strip(), db_time(utc_now())),
            )
            return cursor.lastrowid

    def get_client(self, client_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM clients WHERE id = ? AND master_id = ?",
            (client_id, self.master_id),
        ).fetchone()

    def get_client_by_tg(self, tg_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM clients WHERE master_id = ? AND tg_id = ? ORDER BY id LIMIT 1",
            (self.master_id, tg_id),
        ).fetchone()

    def get_booking(self, booking_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT b.*, s.name AS service_name, s.price, s.duration_min, s.is_active,
                   c.tg_id, c.name AS client_name, c.phone, c.reinvite_opt_out,
                   m.reinvite_days, m.demo_mode
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            JOIN clients c ON c.id = b.client_id
            JOIN masters m ON m.tg_id = b.master_id
            WHERE b.id = ? AND b.master_id = ?
            """,
            (booking_id, self.master_id),
        ).fetchone()

    def active_booking_for_client(self, client_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM bookings WHERE client_id = ? AND status = 'active' ORDER BY start_at LIMIT 1",
            (client_id,),
        ).fetchone()

    def _slot_available(
        self,
        conn: sqlite3.Connection,
        service: sqlite3.Row,
        master: sqlite3.Row,
        start: datetime,
        now: datetime,
        exclude_booking_id: int | None = None,
    ) -> bool:
        start_utc = to_utc(start)
        end_utc = start_utc + timedelta(minutes=service["duration_min"])
        if start_utc < to_utc(now) + timedelta(hours=master["min_notice_hours"]):
            return False
        start_local = start_utc.astimezone(LOCAL_TZ)
        end_local = end_utc.astimezone(LOCAL_TZ)
        if start_local.date() != end_local.date():
            return False
        schedule = conn.execute(
            "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
            (self.master_id, start_local.weekday()),
        ).fetchone()
        if not schedule or not schedule["is_working"]:
            return False
        work_start = datetime.combine(start_local.date(), time.fromisoformat(schedule["work_start"]), LOCAL_TZ)
        work_end = datetime.combine(start_local.date(), time.fromisoformat(schedule["work_end"]), LOCAL_TZ)
        if start_local < work_start or end_local > work_end:
            return False
        if schedule["break_start"] and schedule["break_end"]:
            break_start = datetime.combine(start_local.date(), time.fromisoformat(schedule["break_start"]), LOCAL_TZ)
            break_end = datetime.combine(start_local.date(), time.fromisoformat(schedule["break_end"]), LOCAL_TZ)
            if start_local < break_end and break_start < end_local:
                return False
        exclusion = "AND id != ?" if exclude_booking_id is not None else ""
        params: list = [self.master_id, db_time(end_utc), db_time(start_utc)]
        if exclude_booking_id is not None:
            params.append(exclude_booking_id)
        conflict = conn.execute(
            f"""
            SELECT 1 FROM bookings
            WHERE master_id = ? AND status = 'active'
              AND start_at < ? AND end_at > ? {exclusion}
            LIMIT 1
            """,
            params,
        ).fetchone()
        if conflict:
            return False
        for block in conn.execute(
            "SELECT * FROM blocks WHERE master_id = ? AND date = ?",
            (self.master_id, start_local.date().isoformat()),
        ):
            block_start = datetime.combine(start_local.date(), time.fromisoformat(block["start_time"]), LOCAL_TZ)
            block_end = datetime.combine(start_local.date(), time.fromisoformat(block["end_time"]), LOCAL_TZ)
            if start_local < block_end and block_start < end_local:
                return False
        return True

    def available_slots(self, service_id: int, day: date, now: datetime | None = None) -> list[datetime]:
        service = self.get_service(service_id)
        master = self.get_master()
        if not service or not service["is_active"]:
            return []
        schedule = self.conn.execute(
            "SELECT * FROM schedules WHERE master_id = ? AND weekday = ?",
            (self.master_id, day.weekday()),
        ).fetchone()
        if not schedule or not schedule["is_working"]:
            return []
        now = now or utc_now()
        work_start = datetime.combine(day, time.fromisoformat(schedule["work_start"]), LOCAL_TZ)
        work_end = datetime.combine(day, time.fromisoformat(schedule["work_end"]), LOCAL_TZ)
        step = timedelta(minutes=master["slot_step_min"])
        duration = timedelta(minutes=service["duration_min"])
        result = []
        candidate = work_start
        while candidate + duration <= work_end:
            if self._slot_available(self.conn, service, master, candidate, now):
                result.append(candidate.astimezone(UTC))
            candidate += step
        return result

    def available_dates(self, service_id: int, days: int = 21, now: datetime | None = None) -> list[date]:
        now = now or utc_now()
        first_day = now.astimezone(LOCAL_TZ).date()
        return [
            day
            for offset in range(days)
            if (day := first_day + timedelta(days=offset))
            and self.available_slots(service_id, day, now)
        ]

    def next_slots(
        self,
        service_id: int,
        limit: int = 7,
        days: int = 14,
        now: datetime | None = None,
    ) -> list[datetime]:
        now = now or utc_now()
        first_day = now.astimezone(LOCAL_TZ).date()
        result = []
        for offset in range(days):
            result.extend(self.available_slots(service_id, first_day + timedelta(days=offset), now))
            if len(result) >= limit:
                return result[:limit]
        return result

    def create_booking(
        self,
        client_id: int,
        service_id: int,
        start_at: datetime,
        source: str = "link",
        reinvited_from_id: int | None = None,
        now: datetime | None = None,
    ) -> int:
        if source not in {"link", "manual", "reinvite"}:
            raise ValueError("Неизвестный источник записи")
        with self.transaction() as conn:
            client = conn.execute(
                "SELECT * FROM clients WHERE id = ? AND master_id = ?",
                (client_id, self.master_id),
            ).fetchone()
            service = conn.execute(
                "SELECT * FROM services WHERE id = ? AND master_id = ? AND is_active = 1",
                (service_id, self.master_id),
            ).fetchone()
            if not client or not service:
                raise ValueError("Клиент или услуга не найдены")
            if not self._slot_available(
                conn, service, self.get_master(), start_at, now or utc_now()
            ):
                raise SlotUnavailable("Это время уже недоступно")
            start_utc = to_utc(start_at)
            end_utc = start_utc + timedelta(minutes=service["duration_min"])
            cursor = conn.execute(
                """
                INSERT INTO bookings(
                    master_id, client_id, service_id, start_at, end_at, status,
                    source, reinvited_from_id, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    self.master_id,
                    client_id,
                    service_id,
                    db_time(start_utc),
                    db_time(end_utc),
                    source,
                    reinvited_from_id,
                    db_time(utc_now()),
                ),
            )
            return cursor.lastrowid

    def cancel_booking(self, booking_id: int) -> sqlite3.Row:
        with self.transaction() as conn:
            booking = self.get_booking(booking_id)
            if not booking or booking["status"] != "active":
                raise ValueError("Активная запись не найдена")
            conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
            return booking

    def reschedule_booking(
        self,
        booking_id: int,
        start_at: datetime,
        now: datetime | None = None,
    ) -> int:
        with self.transaction() as conn:
            old = self.get_booking(booking_id)
            if not old or old["status"] != "active":
                raise ValueError("Активная запись не найдена")
            service = self.get_service(old["service_id"])
            if not service or not service["is_active"]:
                raise ValueError("Услуга больше недоступна")
            if not self._slot_available(
                conn,
                service,
                self.get_master(),
                start_at,
                now or utc_now(),
                exclude_booking_id=booking_id,
            ):
                raise SlotUnavailable("Это время уже недоступно")
            start_utc = to_utc(start_at)
            end_utc = start_utc + timedelta(minutes=service["duration_min"])
            cursor = conn.execute(
                """
                INSERT INTO bookings(
                    master_id, client_id, service_id, start_at, end_at, status,
                    source, reinvited_from_id, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    self.master_id,
                    old["client_id"],
                    old["service_id"],
                    db_time(start_utc),
                    db_time(end_utc),
                    old["source"],
                    old["reinvited_from_id"],
                    db_time(utc_now()),
                ),
            )
            new_id = cursor.lastrowid
            # Обе операции находятся в одной транзакции: при сбое старая запись не исчезнет.
            conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
            return new_id

    def due_reminders(self, kind: str, now: datetime) -> list[sqlite3.Row]:
        if kind not in {"reminder24_sent", "reminder1_sent"}:
            raise ValueError("Неизвестный тип напоминания")
        now = to_utc(now)
        if kind == "reminder24_sent":
            lower, upper = now + timedelta(hours=1), now + timedelta(hours=24)
        else:
            lower, upper = now, now + timedelta(hours=1)
        return self.conn.execute(
            f"""
            SELECT b.*, s.name AS service_name, s.price, s.duration_min,
                   c.tg_id, c.name AS client_name, c.phone, c.reinvite_opt_out
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            JOIN clients c ON c.id = b.client_id
            WHERE b.master_id = ? AND b.status = 'active' AND b.{kind} = 0
              AND c.tg_id IS NOT NULL AND b.start_at > ? AND b.start_at <= ?
            ORDER BY b.start_at
            """,
            (self.master_id, db_time(lower), db_time(upper)),
        ).fetchall()

    def mark_reminder_sent(self, booking_id: int, kind: str) -> None:
        if kind not in {"reminder24_sent", "reminder1_sent"}:
            raise ValueError("Неизвестный тип напоминания")
        with self.transaction() as conn:
            conn.execute(f"UPDATE bookings SET {kind} = 1 WHERE id = ?", (booking_id,))

    def complete_visits(self, now: datetime) -> int:
        with self.transaction() as conn:
            cursor = conn.execute(
                "UPDATE bookings SET status = 'done' WHERE master_id = ? AND status = 'active' AND end_at <= ?",
                (self.master_id, db_time(now)),
            )
            return cursor.rowcount

    def reinvites_due(self, now: datetime) -> list[sqlite3.Row]:
        now = to_utc(now)
        rows = self.conn.execute(
            """
            SELECT b.*, s.name AS service_name, s.price, s.duration_min, s.is_active,
                   c.tg_id, c.name AS client_name, c.phone, c.reinvite_opt_out,
                   m.reinvite_days, m.demo_mode
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            JOIN clients c ON c.id = b.client_id
            JOIN masters m ON m.tg_id = b.master_id
            WHERE b.master_id = ? AND b.status = 'done' AND b.reinvite_sent = 0
              AND c.reinvite_opt_out = 0 AND c.tg_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM bookings active
                  WHERE active.client_id = b.client_id AND active.status = 'active'
              )
            ORDER BY b.end_at
            """,
            (self.master_id,),
        ).fetchall()
        return [
            row
            for row in rows
            if from_db_time(row["end_at"]) + (
                timedelta(seconds=60)
                if row["demo_mode"]
                else timedelta(days=row["reinvite_days"])
            ) <= now
        ]

    def set_reinvite_opt_out(self, client_id: int, value: bool = True) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE clients SET reinvite_opt_out = ? WHERE id = ? AND master_id = ?",
                (int(value), client_id, self.master_id),
            )

    def set_reinvite_opt_out_by_tg(self, tg_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE clients SET reinvite_opt_out = 1 WHERE master_id = ? AND tg_id = ?",
                (self.master_id, tg_id),
            )

    def set_service_active(self, service_id: int, active: bool) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE services SET is_active = ? WHERE id = ? AND master_id = ?",
                (int(active), service_id, self.master_id),
            )

    def delete_service(self, service_id: int) -> None:
        # Мягкое удаление сохраняет название и цену в истории прошлых визитов.
        self.set_service_active(service_id, False)

    def upcoming_bookings(self, now: datetime, days: int = 2) -> list[sqlite3.Row]:
        first_day = now.astimezone(LOCAL_TZ).date()
        start = datetime.combine(first_day, time.min, LOCAL_TZ)
        end = start + timedelta(days=days)
        return self.conn.execute(
            """
            SELECT b.*, s.name AS service_name, s.price, s.duration_min,
                   c.tg_id, c.name AS client_name, c.phone, c.reinvite_opt_out
            FROM bookings b
            JOIN services s ON s.id = b.service_id
            JOIN clients c ON c.id = b.client_id
            WHERE b.master_id = ? AND b.status = 'active'
              AND b.start_at >= ? AND b.start_at < ?
            ORDER BY b.start_at
            """,
            (self.master_id, db_time(start), db_time(end)),
        ).fetchall()

    def statistics(self, now: datetime | None = None) -> dict[str, dict[str, int]]:
        now = now or utc_now()

        def collect(since: datetime | None) -> dict[str, int]:
            condition = "AND b.created_at >= ?" if since else ""
            params = [self.master_id]
            if since:
                params.append(db_time(since))
            rows = self.conn.execute(
                f"""
                SELECT b.status, b.source, b.reminder24_sent, b.reminder1_sent, s.price
                FROM bookings b JOIN services s ON s.id = b.service_id
                WHERE b.master_id = ? {condition}
                """,
                params,
            ).fetchall()
            return {
                "link": sum(row["status"] != "cancelled" and row["source"] == "link" for row in rows),
                "manual": sum(row["status"] != "cancelled" and row["source"] == "manual" for row in rows),
                "reinvite": sum(row["status"] != "cancelled" and row["source"] == "reinvite" for row in rows),
                "cancelled": sum(row["status"] == "cancelled" for row in rows),
                "reminders": sum(row["reminder24_sent"] + row["reminder1_sent"] for row in rows),
                "revenue": sum(row["price"] for row in rows if row["status"] == "done"),
            }

        return {"all": collect(None), "last30": collect(now - timedelta(days=30))}
