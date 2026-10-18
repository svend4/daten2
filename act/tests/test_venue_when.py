"""Тесты блока `when`, который отдаёт СЕРВИС заведения (этап 21, §6.1).

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ И ПОЧЕМУ ИМЕННО ТАК

До этапа 21 клиент сам собирал `when` из ответа slot.list (день + час) и сам
подставлял длительность по умолчанию. Расхождение «клиент думает 09:00, сервис
продал 10:30» ловилось только тестом. Теперь блок отдаёт продавец: ответ брони
несёт `when`, GET брони отдаёт тот же блок, повтор по Idempotency-Key отдаёт тот
же блок байт в байт. Расхождение становится невозможным по построению, и тест
проверяет именно это, а не то, что клиент сумел догадаться.

ДИСЦИПЛИНА ПРОВЕРКИ (без моков сервиса)

1. Сервис — настоящий подпроцесс `act.services.venue.server` на свободном порту.
   Порт берётся двойной проверкой: молчит по HTTP И свободен для bind.
2. Ожидаемое смещение — ЛИТЕРАЛЫ из календаря, а не из кода сервиса:
   12 октября 2026 — летнее время (+02:00), 26 октября 2026 — зимнее (+01:00).
   Что сервис СКАЗАЛ, сверяется с тем, что он ХРАНИТ: блок берётся через GET.
3. Старые поля ответов перечислены ВРУЧНУЮ, а не выведены из кода: обратная
   совместимость сверяется с тем, что клиенты читали до этапа 21.
4. Миграция проверяется на базе, созданной ДОСЛОВНОЙ копией старой схемы, с
   бронью, которую сделал старый код. Такая база — то, что реально лежит у
   заведения до обновления.
5. Резервное правило часового пояса (если в системе нет базы tzdata) сверяется с
   zoneinfo поточасово за 2000–2040 годы. Оба — в одном процессе, поэтому это
   проверка правила, а не измерение сервиса, и подписана она так же.

Сценарии:
  1. «новая база»: длительности по специальностям; when в ответе брони, в GET и
     в повторе; смещения лета и зимы; старые поля на месте; запись не
     переписывается правкой слота (запись — доказательство);
  2. «старая база»: миграция добавляет колонки и не трогает данные; старая бронь
     без when получает его из слота; повтор старого ключа отдаёт тот же when;
     перезапуск не откатывает ручную правку длительности (миграция одноразовая);
  3. «часовой пояс»: резервное правило совпадает с zoneinfo, включая неоднозначный
     час осени и несуществующий час весны.

Запуск:  python3 -m act.tests.test_venue_when
"""

from __future__ import annotations

import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.services.venue import server as venue  # noqa: E402

PASSED = 0
FAILED = 0

NORD_PLACE = "Клиника «Норд»"
SUMMER_DAY = "2026-10-12"  # летнее время: +02:00
WINTER_DAY = "2026-10-26"  # зимнее время: +01:00

#: Ключи ответов ДО этапа 21. Записаны вручную, а не взяты из кода сервиса.
OLD_HEALTH = {"ok", "service", "title"}
OLD_HOLD = {"hold_id", "slot_id", "expires_at", "ttl_s"}
OLD_SLOT = {"id", "day", "time", "specialist", "price", "currency", "state"}
OLD_BOOKING_CREATE = {"booking_number", "total", "currency", "status"}
OLD_BOOKING_REPLAY = {"booking_number", "total", "currency", "idempotent_replay"}
OLD_BOOKING_GET = {"booking_number", "customer_name", "note", "total", "currency",
                   "status", "created_at", "day", "time", "specialist"}

#: Схема ДО этапа 21 — дословная копия, а не импорт. Если бы миграцию проверял
#: тот же код, что её пишет, тест сверял бы код с самим собой.
OLD_SCHEMA = """
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

OLD_SEED = [
    ("2026-10-12", "09:00", "Терапевт", 45.00),
    ("2026-10-12", "10:30", "Терапевт", 45.00),
    ("2026-10-12", "15:00", "Кардиолог", 90.00),
    ("2026-10-13", "11:00", "Терапевт", 45.00),
    ("2026-10-13", "18:00", "Кардиолог", 90.00),
]


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


# ────────────────────────────────────────────────────────────────────────────
# Порты и подпроцесс — тот же приём, что в test_when.py
# ────────────────────────────────────────────────────────────────────────────


def answers(url: str) -> bool:
    """Отвечает ли по адресу хоть кто-нибудь — одна попытка, без ожидания."""
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            return True
    except Exception:
        return False


def wait_up(url: str, attempts: int = 150) -> bool:
    for _ in range(attempts):
        if answers(url):
            return True
        time.sleep(0.1)
    return False


#: Диапазон 9400–9800: не пересекается с портами остальных наборов (8201–9330),
#: чтобы параллельный прогон соседнего набора не занял наш порт между проверкой и bind.
BASE_PORT = 9400
_PORT_CURSOR = [BASE_PORT]


def pick_port() -> int:
    """Порт, который и молчит по HTTP, и действительно свободен для bind."""
    while _PORT_CURSOR[0] < BASE_PORT + 400:
        port = _PORT_CURSOR[0]
        _PORT_CURSOR[0] += 1
        if answers(f"http://127.0.0.1:{port}/api/health"):
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("свободных портов для заведения не нашлось")


def call(base: str, method: str, path: str, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, object]:
    """HTTP-вызов к настоящему сервису. Ошибки статуса — это данные, а не исключения."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"_raw": raw}


class Service:
    """Настоящее заведение в подпроцессе. Перезапуск на той же базе — новый экземпляр."""

    def __init__(self, db: Path, log: Path):
        self.db = db
        self.log = log
        self.proc: subprocess.Popen | None = None
        self.base = ""
        self._handle = None

    def __enter__(self) -> str:
        port = pick_port()
        self.base = f"http://127.0.0.1:{port}"
        # stderr уходит в файл: сервис, который не поднялся, обязан объяснить причину.
        self._handle = self.log.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "act.services.venue.server",
             "--port", str(port), "--db", str(self.db)],
            cwd=str(ROOT), stdout=self._handle, stderr=self._handle)
        if not wait_up(f"{self.base}/api/health"):
            tail = self.log.read_text(encoding="utf-8", errors="replace")[-400:]
            self.__exit__(None, None, None)
            raise RuntimeError(
                f"сервис заведения не поднялся на :{port} "
                f"(код {self.proc.poll()}): {tail.strip() or 'без сообщений'}")
        return self.base

    def __exit__(self, *exc) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def sql(db: Path, statement: str, params: tuple = ()) -> list[tuple]:
    """Прямой доступ к файлу базы — только для подготовки и для проверки состояния."""
    conn = sqlite3.connect(str(db), timeout=10)
    try:
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def columns(db: Path, table: str) -> set[str]:
    return {row[1] for row in sql(db, f"PRAGMA table_info({table})")}


def find(slots: list, day: str, time_of_day: str, specialist: str) -> dict:
    for s in slots:
        if (s["day"], s["time"], s["specialist"]) == (day, time_of_day, specialist):
            return s
    raise AssertionError(f"слот {day} {time_of_day} {specialist} не найден в выдаче")


def reserve_and_book(base: str, slot: dict, name: str, key: str) -> tuple[int, dict, dict]:
    st, hold = call(base, "POST", "/api/holds", {"slot_id": slot["id"]})
    if st != 201:
        return st, hold, {}
    st, body = call(base, "POST", "/api/bookings",
                    {"hold_id": hold["hold_id"], "name": name, "note": "тест"},
                    {"Idempotency-Key": key})
    return st, body, hold


def make_fresh_db(db: Path) -> None:
    """Новая база тем же кодом, что делает main(): схема, посев, затем летний слот
    для зимней проверки (26 октября в посеве нет, и добавлять его в посев нельзя:
    это изменило бы выдачу slot.list остальных наборов)."""
    conn = venue.connect(str(db))
    try:
        venue.init_db(conn)
        conn.execute("INSERT INTO slots (day, time, specialist, price, duration_min)"
                     " VALUES (?,?,?,?,?)", (WINTER_DAY, "10:00", "Терапевт", 45.0, 30))
        conn.commit()
    finally:
        conn.close()


def make_legacy_db(db: Path) -> None:
    """База, какой она была ДО этапа 21: старая схема, старый посев и одна бронь,
    сделанная старым кодом (без when)."""
    conn = sqlite3.connect(str(db))
    conn.executescript(OLD_SCHEMA)
    conn.executemany("INSERT INTO slots (day, time, specialist, price) VALUES (?,?,?,?)", OLD_SEED)
    conn.execute("INSERT INTO slots (day, time, specialist, price) VALUES (?,?,?,?)",
                 (WINTER_DAY, "10:00", "Терапевт", 45.0))
    slot_id = conn.execute(
        "SELECT id FROM slots WHERE day = ? AND time = ? AND specialist = ?",
        (SUMMER_DAY, "09:00", "Терапевт")).fetchone()[0]
    conn.execute(
        "INSERT INTO bookings (booking_number, slot_id, customer_name, note, total,"
        " currency, status, idempotency_key, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("legacy-token-1", slot_id, "Старый Клиент", "", 45.0, "EUR", "confirmed",
         "legacy-key-1", "2026-10-01T10:00:00Z"))
    conn.execute("UPDATE slots SET state = 'booked' WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()


# ────────────────────────────────────────────────────────────────────────────
# Сценарий 1: новая база
# ────────────────────────────────────────────────────────────────────────────


def scenario_fresh(tmp: Path) -> None:
    db = tmp / "fresh" / "venue.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    make_fresh_db(db)

    with Service(db, tmp / "fresh" / "venue.log") as base:
        st, health = call(base, "GET", "/api/health")
        check("health: старые поля на месте", st == 200 and OLD_HEALTH <= set(health), str(health))
        check("место из title совпадает с тем, что пойдёт в when",
              str(health.get("title", "")).split(" — ")[0] == NORD_PLACE, str(health.get("title")))

        st, slots = call(base, "GET", "/api/slots")
        check("slots: старые поля + duration_min, и только они",
              st == 200 and all(set(s) == OLD_SLOT | {"duration_min"} for s in slots),
              str(slots[:1]))
        durations_ok = all(
            s["duration_min"] == (60 if s["specialist"] == "Кардиолог" else 30) for s in slots)
        check("длительность: Терапевт 30 мин, Кардиолог 60 (знание заведения, не cost.time_s)",
              durations_ok and any(s["specialist"] == "Кардиолог" for s in slots),
              str([(s["specialist"], s["duration_min"]) for s in slots]))

        slot_a = find(slots, SUMMER_DAY, "09:00", "Терапевт")
        key_a = uuid.uuid4().hex
        st, booked_a, hold_a = reserve_and_book(base, slot_a, "Анна", key_a)
        check("удержание: старые поля на месте", set(hold_a) >= OLD_HOLD, str(hold_a))
        check("бронь 201", st == 201, str(booked_a))
        check("бронь: старые поля + when, и только они",
              set(booked_a) == OLD_BOOKING_CREATE | {"when"}, str(sorted(booked_a)))
        when_a = booked_a["when"]
        check("when: блок из трёх полей §6.1",
              set(when_a) == {"starts_at", "duration_min", "place"}, str(when_a))
        check("when: 12 октября — летнее время заведения, +02:00",
              when_a["starts_at"] == "2026-10-12T09:00+02:00", when_a["starts_at"])
        check("when: длительность терапевта — 30 мин", when_a["duration_min"] == 30,
              str(when_a["duration_min"]))
        check("when: место — название заведения", when_a["place"] == NORD_PLACE, when_a["place"])

        st, got_a = call(base, "GET", f"/api/bookings/{booked_a['booking_number']}")
        check("GET: старые поля + when, и только они (внутренний when_json не утекает)",
              st == 200 and set(got_a) == OLD_BOOKING_GET | {"when"}, str(sorted(got_a)))
        check("GET отдаёт тот же when, что и ответ брони (сверка с хранимым, не с константой)",
              got_a.get("when") == when_a, f"{got_a.get('when')} ≠ {when_a}")
        check("when согласован с днём и часом, которые сервис продал в этой же записи",
              got_a["when"]["starts_at"].startswith(f"{got_a['day']}T{got_a['time']}"),
              f"{got_a['day']} {got_a['time']} / {got_a['when']['starts_at']}")

        st, replay_a = call(base, "POST", "/api/bookings",
                            {"hold_id": hold_a["hold_id"], "name": "Анна"},
                            {"Idempotency-Key": key_a})
        check("повтор по ключу: 200, idempotent_replay, та же бронь",
              st == 200 and replay_a.get("idempotent_replay") is True
              and replay_a.get("booking_number") == booked_a["booking_number"], str(replay_a))
        check("повтор: старые поля + when, и только они",
              set(replay_a) == OLD_BOOKING_REPLAY | {"when"}, str(sorted(replay_a)))
        check("повтор отдаёт тот же when, что и первый раз", replay_a.get("when") == when_a,
              f"{replay_a.get('when')} ≠ {when_a}")

        slot_c = find(slots, WINTER_DAY, "10:00", "Терапевт")
        st, booked_c, _ = reserve_and_book(base, slot_c, "Борис", uuid.uuid4().hex)
        check("зимнее время: 26 октября — +01:00",
              st == 201 and booked_c["when"]["starts_at"] == "2026-10-26T10:00+01:00",
              str(booked_c))

        slot_b = find(slots, SUMMER_DAY, "15:00", "Кардиолог")
        st, booked_b, _ = reserve_and_book(base, slot_b, "Вера", uuid.uuid4().hex)
        check("Кардиолог: длительность 60 мин в when",
              st == 201 and booked_b["when"]["duration_min"] == 60, str(booked_b))
        check("Кардиолог 12 октября: +02:00",
              booked_b["when"]["starts_at"] == "2026-10-12T15:00+02:00", str(booked_b.get("when")))

        st, bad = call(base, "POST", "/api/bookings", {"hold_id": "нет", "name": "x"})
        check("без Idempotency-Key по-прежнему 400", st == 400, str(st))

        # Запись — доказательство: правка слота после брони не переписывает её when.
        sql(db, "UPDATE slots SET duration_min = 45 WHERE id = ?", (slot_a["id"],))
        check("правка длительности в базе действительно сделана",
              sql(db, "SELECT duration_min FROM slots WHERE id = ?", (slot_a["id"],))[0][0] == 45)
        st, again = call(base, "GET", f"/api/bookings/{booked_a['booking_number']}")
        check("после правки слота when брони прежний (45 не просочилось в запись)",
              st == 200 and again.get("when") == when_a, str(again.get("when")))


# ────────────────────────────────────────────────────────────────────────────
# Сценарий 2: старая база, миграция
# ────────────────────────────────────────────────────────────────────────────


def scenario_legacy(tmp: Path) -> None:
    db = tmp / "legacy" / "venue.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    make_legacy_db(db)

    check("исходное состояние: старая база без duration_min и when_json",
          "duration_min" not in columns(db, "slots") and "when_json" not in columns(db, "bookings"))
    legacy_rows_before = sql(db, "SELECT booking_number, total, status FROM bookings")

    with Service(db, tmp / "legacy" / "venue.log") as base:
        check("старая база поднимается новым кодом (миграция без ошибок)", True)
        check("миграция добавила duration_min и when_json",
              "duration_min" in columns(db, "slots") and "when_json" in columns(db, "bookings"))
        check("миграция не тронула существующие брони",
              sql(db, "SELECT booking_number, total, status FROM bookings") == legacy_rows_before)

        st, legacy = call(base, "GET", "/api/bookings/legacy-token-1")
        check("старая бронь (без when в базе): 200 и when восстановлен из слота",
              st == 200 and legacy.get("when") == {
                  "starts_at": "2026-10-12T09:00+02:00", "duration_min": 30, "place": NORD_PLACE},
              str(legacy))
        check("старая бронь: старые поля на месте", set(legacy) == OLD_BOOKING_GET | {"when"},
              str(sorted(legacy)))

        st, replay = call(base, "POST", "/api/bookings", {"hold_id": "любой", "name": "x"},
                          {"Idempotency-Key": "legacy-key-1"})
        check("повтор старого ключа: 200, та же бронь, тот же when",
              st == 200 and replay.get("idempotent_replay") is True
              and replay.get("booking_number") == "legacy-token-1"
              and replay.get("when") == legacy["when"], str(replay))

        st, slots = call(base, "GET", "/api/slots")
        check("миграция: длительность по специальности для ВСЕХ слотов, старых тоже",
              st == 200 and all(
                  s["duration_min"] == (60 if s["specialist"] == "Кардиолог" else 30)
                  for s in slots) and bool(slots),
              str([(s["day"], s["time"], s["specialist"], s.get("duration_min")) for s in slots]))
        check("миграция: старые поля slots на месте",
              all(OLD_SLOT <= set(s) for s in slots))

        winter = find(slots, WINTER_DAY, "10:00", "Терапевт")
        st, booked, _ = reserve_and_book(base, winter, "Глеб", uuid.uuid4().hex)
        check("новая бронь на старой базе: 26 октября +01:00, 30 мин",
              st == 201 and booked["when"] == {
                  "starts_at": "2026-10-26T10:00+01:00", "duration_min": 30, "place": NORD_PLACE},
              str(booked))

        # Ручная правка длительности: миграция должна отработать ОДИН раз.
        sql(db, "UPDATE slots SET duration_min = 45 WHERE day = ? AND time = ? AND specialist = ?",
            ("2026-10-13", "11:00", "Терапевт"))

    with Service(db, tmp / "legacy" / "venue.log") as base2:
        st, slots2 = call(base2, "GET", "/api/slots")
        mine = find(slots2, "2026-10-13", "11:00", "Терапевт")
        check("перезапуск: миграция не переписывает ручную правку (45, не 30)",
              mine["duration_min"] == 45, str(mine.get("duration_min")))
        st, got = call(base2, "GET", f"/api/bookings/{booked['booking_number']}")
        check("бронь пережила перезапуск, when прежний",
              st == 200 and got.get("when") == booked["when"], str(got.get("when")))
        st, got_legacy = call(base2, "GET", "/api/bookings/legacy-token-1")
        check("старая бронь после перезапуска — тот же when",
              st == 200 and got_legacy.get("when") == legacy["when"], str(got_legacy.get("when")))


# ────────────────────────────────────────────────────────────────────────────
# Сценарий 3: резервное правило часового пояса против zoneinfo
# ────────────────────────────────────────────────────────────────────────────


def scenario_timezone(_tmp: Path) -> None:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Europe/Berlin")
    rule = venue.EuropeBerlinRule()
    print(f"  часовой пояс сервиса в этой системе: {venue.TZ_BACKEND}")

    # Поточасовая сверка за 2000–2040: около 82 переходов должны попасть в выборку,
    # иначе совпадение ничего не доказывает (пустая выборка тоже «совпадает»).
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    hours = 41 * 366 * 24
    mismatches: list[str] = []
    offsets_seen: set[timedelta] = set()
    transitions = 0
    previous = None
    for h in range(hours):
        local = (start + timedelta(hours=h)).astimezone(zone)
        zone_off = local.utcoffset()
        rule_off = local.replace(tzinfo=rule).utcoffset()
        offsets_seen.add(zone_off)
        if previous is not None and zone_off != previous:
            transitions += 1
        previous = zone_off
        if zone_off != rule_off and len(mismatches) < 5:
            mismatches.append(f"{local.isoformat()} zoneinfo={zone_off} rule={rule_off}")
    check("резерв совпадает с zoneinfo поточасово, 2000–2040 годы",
          not mismatches, "; ".join(mismatches))
    check("выборка содержит переходы летнего времени (иначе сверка пуста)",
          transitions >= 80 and offsets_seen == {timedelta(hours=1), timedelta(hours=2)},
          f"переходов {transitions}, смещения {sorted(map(str, offsets_seen))}")

    ambiguous_first = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0)
    ambiguous_second = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=1)
    check("неоднозначный час осени: первое вхождение — летнее (+02:00)",
          ambiguous_first.utcoffset() == timedelta(hours=2)
          and ambiguous_first.replace(tzinfo=rule).utcoffset() == timedelta(hours=2))
    check("неоднозначный час осени: второе вхождение — зимнее (+01:00)",
          ambiguous_second.utcoffset() == timedelta(hours=1)
          and ambiguous_second.replace(tzinfo=rule).utcoffset() == timedelta(hours=1))

    gap = datetime(2026, 3, 29, 2, 30, tzinfo=zone, fold=0)
    check("несуществующий час весны: резерв согласован с zoneinfo",
          gap.utcoffset() == gap.replace(tzinfo=rule).utcoffset(),
          f"{gap.utcoffset()} / {gap.replace(tzinfo=rule).utcoffset()}")


SCENARIOS = (
    ("новая база", scenario_fresh),
    ("старая база и миграция", scenario_legacy),
    ("часовой пояс", scenario_timezone),
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_act_venue_when_"))
    print(f"Сценариев: {len(SCENARIOS)}; сервисы — настоящие подпроцессы, порты от :{BASE_PORT}")
    try:
        for label, scenario in SCENARIOS:
            print(f"\n■ {label}")
            try:
                scenario(tmp)
            except Exception as e:  # сбой одного сценария не должен прятать остальные
                check(f"сценарий «{label}» выполнен", False, f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
