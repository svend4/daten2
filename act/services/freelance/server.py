"""Цех — Actionable-сервис сферы услуг (фриланс).

ПОЧЕМУ ЭТОТ СЕРВИС ВЫГЛЯДИТ ИНАЧЕ, ЧЕМ МАГАЗИН И КЛИНИКА
---------------------------------------------------------
Магазин продаёт товар: непроданный букет продашь завтра, заказ возвратен.
Клиника продаёт время: непроданный вторник не продашь никогда, бронь невозвратна.
Цех продаёт третье — компетенцию и обязательство во времени, и у него четыре
свойства, которых нет ни у товара, ни у слота:

1. ЦЕНА НЕ ОБЪЯВЛЕНА ЗАРАНЕЕ. У букета есть прайс, у приёма — тариф, у работы
   есть только оценка, которую даёт исполнитель. Поэтому между заявкой и
   обязательством стоит отдельная пара шагов: запрос оценки (обратимый) и
   оценка (обязательство исполнителя, тоже обратимое, пока не подписан контракт).

2. ОБЯЗАТЕЛЬСТВО ДВУСТОРОННЕЕ. В товарном ERP заказ создаёт одна сторона.
   Здесь контракт не существует, пока обе стороны не связали себя: заказчик —
   деньгами в эскроу, исполнитель — ёмкостью своей недели.

3. ЁМКОСТЬ, А НЕ СКЛАД. Склад уменьшается и может быть пополнен. Ёмкость
   исполнителя — часы в неделю — не пополняется ничем: нельзя «подвезти» ещё
   десять часов во вторник. И она НЕВОЗВРАТНА: при расторжении контракта часы
   начавшихся недель не возвращаются в ёмкость, часы будущих — возвращаются.
   Это главное отличие учёта услуг от учёта товара, и оно здесь смоделировано
   прямо в таблице `capacity_holds` состояниями 'released' и 'burned'.

4. ПРИЁМКА С ДОРАБОТКОЙ. Товар либо отгружен, либо нет. Работу можно вернуть
   на доработку, и это НЕ провал контракта — обычная фаза жизненного цикла.
   Поэтому возврат на доработку оформлен отдельным глаголом с обратимым
   эффектом, а не ошибкой исполнения.

Плюс цеховая модель репутации: рекомендация относится к КОНКРЕТНОЙ выполненной
работе, а не к профилю. Профиль не несёт «рейтинга» — он несёт список
выполненных обязательств, каждое из которых проверяемо.

ДЕНЬГИ СЧИТАЮТСЯ В ЦЕЛЫХ ЦЕНТАХ. Аудит семи уровней daten2 показал, что только
L6 держал деньги в Decimal, остальные — во float или в строке; расхождение в
цент в эскроу означает либо неоплаченную работу, либо недоплаченного человека.
Здесь любое сравнение сумм — сравнение целых.

ОДИН ХЭНДЛ SQLITE НА ВСЕХ, НО ПОД ЗАМКОМ. L4 из daten2 ломался на шести
одновременных заказах (1 успех, 5 отказов) именно из-за общего хэндла.
Хэндл здесь тоже общий, но каждый запрос сериализуется замком, а подписание
контракта идёт одной транзакцией — поэтому конкуренция даёт отказ «сверх
ёмкости», а не отказ «база занята».

Зависимостей нет: http.server + sqlite3 из стандартной библиотеки.

Запуск:  python3 -m act.services.freelance.server --port 8220 --db /tmp/guild.db --reset
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SERVICE_TITLE = "Цех — биржа компетенции и обязательства во времени"

#: Запрос оценки — удержание внимания исполнителя. Истекает сам, как слот в клинике.
QUOTE_REQUEST_TTL_S = 300
#: Срок жизни самой оценки: обязательство исполнителя по цене не бессрочно.
QUOTE_VALID_S = 1800

WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")

#: Статусы контракта. 'in_work' после возврата на доработку — это рабочая фаза,
#: а не ошибка: контракт жив, обязательство в силе, срок идёт.
ACTIVE_CONTRACT = ("signed", "delivered", "in_work")
DONE_CONTRACT = ("accepted", "paid")

SCHEMA = """
CREATE TABLE IF NOT EXISTS contractors (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT    NOT NULL,
  skills         TEXT    NOT NULL DEFAULT '',
  hours_per_week INTEGER NOT NULL CHECK (hours_per_week > 0),
  rate_cents     INTEGER NOT NULL CHECK (rate_cents >= 0),
  currency       TEXT    NOT NULL DEFAULT 'EUR'
);
CREATE TABLE IF NOT EXISTS briefs (
  brief_token     TEXT PRIMARY KEY,
  client          TEXT NOT NULL,
  title           TEXT NOT NULL,
  spec            TEXT NOT NULL DEFAULT '',
  budget_cap_cents INTEGER NOT NULL CHECK (budget_cap_cents > 0),
  currency        TEXT NOT NULL DEFAULT 'EUR',
  status          TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open','contracted','cancelled')),
  created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quote_requests (
  id            TEXT PRIMARY KEY,
  brief_token   TEXT NOT NULL REFERENCES briefs(brief_token),
  contractor_id INTEGER NOT NULL REFERENCES contractors(id),
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,
  released      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quotes (
  quote_token   TEXT PRIMARY KEY,
  request_id    TEXT NOT NULL REFERENCES quote_requests(id),
  brief_token   TEXT NOT NULL REFERENCES briefs(brief_token),
  contractor_id INTEGER NOT NULL REFERENCES contractors(id),
  price_cents   INTEGER NOT NULL CHECK (price_cents > 0),
  currency      TEXT NOT NULL DEFAULT 'EUR',
  hours         INTEGER NOT NULL CHECK (hours > 0),
  week          TEXT NOT NULL,
  valid_until   TEXT NOT NULL,
  state         TEXT NOT NULL DEFAULT 'given'
                CHECK (state IN ('given','revoked','used')),
  created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS escrows (
  escrow_token TEXT PRIMARY KEY,
  brief_token  TEXT NOT NULL REFERENCES briefs(brief_token),
  amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
  currency     TEXT NOT NULL DEFAULT 'EUR',
  state        TEXT NOT NULL DEFAULT 'held'
               CHECK (state IN ('held','released','refunded')),
  created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contracts (
  contract_token TEXT PRIMARY KEY,
  brief_token    TEXT NOT NULL REFERENCES briefs(brief_token),
  quote_token    TEXT NOT NULL REFERENCES quotes(quote_token),
  escrow_token   TEXT NOT NULL REFERENCES escrows(escrow_token),
  contractor_id  INTEGER NOT NULL REFERENCES contractors(id),
  client         TEXT NOT NULL,
  price_cents    INTEGER NOT NULL,
  currency       TEXT NOT NULL DEFAULT 'EUR',
  hours          INTEGER NOT NULL,
  week           TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'signed'
                 CHECK (status IN ('signed','delivered','in_work','accepted','paid','cancelled')),
  revisions      INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL,
  accepted_at    TEXT,
  closed_at      TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_token TEXT NOT NULL REFERENCES contracts(contract_token),
  revision       INTEGER NOT NULL,
  artifact       TEXT NOT NULL,
  note           TEXT NOT NULL DEFAULT '',
  created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capacity_holds (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  contractor_id  INTEGER NOT NULL REFERENCES contractors(id),
  week           TEXT NOT NULL,
  hours          INTEGER NOT NULL CHECK (hours > 0),
  contract_token TEXT NOT NULL REFERENCES contracts(contract_token),
  state          TEXT NOT NULL DEFAULT 'held'
                 CHECK (state IN ('held','released','burned')),
  created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS endorsements (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_token TEXT NOT NULL REFERENCES contracts(contract_token),
  work_ref       TEXT NOT NULL,
  contractor_id  INTEGER NOT NULL REFERENCES contractors(id),
  client         TEXT NOT NULL,
  verdict        TEXT NOT NULL CHECK (verdict IN ('recommend','with_reservations')),
  comment        TEXT NOT NULL DEFAULT '',
  created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idem (
  key        TEXT PRIMARY KEY,
  verb       TEXT NOT NULL,
  response   TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

SEED = [
    ("Марина Соколова", "вёрстка, фронтенд, доступность", 20, 4500),
    ("Игорь Лапин", "бэкенд, sqlite, миграции данных", 10, 6000),
    ("Ольга Веер", "техническая документация, тексты", 30, 3000),
]

#: Один общий хэндл sqlite3 — но ни один запрос не идёт мимо этого замка.
LOCK = threading.Lock()


# ───────────────────────────── время и деньги ─────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def today() -> date:
    return datetime.now(timezone.utc).date()


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(week: str) -> date | None:
    """Понедельник недели вида '2026-W42', либо None, если форма неверна."""
    if not WEEK_RE.match(week):
        return None
    year, _, num = week.partition("-W")
    try:
        return date.fromisocalendar(int(year), int(num), 1)
    except ValueError:
        return None


def week_started(week: str) -> bool:
    """Неделя уже началась — значит её часы невозвратны.

    Граница намеренно нестрогая: в понедельник неделя уже идёт, и час,
    обещанный на эту неделю, уже нельзя вернуть в ёмкость «как было».
    """
    start = week_start(week)
    return start is not None and start <= today()


def money(cents: int) -> float:
    return round(cents / 100, 2)


def to_cents(value) -> int | None:
    """Приём денег от клиента: любое представление → целые центы."""
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def work_ref(contract_token: str) -> str:
    """Публичная ссылка на работу.

    §10.3 требует, чтобы идентификатор обязательства был непубличным токеном.
    Репутация же обязана быть публичной. Противоречие снимается производной:
    из токена контракта выводится work_ref, обратно — нет. Рекомендацию можно
    предъявить, не раскрывая доступ к контракту.
    """
    return "work_" + sha256(contract_token.encode("utf-8")).hexdigest()[:12]


# ───────────────────────────── база ─────────────────────────────

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT count(*) FROM contractors").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO contractors (name, skills, hours_per_week, rate_cents)"
            " VALUES (?,?,?,?)", SEED
        )
    conn.commit()


def expire_requests(conn: sqlite3.Connection) -> int:
    """Запросы оценки истекают сами — поэтому они обратимы без участия сторон."""
    stale = conn.execute(
        "SELECT id FROM quote_requests WHERE released = 0 AND expires_at <= ?", (now_iso(),)
    ).fetchall()
    for row in stale:
        conn.execute("UPDATE quote_requests SET released = 1 WHERE id = ?", (row["id"],))
    if stale:
        conn.commit()
    return len(stale)


def committed_hours(conn: sqlite3.Connection, contractor_id: int, week: str) -> tuple[int, int]:
    """Занятые часы недели: (под действующими обязательствами, сожжённые).

    Сожжённые часы — это часы расторгнутых контрактов на уже начавшуюся неделю.
    Они продолжают занимать ёмкость, потому что время не вернулось. Именно это
    отличает учёт услуг от учёта склада: отмена заказа возвращает товар на полку,
    отмена контракта не возвращает прошедшую неделю.
    """
    row = conn.execute(
        "SELECT"
        "  COALESCE(SUM(CASE WHEN state = 'held'   THEN hours ELSE 0 END), 0) AS held,"
        "  COALESCE(SUM(CASE WHEN state = 'burned' THEN hours ELSE 0 END), 0) AS burned"
        " FROM capacity_holds WHERE contractor_id = ? AND week = ?",
        (contractor_id, week),
    ).fetchone()
    return int(row["held"]), int(row["burned"])


def free_hours(conn: sqlite3.Connection, contractor_id: int, week: str, cap: int) -> int:
    held, burned = committed_hours(conn, contractor_id, week)
    return cap - held - burned


# ───────────────────────────── HTTP ─────────────────────────────

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
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    # ---------- идемпотентность ----------

    def _idem_begin(self, verb: str, key: str | None) -> tuple[bool, dict | None]:
        """Проверка ключа ДО исполнения.

        Возвращает (можно_исполнять, готовый_ответ). Повтор с тем же ключом
        возвращает ровно тот же ответ, а не второе обязательство; тот же ключ
        на другом глаголе — конфликт, потому что ключ идентифицирует намерение,
        а не строку в таблице.
        """
        if not key:
            self._send(400, {"error": "требуется заголовок Idempotency-Key"})
            return False, None
        row = self.conn.execute("SELECT verb, response FROM idem WHERE key = ?", (key,)).fetchone()
        if row is None:
            return True, None
        if row["verb"] != verb:
            self._send(409, {"error": f"ключ идемпотентности уже использован глаголом '{row['verb']}'"})
            return False, None
        self._send(200, {**json.loads(row["response"]), "idempotent_replay": True})
        return False, None

    def _idem_done(self, verb: str, key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO idem (key, verb, response, created_at) VALUES (?,?,?,?)",
            (key, verb, json.dumps(payload, ensure_ascii=False), now_iso()),
        )
        self.conn.commit()

    def _ok(self, status: int, verb: str, key: str, payload: dict) -> None:
        self._idem_done(verb, key, payload)
        self._send(status, payload)

    # ---------- чтение состояния ----------

    def _contract(self, token: str):
        return self.conn.execute(
            "SELECT * FROM contracts WHERE contract_token = ?", (token,)
        ).fetchone()

    def _contract_view(self, row) -> dict:
        deliveries = [
            {"revision": d["revision"], "artifact": d["artifact"],
             "note": d["note"], "created_at": d["created_at"]}
            for d in self.conn.execute(
                "SELECT revision, artifact, note, created_at FROM deliveries"
                " WHERE contract_token = ? ORDER BY revision",
                (row["contract_token"],),
            )
        ]
        escrow = self.conn.execute(
            "SELECT state, amount_cents FROM escrows WHERE escrow_token = ?", (row["escrow_token"],)
        ).fetchone()
        contractor = self.conn.execute(
            "SELECT name FROM contractors WHERE id = ?", (row["contractor_id"],)
        ).fetchone()
        return {
            "contract_token": row["contract_token"],
            "work_ref": work_ref(row["contract_token"]),
            "client": row["client"],
            "contractor_id": row["contractor_id"],
            "contractor": contractor["name"] if contractor else "",
            "price": money(row["price_cents"]),
            "price_cents": row["price_cents"],
            "currency": row["currency"],
            "hours": row["hours"],
            "week": row["week"],
            "week_started": week_started(row["week"]),
            "status": row["status"],
            "revisions": row["revisions"],
            "deliveries": deliveries,
            "escrow_state": escrow["state"] if escrow else "unknown",
            "escrow_amount": money(escrow["amount_cents"]) if escrow else 0.0,
            "created_at": row["created_at"],
            "accepted_at": row["accepted_at"],
        }

    # ---------- GET ----------

    def do_GET(self) -> None:
        with LOCK:
            try:
                self._get()
            except Exception as e:  # сервис не должен падать молча
                self._send(500, {"error": f"внутренний сбой: {e}"})

    def _get(self) -> None:
        url = urlparse(self.path)
        q = parse_qs(url.query)
        expire_requests(self.conn)

        if url.path == "/api/health":
            return self._send(200, {"ok": True, "service": "freelance", "title": SERVICE_TITLE,
                                    "sells": "компетенция и обязательство во времени"})

        if url.path == "/.well-known/npp-act.json":
            # act/services/freelance/server.py → parents[2] == act/
            manifest = Path(__file__).resolve().parents[2] / "manifests" / "freelance.act.json"
            if manifest.exists():
                return self._send(200, json.loads(manifest.read_text(encoding="utf-8")))
            return self._send(404, {"error": "манифест не найден"})

        if url.path == "/api/contractors":
            sql = "SELECT id, name, skills, hours_per_week, rate_cents, currency FROM contractors"
            params: list = []
            if "skill" in q:
                sql += " WHERE skills LIKE ?"
                params.append(f"%{q['skill'][0]}%")
            sql += " ORDER BY id"
            week = iso_week(today())
            rows = []
            for r in self.conn.execute(sql, params):
                held, burned = committed_hours(self.conn, r["id"], week)
                rows.append({
                    "id": r["id"], "name": r["name"], "skills": r["skills"],
                    "hours_per_week": r["hours_per_week"],
                    "rate": money(r["rate_cents"]), "currency": r["currency"],
                    "week": week,
                    "committed_hours": held, "burned_hours": burned,
                    "free_hours": r["hours_per_week"] - held - burned,
                })
            return self._send(200, rows)

        if url.path == "/api/capacity":
            cid = q.get("contractor_id", [None])[0]
            row = self.conn.execute(
                "SELECT id, name, hours_per_week FROM contractors WHERE id = ?", (cid,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "исполнитель не найден"})
            horizon = int(q.get("weeks", ["4"])[0] or 4)
            start = today()
            weeks = []
            for i in range(max(1, min(horizon, 26))):
                wk = iso_week(start + timedelta(days=7 * i))
                held, burned = committed_hours(self.conn, row["id"], wk)
                weeks.append({
                    "week": wk,
                    "week_start": week_start(wk).isoformat(),
                    "started": week_started(wk),
                    "committed_hours": held,
                    "burned_hours": burned,
                    "free_hours": row["hours_per_week"] - held - burned,
                })
            return self._send(200, {
                "contractor_id": row["id"], "contractor": row["name"],
                "hours_per_week": row["hours_per_week"], "weeks": weeks,
                "note": "сожжённые часы — расторгнутые контракты начавшихся недель; "
                        "они не возвращаются в ёмкость",
            })

        if url.path == "/api/reputation":
            cid = q.get("contractor_id", [None])[0]
            row = self.conn.execute(
                "SELECT id, name FROM contractors WHERE id = ?", (cid,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "исполнитель не найден"})
            done = self.conn.execute(
                "SELECT contract_token, hours, revisions, week, price_cents FROM contracts"
                " WHERE contractor_id = ? AND status IN ('accepted','paid')", (row["id"],)
            ).fetchall()
            ends = [
                {"work_ref": e["work_ref"], "verdict": e["verdict"], "comment": e["comment"],
                 "created_at": e["created_at"]}
                for e in self.conn.execute(
                    "SELECT work_ref, verdict, comment, created_at FROM endorsements"
                    " WHERE contractor_id = ? ORDER BY id", (row["id"],)
                )
            ]
            return self._send(200, {
                "contractor_id": row["id"], "contractor": row["name"],
                "completed_contracts": len(done),
                "hours_delivered": sum(int(d["hours"]) for d in done),
                "revisions_requested": sum(int(d["revisions"]) for d in done),
                "works": [{"work_ref": work_ref(d["contract_token"]), "week": d["week"],
                           "hours": d["hours"], "revisions": d["revisions"]} for d in done],
                "endorsements": ends,
                "note": "репутация считается по принятым обязательствам, а не по профилю: "
                        "каждая рекомендация относится к конкретной работе (work_ref)",
            })

        if url.path.startswith("/api/contracts/"):
            rest = url.path[len("/api/contracts/"):]
            if "/" not in rest:
                row = self._contract(rest)
                if row is None:
                    return self._send(404, {"error": "контракт не найден"})
                return self._send(200, self._contract_view(row))

        if url.path.startswith("/api/briefs/"):
            token = url.path.rsplit("/", 1)[-1]
            row = self.conn.execute(
                "SELECT brief_token, client, title, spec, budget_cap_cents, currency, status,"
                " created_at FROM briefs WHERE brief_token = ?", (token,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "бриф не найден"})
            return self._send(200, {
                "brief_token": row["brief_token"], "client": row["client"],
                "title": row["title"], "spec": row["spec"],
                "budget_cap": money(row["budget_cap_cents"]),
                "currency": row["currency"], "status": row["status"],
                "created_at": row["created_at"],
            })

        return self._send(404, {"error": "неизвестный маршрут"})

    # ---------- POST ----------

    def do_POST(self) -> None:
        with LOCK:
            try:
                self._post()
            except Exception as e:
                try:
                    self.conn.rollback()
                except sqlite3.Error:
                    pass
                self._send(500, {"error": f"внутренний сбой: {e}"})

    def _post(self) -> None:
        url = urlparse(self.path)
        expire_requests(self.conn)
        body = self._body()
        key = self.headers.get("Idempotency-Key")

        # ── brief.create: заказчик формулирует задачу ──────────────────────
        # Обязательство слабое и обратимое: бриф можно отменить, пока нет
        # контракта. Поэтому сценарий начинается именно с него (§4.2).
        if url.path == "/api/briefs":
            token_field = (body.get("client_token") or "").strip()
            if not token_field:
                return self._send(400, {"error": "требуется поле client_token (идемпотентность)"})
            ok, _ = self._idem_begin("brief.create", token_field)
            if not ok:
                return None
            client = (body.get("client") or "").strip()
            title = (body.get("title") or "").strip()
            cap = to_cents(body.get("budget_cap"))
            if not client or not title:
                return self._send(400, {"error": "client и title обязательны"})
            if cap is None or cap <= 0:
                return self._send(400, {"error": "budget_cap должен быть положительным числом"})

            brief = secrets.token_hex(16)
            self.conn.execute(
                "INSERT INTO briefs (brief_token, client, title, spec, budget_cap_cents,"
                " currency, created_at) VALUES (?,?,?,?,?,?,?)",
                (brief, client, title, body.get("spec", ""), cap,
                 body.get("currency", "EUR"), now_iso()),
            )
            return self._ok(201, "brief.create", token_field, {
                "brief_token": brief, "status": "open",
                "budget_cap": money(cap), "currency": body.get("currency", "EUR"),
            })

        # ── quote.request: удержание внимания исполнителя ─────────────────
        if url.path == "/api/quote-requests":
            brief_token = body.get("brief_token")
            cid = body.get("contractor_id")
            brief = self.conn.execute(
                "SELECT brief_token, status FROM briefs WHERE brief_token = ?", (brief_token,)
            ).fetchone()
            if brief is None:
                return self._send(404, {"error": "бриф не найден"})
            if brief["status"] != "open":
                return self._send(409, {"error": f"бриф в состоянии '{brief['status']}'"})
            contractor = self.conn.execute(
                "SELECT id FROM contractors WHERE id = ?", (cid,)
            ).fetchone()
            if contractor is None:
                return self._send(404, {"error": "исполнитель не найден"})
            busy = self.conn.execute(
                "SELECT id FROM quote_requests WHERE brief_token = ? AND contractor_id = ?"
                " AND released = 0", (brief_token, cid)
            ).fetchone()
            if busy is not None:
                return self._send(409, {"error": "запрос оценки уже удерживается",
                                        "hold_id": busy["id"]})

            rid = "qr_" + uuid.uuid4().hex[:12]
            expires = (datetime.now(timezone.utc) + timedelta(seconds=QUOTE_REQUEST_TTL_S)
                       ).isoformat(timespec="seconds").replace("+00:00", "Z")
            self.conn.execute(
                "INSERT INTO quote_requests (id, brief_token, contractor_id, created_at, expires_at)"
                " VALUES (?,?,?,?,?)", (rid, brief_token, cid, now_iso(), expires),
            )
            self.conn.commit()
            # hold_id — то же значение под обобщённым именем: удержание здесь
            # устроено так же, как слот в клинике, и обобщённый агент из npp_act
            # должен работать с ним без правок.
            return self._send(201, {"request_id": rid, "hold_id": rid,
                                    "expires_at": expires, "ttl_s": QUOTE_REQUEST_TTL_S})

        # ── quote.give: исполнитель связывает себя ценой и сроком ─────────
        if url.path == "/api/quotes":
            ok, _ = self._idem_begin("quote.give", key)
            if not ok:
                return None
            req = self.conn.execute(
                "SELECT id, brief_token, contractor_id, released, expires_at FROM quote_requests"
                " WHERE id = ?", (body.get("request_id"),)
            ).fetchone()
            if req is None:
                return self._send(404, {"error": "запрос оценки не найден"})
            if req["released"] or req["expires_at"] <= now_iso():
                return self._send(409, {"error": "запрос оценки истёк или снят"})

            price = to_cents(body.get("price"))
            hours = body.get("hours")
            week = str(body.get("week") or "")
            if price is None or price <= 0:
                return self._send(400, {"error": "price должен быть положительным числом"})
            if not isinstance(hours, int) or hours <= 0:
                return self._send(400, {"error": "hours должен быть целым положительным"})
            start = week_start(week)
            if start is None:
                return self._send(400, {"error": "week должен иметь вид '2026-W42'"})
            if start + timedelta(days=7) <= today():
                return self._send(409, {"error": "неделя уже прошла: время невозвратно"})

            contractor = self.conn.execute(
                "SELECT id, hours_per_week FROM contractors WHERE id = ?", (req["contractor_id"],)
            ).fetchone()
            if hours > contractor["hours_per_week"]:
                # Оценка сверх недельной ёмкости неисполнима в принципе, и отказ
                # здесь дешевле отказа на подписании: исполнитель ещё не связал
                # себя ценой, а заказчик ещё не внёс деньги.
                return self._send(409, {
                    "error": "оценка превышает недельную ёмкость исполнителя",
                    "hours_per_week": contractor["hours_per_week"], "requested_hours": hours,
                })

            valid_s = int(body.get("valid_s") or QUOTE_VALID_S)
            valid_until = (datetime.now(timezone.utc) + timedelta(seconds=valid_s)
                           ).isoformat(timespec="seconds").replace("+00:00", "Z")
            quote = secrets.token_hex(16)
            self.conn.execute(
                "INSERT INTO quotes (quote_token, request_id, brief_token, contractor_id,"
                " price_cents, currency, hours, week, valid_until, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (quote, req["id"], req["brief_token"], req["contractor_id"], price,
                 body.get("currency", "EUR"), hours, week, valid_until, now_iso()),
            )
            # Оценка закрывает удержание: внимание исполнителя больше не держат,
            # теперь держит обязательство по цене — и у него свой срок.
            self.conn.execute("UPDATE quote_requests SET released = 1 WHERE id = ?", (req["id"],))
            return self._ok(201, "quote.give", key, {
                "quote_token": quote, "contractor_id": req["contractor_id"],
                "price": money(price), "price_cents": price,
                "currency": body.get("currency", "EUR"),
                "hours": hours, "week": week, "valid_until": valid_until, "state": "given",
            })

        # ── escrow.fund: деньги удерживаются ДО работы ────────────────────
        if url.path == "/api/escrow":
            ok, _ = self._idem_begin("escrow.fund", key)
            if not ok:
                return None
            brief = self.conn.execute(
                "SELECT brief_token, status, budget_cap_cents, currency FROM briefs"
                " WHERE brief_token = ?", (body.get("brief_token"),)
            ).fetchone()
            if brief is None:
                return self._send(404, {"error": "бриф не найден"})
            if brief["status"] != "open":
                return self._send(409, {"error": f"бриф в состоянии '{brief['status']}'"})
            amount = to_cents(body.get("amount"))
            if amount is None or amount <= 0:
                return self._send(400, {"error": "amount должен быть положительным числом"})
            if amount > brief["budget_cap_cents"]:
                return self._send(409, {
                    "error": "эскроу выше объявленного бюджета брифа",
                    "budget_cap": money(brief["budget_cap_cents"]),
                })
            token = "esc_" + secrets.token_hex(12)
            self.conn.execute(
                "INSERT INTO escrows (escrow_token, brief_token, amount_cents, currency, created_at)"
                " VALUES (?,?,?,?,?)",
                (token, brief["brief_token"], amount, brief["currency"], now_iso()),
            )
            return self._ok(201, "escrow.fund", key, {
                "escrow_token": token, "amount": money(amount), "amount_cents": amount,
                "currency": brief["currency"], "state": "held",
            })

        # ── escrow.refund: возврат заказчику ──────────────────────────────
        if url.path.startswith("/api/escrow/") and url.path.endswith("/refund"):
            token = url.path[len("/api/escrow/"):-len("/refund")]
            ok, _ = self._idem_begin("escrow.refund", key)
            if not ok:
                return None
            esc = self.conn.execute(
                "SELECT escrow_token, state, amount_cents, currency FROM escrows"
                " WHERE escrow_token = ?", (token,)
            ).fetchone()
            if esc is None:
                return self._send(404, {"error": "эскроу не найден"})
            if esc["state"] != "held":
                return self._send(409, {"error": f"эскроу уже в состоянии '{esc['state']}'"})
            live = self.conn.execute(
                "SELECT contract_token, status FROM contracts WHERE escrow_token = ?"
                " AND status != 'cancelled'", (token,)
            ).fetchone()
            if live is not None:
                return self._send(409, {
                    "error": "эскроу обеспечивает действующий контракт",
                    "contract_status": live["status"],
                })
            self.conn.execute(
                "UPDATE escrows SET state = 'refunded' WHERE escrow_token = ?", (token,)
            )
            return self._ok(200, "escrow.refund", key, {
                "escrow_token": token, "state": "refunded",
                "amount": money(esc["amount_cents"]), "currency": esc["currency"],
            })

        # ── contract.sign: двустороннее обязательство ─────────────────────
        if url.path == "/api/contracts":
            ok, _ = self._idem_begin("contract.sign", key)
            if not ok:
                return None
            brief = self.conn.execute(
                "SELECT brief_token, client, status FROM briefs WHERE brief_token = ?",
                (body.get("brief_token"),)
            ).fetchone()
            if brief is None:
                return self._send(404, {"error": "бриф не найден"})
            if brief["status"] != "open":
                return self._send(409, {"error": f"бриф в состоянии '{brief['status']}'"})

            quote = self.conn.execute(
                "SELECT * FROM quotes WHERE quote_token = ?", (body.get("quote_token"),)
            ).fetchone()
            if quote is None:
                return self._send(404, {"error": "оценка не найдена"})
            if quote["state"] != "given":
                return self._send(409, {"error": f"оценка в состоянии '{quote['state']}'"})
            if quote["valid_until"] <= now_iso():
                return self._send(409, {"error": "оценка истекла — запросите новую"})
            if quote["brief_token"] != brief["brief_token"]:
                return self._send(409, {"error": "оценка относится к другому брифу"})

            esc = self.conn.execute(
                "SELECT * FROM escrows WHERE escrow_token = ?", (body.get("escrow_token"),)
            ).fetchone()
            if esc is None:
                return self._send(404, {"error": "эскроу не найден"})
            if esc["state"] != "held":
                return self._send(409, {"error": f"эскроу в состоянии '{esc['state']}'"})
            if esc["brief_token"] != brief["brief_token"]:
                return self._send(409, {"error": "эскроу относится к другому брифу"})
            # Сравнение целых центов: обязательство не подписывается, если
            # обеспечение расходится с ценой хотя бы на цент.
            if esc["amount_cents"] < quote["price_cents"]:
                return self._send(409, {
                    "error": "эскроу не покрывает цену оценки",
                    "escrow": money(esc["amount_cents"]), "price": money(quote["price_cents"]),
                })

            start = week_start(quote["week"])
            if start is None or start + timedelta(days=7) <= today():
                return self._send(409, {"error": "неделя уже прошла: время невозвратно"})

            contractor = self.conn.execute(
                "SELECT id, name, hours_per_week FROM contractors WHERE id = ?",
                (quote["contractor_id"],)
            ).fetchone()
            free = free_hours(self.conn, contractor["id"], quote["week"],
                              contractor["hours_per_week"])
            if quote["hours"] > free:
                # Главный отказ сферы услуг. Склад можно пополнить, ёмкость — нет:
                # у исполнителя нет и не может быть «ещё десяти часов» на этой неделе.
                return self._send(409, {
                    "error": "сверх ёмкости исполнителя",
                    "week": quote["week"], "free_hours": free,
                    "requested_hours": quote["hours"],
                    "hours_per_week": contractor["hours_per_week"],
                })

            token = secrets.token_hex(16)
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute(
                    "INSERT INTO contracts (contract_token, brief_token, quote_token, escrow_token,"
                    " contractor_id, client, price_cents, currency, hours, week, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (token, brief["brief_token"], quote["quote_token"], esc["escrow_token"],
                     contractor["id"], brief["client"], quote["price_cents"], quote["currency"],
                     quote["hours"], quote["week"], now_iso()),
                )
                self.conn.execute(
                    "INSERT INTO capacity_holds (contractor_id, week, hours, contract_token,"
                    " created_at) VALUES (?,?,?,?,?)",
                    (contractor["id"], quote["week"], quote["hours"], token, now_iso()),
                )
                self.conn.execute(
                    "UPDATE quotes SET state = 'used' WHERE quote_token = ?", (quote["quote_token"],)
                )
                self.conn.execute(
                    "UPDATE briefs SET status = 'contracted' WHERE brief_token = ?",
                    (brief["brief_token"],)
                )
                self.conn.commit()
            except sqlite3.Error as e:
                self.conn.rollback()
                return self._send(500, {"error": f"сбой транзакции: {e}"})

            return self._ok(201, "contract.sign", key, {
                "contract_token": token, "work_ref": work_ref(token),
                "contractor_id": contractor["id"], "contractor": contractor["name"],
                "client": brief["client"],
                "price": money(quote["price_cents"]), "price_cents": quote["price_cents"],
                "currency": quote["currency"], "hours": quote["hours"], "week": quote["week"],
                "status": "signed", "revisions": 0,
                "free_hours_left": free - quote["hours"],
            })

        # ── глаголы над контрактом ────────────────────────────────────────
        if url.path.startswith("/api/contracts/") and url.path.count("/") == 4:
            token, _, action = url.path[len("/api/contracts/"):].partition("/")

            if action == "deliveries":
                return self._deliver(token, key, body)
            if action == "revision":
                return self._revise(token, key, body)
            if action == "acceptance":
                return self._accept(token, key, body)
            if action == "payment":
                return self._pay(token, key)
            if action == "cancel":
                return self._cancel(token, key, body)
            if action == "endorsement":
                return self._endorse(token, key, body)

        return self._send(404, {"error": "неизвестный маршрут"})

    # ---------- сдача-приёмка ----------

    def _deliver(self, token: str, key: str | None, body: dict) -> None:
        ok, _ = self._idem_begin("work.deliver", key)
        if not ok:
            return None
        row = self._contract(token)
        if row is None:
            return self._send(404, {"error": "контракт не найден"})
        if row["status"] not in ("signed", "in_work"):
            return self._send(409, {"error": f"сдавать нечего: контракт в состоянии '{row['status']}'"})
        artifact = (body.get("artifact") or "").strip()
        if not artifact:
            return self._send(400, {"error": "artifact обязателен — сдаётся результат, а не отчёт"})

        revision = self.conn.execute(
            "SELECT count(*) FROM deliveries WHERE contract_token = ?", (token,)
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO deliveries (contract_token, revision, artifact, note, created_at)"
            " VALUES (?,?,?,?,?)",
            (token, revision, artifact, body.get("note", ""), now_iso()),
        )
        self.conn.execute(
            "UPDATE contracts SET status = 'delivered' WHERE contract_token = ?", (token,)
        )
        return self._ok(201, "work.deliver", key, {
            "contract_token": token, "revision": revision,
            "status": "delivered", "artifact": artifact,
        })

    def _revise(self, token: str, key: str | None, body: dict) -> None:
        """Возврат на доработку — рабочая фаза, а не разрыв обязательства.

        В товарном ERP такого состояния нет: товар либо отгружен, либо нет.
        Здесь приёмка может вернуть работу сколько угодно раз, контракт при этом
        жив, ёмкость недели остаётся занятой, эскроу остаётся удержанным.
        """
        ok, _ = self._idem_begin("work.revise", key)
        if not ok:
            return None
        row = self._contract(token)
        if row is None:
            return self._send(404, {"error": "контракт не найден"})
        if row["status"] != "delivered":
            return self._send(409, {
                "error": f"возвращать нечего: контракт в состоянии '{row['status']}'"})
        comment = (body.get("comment") or "").strip()
        if not comment:
            return self._send(400, {"error": "comment обязателен: доработка без замечаний бессмысленна"})

        revisions = row["revisions"] + 1
        self.conn.execute(
            "UPDATE contracts SET status = 'in_work', revisions = ? WHERE contract_token = ?",
            (revisions, token),
        )
        return self._ok(200, "work.revise", key, {
            "contract_token": token, "status": "in_work", "revisions": revisions,
            "contract_alive": True, "comment": comment,
        })

    def _accept(self, token: str, key: str | None, body: dict) -> None:
        ok, _ = self._idem_begin("work.accept", key)
        if not ok:
            return None
        row = self._contract(token)
        if row is None:
            return self._send(404, {"error": "контракт не найден"})
        if row["status"] != "delivered":
            return self._send(409, {
                "error": f"принимать можно только сданную работу (сейчас '{row['status']}')"})
        ts = now_iso()
        self.conn.execute(
            "UPDATE contracts SET status = 'accepted', accepted_at = ? WHERE contract_token = ?",
            (ts, token),
        )
        # Приёмка необратима: именно она превращает работу в выполненное
        # обязательство, а выполненное обязательство — единственное, что в этой
        # модели даёт репутацию.
        return self._ok(200, "work.accept", key, {
            "contract_token": token, "work_ref": work_ref(token),
            "status": "accepted", "revisions": row["revisions"], "accepted_at": ts,
        })

    def _pay(self, token: str, key: str | None) -> None:
        ok, _ = self._idem_begin("payment.release", key)
        if not ok:
            return None
        row = self._contract(token)
        if row is None:
            return self._send(404, {"error": "контракт не найден"})
        if row["status"] != "accepted":
            # Смысл эскроу ровно в этом отказе: деньги не уходят, пока заказчик
            # не принял работу, и не возвращаются, пока принял.
            return self._send(409, {
                "error": "эскроу выплачивается только после приёмки",
                "status": row["status"],
            })
        esc = self.conn.execute(
            "SELECT escrow_token, state, amount_cents, currency FROM escrows"
            " WHERE escrow_token = ?", (row["escrow_token"],)
        ).fetchone()
        if esc is None or esc["state"] != "held":
            return self._send(409, {"error": "эскроу не удержан"})
        contractor = self.conn.execute(
            "SELECT name FROM contractors WHERE id = ?", (row["contractor_id"],)
        ).fetchone()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "UPDATE escrows SET state = 'released' WHERE escrow_token = ?", (esc["escrow_token"],)
            )
            self.conn.execute(
                "UPDATE contracts SET status = 'paid', closed_at = ? WHERE contract_token = ?",
                (now_iso(), token),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            return self._send(500, {"error": f"сбой транзакции: {e}"})

        return self._ok(200, "payment.release", key, {
            "contract_token": token, "status": "paid",
            "amount": money(row["price_cents"]), "amount_cents": row["price_cents"],
            "currency": row["currency"], "paid_to": contractor["name"] if contractor else "",
            "escrow_state": "released",
        })

    def _cancel(self, token: str, key: str | None, body: dict) -> None:
        """Расторжение. Возвращает ёмкость только будущих недель.

        Деньги при расторжении НЕ двигаются: возврат эскроу — отдельный глагол
        с effect=money. Прятать движение денег внутрь расторжения значило бы
        скрыть от губернатора последствие, из-за которого он и существует.
        """
        ok, _ = self._idem_begin("contract.cancel", key)
        if not ok:
            return None
        row = self._contract(token)
        if row is None:
            return self._send(404, {"error": "контракт не найден"})
        if row["status"] not in ACTIVE_CONTRACT:
            return self._send(409, {
                "error": f"расторгать нечего: контракт в состоянии '{row['status']}'"})

        burned = week_started(row["week"])
        new_state = "burned" if burned else "released"
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "UPDATE capacity_holds SET state = ? WHERE contract_token = ? AND state = 'held'",
                (new_state, token),
            )
            self.conn.execute(
                "UPDATE contracts SET status = 'cancelled', closed_at = ? WHERE contract_token = ?",
                (now_iso(), token),
            )
            # Задача возвращается в поиск, а не закрывается: в услугах заказчик
            # чаще ищет другого исполнителя, чем отказывается от задачи.
            self.conn.execute(
                "UPDATE briefs SET status = 'open' WHERE brief_token = ?", (row["brief_token"],)
            )
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            return self._send(500, {"error": f"сбой транзакции: {e}"})

        return self._ok(200, "contract.cancel", key, {
            "contract_token": token, "status": "cancelled",
            "reason": body.get("reason", ""),
            "capacity_returned_hours": 0 if burned else row["hours"],
            "capacity_burned_hours": row["hours"] if burned else 0,
            "week_started": burned,
            "escrow_state": "held",
            "next": "escrow.refund — деньги возвращает отдельный глагол",
        })

    def _endorse(self, token: str, key: str | None, body: dict) -> None:
        """Цеховая модель репутации: рекомендация относится к РАБОТЕ.

        Профиль не несёт рейтинга. Он несёт список выполненных обязательств,
        и каждая рекомендация привязана к одному из них через work_ref. Поэтому
        её нельзя ни перенести на другую работу, ни выдать до приёмки.
        """
        ok, _ = self._idem_begin("reputation.endorse", key)
        if not ok:
            return None
        row = self._contract(token)
        if row is None:
            return self._send(404, {"error": "контракт не найден"})
        if row["status"] not in DONE_CONTRACT:
            return self._send(409, {
                "error": "рекомендация относится к выполненной работе",
                "status": row["status"],
            })
        verdict = body.get("verdict", "recommend")
        if verdict not in ("recommend", "with_reservations"):
            return self._send(400, {"error": "verdict: 'recommend' либо 'with_reservations'"})
        ref = work_ref(token)
        self.conn.execute(
            "INSERT INTO endorsements (contract_token, work_ref, contractor_id, client, verdict,"
            " comment, created_at) VALUES (?,?,?,?,?,?,?)",
            (token, ref, row["contractor_id"], row["client"], verdict,
             body.get("comment", ""), now_iso()),
        )
        return self._ok(201, "reputation.endorse", key, {
            "work_ref": ref, "contractor_id": row["contractor_id"],
            "verdict": verdict, "comment": body.get("comment", ""),
        })

    # ---------- DELETE ----------

    def do_DELETE(self) -> None:
        with LOCK:
            try:
                self._delete()
            except Exception as e:
                self._send(500, {"error": f"внутренний сбой: {e}"})

    def _delete(self) -> None:
        url = urlparse(self.path)
        expire_requests(self.conn)

        # quote.withdraw — обратный глагол к quote.request
        if url.path.startswith("/api/quote-requests/"):
            rid = url.path.rsplit("/", 1)[-1]
            row = self.conn.execute(
                "SELECT id, released FROM quote_requests WHERE id = ?", (rid,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "запрос оценки не найден"})
            self.conn.execute("UPDATE quote_requests SET released = 1 WHERE id = ?", (rid,))
            self.conn.commit()
            return self._send(200, {"released": True, "hold_id": rid})

        # quote.revoke — обратный глагол к quote.give
        if url.path.startswith("/api/quotes/"):
            token = url.path.rsplit("/", 1)[-1]
            row = self.conn.execute(
                "SELECT quote_token, state FROM quotes WHERE quote_token = ?", (token,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "оценка не найдена"})
            if row["state"] == "used":
                return self._send(409, {"error": "оценка уже превращена в контракт"})
            self.conn.execute(
                "UPDATE quotes SET state = 'revoked' WHERE quote_token = ?", (token,)
            )
            self.conn.commit()
            return self._send(200, {"revoked": True, "quote_token": token})

        # brief.cancel — обратный глагол к brief.create
        if url.path.startswith("/api/briefs/"):
            token = url.path.rsplit("/", 1)[-1]
            key = self.headers.get("Idempotency-Key")
            ok, _ = self._idem_begin("brief.cancel", key)
            if not ok:
                return None
            row = self.conn.execute(
                "SELECT brief_token, status FROM briefs WHERE brief_token = ?", (token,)
            ).fetchone()
            if row is None:
                return self._send(404, {"error": "бриф не найден"})
            if row["status"] == "contracted":
                return self._send(409, {
                    "error": "бриф под контрактом: расторгать нужно контракт, а не бриф"})
            self.conn.execute(
                "UPDATE briefs SET status = 'cancelled' WHERE brief_token = ?", (token,)
            )
            self.conn.execute(
                "UPDATE quote_requests SET released = 1 WHERE brief_token = ? AND released = 0",
                (token,),
            )
            return self._ok(200, "brief.cancel", key, {
                "brief_token": token, "status": "cancelled",
            })

        return self._send(404, {"error": "неизвестный маршрут"})


def main() -> None:
    ap = argparse.ArgumentParser(
        description="NPP-Act: цех — сервис сферы услуг (продаёт обязательство во времени)"
    )
    ap.add_argument("--port", type=int, default=8220)
    ap.add_argument("--db", default="/tmp/npp_freelance.db")
    ap.add_argument("--reset", action="store_true", help="пересоздать базу")
    args = ap.parse_args()

    if args.reset and Path(args.db).exists():
        Path(args.db).unlink()

    conn = connect(args.db)
    init_db(conn)
    Handler.conn = conn

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"цех на http://127.0.0.1:{args.port}  (база {args.db})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
