"""Сервис заведения: клиника/ресторан, торгующая ВРЕМЕНЕМ.

Отличие от магазина цветов принципиальное и в этом весь смысл примера:
непроданный букет можно продать завтра, непроданный вторник — нельзя.
Время — невозвратный ресурс, поэтому здесь обязательна пара
`reserve` → `commit`: удержание обратимо и само истекает, бронь — нет.

Этап 21: заведение само отдаёт блок `when` (§6.1). До этого клиент собирал его
из слота сам, и расхождение «клиент думает 09:00, сервис продал 10:30» ловилось
только тестом. Теперь время обязательства объявляет продавец, и клиент может
лишь повторить его. Блок несёт местное время заведения с часовым поясом.

Зависимостей нет: http.server + sqlite3 + zoneinfo из стандартной библиотеки.

Запуск:  python3 -m act.services.venue.server --port 8210 --db /tmp/venue.db
"""

from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta, timezone, tzinfo
from datetime import time as dtime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOLD_TTL_SECONDS = 120

#: Название заведения. Оно же — место в блоке `when`: на карте обязательств
#: место читает человек, и «Клиника «Норд»» ему говорит больше, чем `venue-…`.
VENUE_NAME = "Клиника «Норд»"
SERVICE_TITLE = f"{VENUE_NAME} — приём специалиста"

#: Длительность приёма по специальности. Это ЗНАНИЕ ЗАВЕДЕНИЯ: сколько длится
#: приём у кардиолога решает клиника, а не сервер и не клиент. Нельзя выводить
#: её из `cost.time_s` глагола: это время HTTP-вызова, а не обязательства (§6.1).
DURATION_MIN = {"Терапевт": 30, "Кардиолог": 60}
#: Для специальности, которой нет в таблице выше. Совпадает с умолчанием колонки.
DEFAULT_DURATION_MIN = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS slots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  day         TEXT    NOT NULL,
  time        TEXT    NOT NULL,
  specialist  TEXT    NOT NULL,
  price       REAL    NOT NULL CHECK (price >= 0),
  currency    TEXT    NOT NULL DEFAULT 'EUR',
  state       TEXT    NOT NULL DEFAULT 'free' CHECK (state IN ('free','held','booked')),
  duration_min INTEGER NOT NULL DEFAULT 30,
  UNIQUE (day, time, specialist)
);
CREATE TABLE IF NOT EXISTS holds (
  id         TEXT PRIMARY KEY,
  slot_id    INTEGER NOT NULL REFERENCES slots(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  released   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bookings (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_number  TEXT NOT NULL UNIQUE,
  slot_id         INTEGER NOT NULL REFERENCES slots(id),
  customer_name   TEXT NOT NULL,
  note            TEXT NOT NULL DEFAULT '',
  total           REAL NOT NULL,
  currency        TEXT NOT NULL DEFAULT 'EUR',
  status          TEXT NOT NULL DEFAULT 'confirmed',
  idempotency_key TEXT UNIQUE,
  created_at      TEXT NOT NULL,
  when_json       TEXT
);
"""

#: Колонки, которых не было в первой версии схемы: (таблица, колонка, объявление).
#: CREATE TABLE IF NOT EXISTS старую таблицу не трогает, поэтому недостающее
#: добавляется отдельно и аддитивно. SQLite не умеет ADD COLUMN IF NOT EXISTS,
#: поэтому наличие колонки проверяется через PRAGMA.
ADDED_COLUMNS = (
    ("slots", "duration_min", "INTEGER NOT NULL DEFAULT 30"),
    # NULL — только у броней, созданных до этапа 21; для них when восстанавливается из слота.
    ("bookings", "when_json", "TEXT"),
)

SEED = [
    ("2026-10-12", "09:00", "Терапевт", 45.00),
    ("2026-10-12", "10:30", "Терапевт", 45.00),
    ("2026-10-12", "15:00", "Кардиолог", 90.00),
    ("2026-10-13", "11:00", "Терапевт", 45.00),
    ("2026-10-13", "18:00", "Кардиолог", 90.00),
]


# ────────────────────────────────────────────────────────────────────────────
# Часовой пояс заведения: Europe/Berlin
# ────────────────────────────────────────────────────────────────────────────


def _last_sunday(year: int, month: int) -> date:
    """Последнее воскресенье месяца — от него в ЕС отсчитывается летнее время."""
    last_day = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return last_day - timedelta(days=(last_day.weekday() - 6) % 7)


class EuropeBerlinRule(tzinfo):
    """Europe/Berlin по правилу ЕС — резерв на случай, когда базы tzdata нет.

    Почему резерв, а не `pip install tzdata`: act/ не имеет внешних зависимостей
    (§11). Почему это не тихая подмена: при отсутствии zoneinfo сервис печатает
    предупреждение и отмечает способ в TZ_BACKEND, а test_venue_when сверяет
    правило с zoneinfo поточасово за 2000–2040 годы.

    Правило: летнее время с последнего воскресенья марта до последнего воскресенья
    октября. Переход происходит в 01:00 UTC, то есть в 02:00 CET → 03:00 CEST весной
    и в 03:00 CEST → 02:00 CET осенью. Для местных часов это:
      • весной несуществующий час 02:00–03:00 трактуется как стандартное время
        (+01:00) — так же, как zoneinfo при fold=0;
      • осенью неоднозначный час 02:00–03:00 при fold=0 — первое вхождение
        (CEST, +02:00), при fold=1 — второе (CET, +01:00).
    """

    _STD = timedelta(hours=1)
    _DST = timedelta(hours=2)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return self._DST if self._is_dst(dt) else self._STD

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=1) if self._is_dst(dt) else timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "CEST" if self._is_dst(dt) else "CET"

    @staticmethod
    def _is_dst(dt: datetime | None) -> bool:
        if dt is None:
            return False
        wall = dt.replace(tzinfo=None)
        start = datetime.combine(_last_sunday(wall.year, 3), dtime(3, 0))
        end = datetime.combine(_last_sunday(wall.year, 10), dtime(3, 0))
        if not start <= wall < end:
            return False
        if wall >= end - timedelta(hours=1):  # неоднозначный час осени
            return not dt.fold
        return True


def _load_berlin() -> tuple[tzinfo, str]:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Berlin"), "zoneinfo"
    except (ImportError, LookupError, ValueError) as e:  # ZoneInfoNotFoundError — подкласс LookupError
        print(f"venue: база часовых поясов недоступна ({e}); "
              f"использую резервное правило ЕС для Europe/Berlin", file=sys.stderr, flush=True)
        return EuropeBerlinRule(), "eu-rule-fallback"


BERLIN, TZ_BACKEND = _load_berlin()


def venue_when(day: str, time_of_day: str, duration_min: int) -> dict:
    """Блок `when` (§6.1) для слота: местное время заведения с его смещением.

    Смещение берётся из правил Europe/Berlin на эту дату, а не из константы:
    12 октября — +02:00 (летнее), 26 октября — +01:00 (зимнее). Если время
    объявлено без смещения, потребитель не знает, какую шкалу читать, поэтому
    смещение пишется всегда.
    """
    wall = datetime.strptime(f"{day} {time_of_day}", "%Y-%m-%d %H:%M")
    moment = wall.replace(tzinfo=BERLIN)
    return {
        "starts_at": moment.isoformat(timespec="minutes"),
        "duration_min": int(duration_min),
        "place": VENUE_NAME,
    }


def _when_of(when_json: str | None, day: str, time_of_day: str, duration_min: int) -> dict:
    """Вернуть when, который заведение ОБЪЯВИЛО при брони, либо восстановить его.

    Объявленный блок хранится в брони как есть и возвращается байт в байт: запись —
    доказательство, и правка слота или смена правил часового пояса задним числом не
    должны переписывать то, что уже было сказано. Восстановление из слота нужно
    только для броней, созданных до этапа 21.
    """
    if when_json:
        return json.loads(when_json)
    return venue_when(day, time_of_day, duration_min)


def duration_for(specialist: str) -> int:
    return DURATION_MIN.get(specialist, DEFAULT_DURATION_MIN)


# ────────────────────────────────────────────────────────────────────────────
# База
# ────────────────────────────────────────────────────────────────────────────


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Аддитивная миграция: добавить колонки, которых нет, и ничего не переписывать.

    Длительность старым слотам проставляется ОДИН раз — в момент добавления колонки.
    Если бы это делалось при каждом запуске, ручная правка заведения откатывалась бы
    при перезапуске сервиса.
    """
    for table, column, decl in ADDED_COLUMNS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column in present:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        if (table, column) == ("slots", "duration_min"):
            for specialist, minutes in DURATION_MIN.items():
                conn.execute("UPDATE slots SET duration_min = ? WHERE specialist = ?",
                             (minutes, specialist))
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate(conn)
    if conn.execute("SELECT count(*) FROM slots").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO slots (day, time, specialist, price, duration_min) VALUES (?,?,?,?,?)",
            [(d, t, s, p, duration_for(s)) for d, t, s, p in SEED],
        )
    conn.commit()


def expire_holds(conn: sqlite3.Connection) -> int:
    """Удержания истекают сами — это и делает их обратимыми без участия сторон."""
    stale = conn.execute(
        "SELECT id, slot_id FROM holds WHERE released = 0 AND expires_at <= ?", (now_iso(),)
    ).fetchall()
    for row in stale:
        conn.execute("UPDATE holds SET released = 1 WHERE id = ?", (row["id"],))
        conn.execute("UPDATE slots SET state = 'free' WHERE id = ? AND state = 'held'", (row["slot_id"],))
    if stale:
        conn.commit()
    return len(stale)


class Handler(BaseHTTPRequestHandler):
    conn: sqlite3.Connection = None  # подставляется в main()

    # ---------- инфраструктура ----------

    def log_message(self, *args) -> None:  # тише в тестах
        pass

    def _send(self, status: int, body: dict | list) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------- маршруты ----------

    def do_GET(self) -> None:
        url = urlparse(self.path)
        expire_holds(self.conn)

        if url.path == "/api/health":
            return self._send(200, {"ok": True, "service": "venue", "title": SERVICE_TITLE})

        if url.path == "/.well-known/npp-act.json":
            # act/services/venue/server.py → parents[2] это каталог act/.
            # parents[3] (корень репозитория) был ошибкой: манифест не находился,
            # и эндпоинт отдавал 404, хотя файл существует.
            manifest = Path(__file__).resolve().parents[2] / "manifests" / "venue.act.json"
            if manifest.exists():
                return self._send(200, json.loads(manifest.read_text(encoding="utf-8")))
            return self._send(404, {"error": "manifest not found"})

        if url.path == "/api/slots":
            q = parse_qs(url.query)
            sql = ("SELECT id, day, time, specialist, price, currency, state, duration_min "
                   "FROM slots WHERE state = 'free'")
            params: list = []
            if "day" in q:
                sql += " AND day = ?"
                params.append(q["day"][0])
            if "specialist" in q:
                sql += " AND specialist = ?"
                params.append(q["specialist"][0])
            sql += " ORDER BY day, time"
            rows = [dict(r) for r in self.conn.execute(sql, params)]
            return self._send(200, rows)

        if url.path.startswith("/api/bookings/"):
            token = url.path.rsplit("/", 1)[-1]
            row = self.conn.execute(
                "SELECT b.booking_number, b.customer_name, b.note, b.total, b.currency,"
                "       b.status, b.created_at, b.when_json, s.day, s.time, s.specialist,"
                "       s.duration_min "
                "FROM bookings b JOIN slots s ON s.id = b.slot_id "
                "WHERE b.booking_number = ?", (token,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "бронь не найдена"})
            out = dict(row)
            out["when"] = _when_of(out.pop("when_json"), out["day"], out["time"],
                                   out.pop("duration_min"))
            return self._send(200, out)

        return self._send(404, {"error": "неизвестный маршрут"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        expire_holds(self.conn)
        body = self._body()

        # --- удержание слота: обратимо, истекает само ---
        if url.path == "/api/holds":
            slot_id = body.get("slot_id")
            if slot_id is None:
                return self._send(400, {"error": "slot_id обязателен"})
            row = self.conn.execute("SELECT id, state FROM slots WHERE id = ?", (slot_id,)).fetchone()
            if row is None:
                return self._send(404, {"error": "слот не найден"})
            if row["state"] != "free":
                return self._send(409, {"error": f"слот уже {row['state']}"})

            hold_id = "hold_" + uuid.uuid4().hex[:12]
            expires = (datetime.now(timezone.utc) + timedelta(seconds=HOLD_TTL_SECONDS))
            expires_iso = expires.isoformat(timespec="seconds").replace("+00:00", "Z")
            self.conn.execute(
                "INSERT INTO holds (id, slot_id, created_at, expires_at) VALUES (?,?,?,?)",
                (hold_id, slot_id, now_iso(), expires_iso),
            )
            self.conn.execute("UPDATE slots SET state = 'held' WHERE id = ?", (slot_id,))
            self.conn.commit()
            return self._send(201, {"hold_id": hold_id, "slot_id": slot_id,
                                    "expires_at": expires_iso, "ttl_s": HOLD_TTL_SECONDS})

        # --- бронь: необратима, требует согласия обеих сторон и ключа идемпотентности ---
        if url.path == "/api/bookings":
            key = self.headers.get("Idempotency-Key")
            if not key:
                return self._send(400, {"error": "требуется заголовок Idempotency-Key"})

            seen = self.conn.execute(
                "SELECT b.booking_number, b.total, b.currency, b.when_json,"
                "       s.day, s.time, s.duration_min "
                "FROM bookings b JOIN slots s ON s.id = b.slot_id "
                "WHERE b.idempotency_key = ?", (key,)
            ).fetchone()
            if seen is not None:
                # Повтор возвращает тот же результат, а не создаёт вторую бронь —
                # и тот же when, объявленный при первой брони.
                when = _when_of(seen["when_json"], seen["day"], seen["time"], seen["duration_min"])
                return self._send(200, {"booking_number": seen["booking_number"],
                                        "total": seen["total"], "currency": seen["currency"],
                                        "idempotent_replay": True, "when": when})

            hold_id = body.get("hold_id")
            name = (body.get("name") or "").strip()
            if not hold_id or not name:
                return self._send(400, {"error": "hold_id и name обязательны"})

            hold = self.conn.execute(
                "SELECT id, slot_id, expires_at, released FROM holds WHERE id = ?", (hold_id,)
            ).fetchone()
            if hold is None:
                return self._send(404, {"error": "удержание не найдено"})
            if hold["released"]:
                return self._send(409, {"error": "удержание уже отпущено или истекло"})
            if hold["expires_at"] <= now_iso():
                return self._send(409, {"error": "удержание истекло"})

            slot = self.conn.execute(
                "SELECT id, day, time, duration_min, price, currency, state "
                "FROM slots WHERE id = ?", (hold["slot_id"],)
            ).fetchone()
            if slot["state"] == "booked":
                return self._send(409, {"error": "слот уже забронирован"})

            try:
                when = venue_when(slot["day"], slot["time"], slot["duration_min"])
            except ValueError as e:
                return self._send(500, {"error": f"слот с непонятным временем: {e}"})

            token = secrets.token_hex(16)
            try:
                self.conn.execute("BEGIN")
                self.conn.execute(
                    "INSERT INTO bookings (booking_number, slot_id, customer_name, note,"
                    " total, currency, idempotency_key, created_at, when_json)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (token, slot["id"], name, body.get("note", ""),
                     slot["price"], slot["currency"], key, now_iso(),
                     json.dumps(when, ensure_ascii=False)),
                )
                self.conn.execute("UPDATE slots SET state = 'booked' WHERE id = ?", (slot["id"],))
                self.conn.execute("UPDATE holds SET released = 1 WHERE id = ?", (hold_id,))
                self.conn.commit()
            except sqlite3.Error as e:
                self.conn.rollback()
                return self._send(500, {"error": f"сбой транзакции: {e}"})

            return self._send(201, {"booking_number": token, "total": slot["price"],
                                    "currency": slot["currency"], "status": "confirmed",
                                    "when": when})

        return self._send(404, {"error": "неизвестный маршрут"})

    def do_DELETE(self) -> None:
        url = urlparse(self.path)
        if url.path.startswith("/api/holds/"):
            hold_id = url.path.rsplit("/", 1)[-1]
            hold = self.conn.execute(
                "SELECT id, slot_id, released FROM holds WHERE id = ?", (hold_id,)
            ).fetchone()
            if hold is None:
                return self._send(404, {"error": "удержание не найдено"})
            self.conn.execute("UPDATE holds SET released = 1 WHERE id = ?", (hold_id,))
            self.conn.execute(
                "UPDATE slots SET state = 'free' WHERE id = ? AND state = 'held'", (hold["slot_id"],)
            )
            self.conn.commit()
            return self._send(200, {"released": True, "hold_id": hold_id})
        return self._send(404, {"error": "неизвестный маршрут"})


def main() -> None:
    ap = argparse.ArgumentParser(description="NPP-Act: сервис заведения (продаёт время)")
    ap.add_argument("--port", type=int, default=8210)
    ap.add_argument("--db", default="/tmp/npp_venue.db")
    ap.add_argument("--reset", action="store_true", help="пересоздать базу")
    args = ap.parse_args()

    if args.reset and Path(args.db).exists():
        Path(args.db).unlink()

    conn = connect(args.db)
    init_db(conn)
    Handler.conn = conn

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"venue на http://127.0.0.1:{args.port}  (база {args.db}, часовой пояс: {TZ_BACKEND})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
