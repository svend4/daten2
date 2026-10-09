"""Сервис заведения: клиника/ресторан, торгующая ВРЕМЕНЕМ.

Отличие от магазина цветов принципиальное и в этом весь смысл примера:
непроданный букет можно продать завтра, непроданный вторник — нельзя.
Время — невозвратный ресурс, поэтому здесь обязательна пара
`reserve` → `commit`: удержание обратимо и само истекает, бронь — нет.

Зависимостей нет: http.server + sqlite3 из стандартной библиотеки.

Запуск:  python3 -m act.services.venue.server --port 8210 --db /tmp/venue.db
"""

from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOLD_TTL_SECONDS = 120
SERVICE_TITLE = "Клиника «Норд» — приём специалиста"

SCHEMA = """
CREATE TABLE IF NOT EXISTS slots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  day         TEXT    NOT NULL,
  time        TEXT    NOT NULL,
  specialist  TEXT    NOT NULL,
  price       REAL    NOT NULL CHECK (price >= 0),
  currency    TEXT    NOT NULL DEFAULT 'EUR',
  state       TEXT    NOT NULL DEFAULT 'free' CHECK (state IN ('free','held','booked')),
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
  created_at      TEXT NOT NULL
);
"""

SEED = [
    ("2026-10-12", "09:00", "Терапевт", 45.00),
    ("2026-10-12", "10:30", "Терапевт", 45.00),
    ("2026-10-12", "15:00", "Кардиолог", 90.00),
    ("2026-10-13", "11:00", "Терапевт", 45.00),
    ("2026-10-13", "18:00", "Кардиолог", 90.00),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT count(*) FROM slots").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO slots (day, time, specialist, price) VALUES (?,?,?,?)", SEED
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
            manifest = Path(__file__).resolve().parents[3] / "manifests" / "venue.act.json"
            if manifest.exists():
                return self._send(200, json.loads(manifest.read_text(encoding="utf-8")))
            return self._send(404, {"error": "manifest not found"})

        if url.path == "/api/slots":
            q = parse_qs(url.query)
            sql = "SELECT id, day, time, specialist, price, currency, state FROM slots WHERE state = 'free'"
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
                "       b.status, b.created_at, s.day, s.time, s.specialist "
                "FROM bookings b JOIN slots s ON s.id = b.slot_id "
                "WHERE b.booking_number = ?", (token,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "бронь не найдена"})
            return self._send(200, dict(row))

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
                "SELECT booking_number, total, currency FROM bookings WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if seen is not None:
                # Повтор возвращает тот же результат, а не создаёт вторую бронь.
                return self._send(200, {**dict(seen), "idempotent_replay": True})

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
                "SELECT id, price, currency, state FROM slots WHERE id = ?", (hold["slot_id"],)
            ).fetchone()
            if slot["state"] == "booked":
                return self._send(409, {"error": "слот уже забронирован"})

            token = secrets.token_hex(16)
            try:
                self.conn.execute("BEGIN")
                self.conn.execute(
                    "INSERT INTO bookings (booking_number, slot_id, customer_name, note,"
                    " total, currency, idempotency_key, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (token, slot["id"], name, body.get("note", ""),
                     slot["price"], slot["currency"], key, now_iso()),
                )
                self.conn.execute("UPDATE slots SET state = 'booked' WHERE id = ?", (slot["id"],))
                self.conn.execute("UPDATE holds SET released = 1 WHERE id = ?", (hold_id,))
                self.conn.commit()
            except sqlite3.Error as e:
                self.conn.rollback()
                return self._send(500, {"error": f"сбой транзакции: {e}"})

            return self._send(201, {"booking_number": token, "total": slot["price"],
                                    "currency": slot["currency"], "status": "confirmed"})

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
    print(f"venue на http://127.0.0.1:{args.port}  (база {args.db})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
