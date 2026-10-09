"""Тесты жёсткого предиката H8: конфликт расписания блокирует обязательство.

ДИСЦИПЛИНА ПРОВЕРКИ. Ни один журнал здесь не пишется руками и ни один сервис не
подменяется моком. Поднимаются ДВА настоящих экземпляра сервиса заведения —
«Клиника Норд (Гамбург)» и «Клиника Зюд (Мюнхен)», — и Анна бронирует в них
время по настоящему HTTP через губернатора и двустороннее обязательство (§7).
Время, которое проверяет предикат, приходит из ответа `slot.list` настоящего
сервиса, а не из ожиданий теста: если сервис передвинет слот, тест это увидит.

Причина такой строгости записана в §10.1 спецификации и подтверждена в этом же
репозитории: смоук `plugin-marketplace` показывает 14/14 зелёных и при этом
сервис отвергает все настоящие бэкенды — ровно потому, что проверял себя своим
же моком. Предикат, который «блокирует конфликт» только против собственной
выдуманной записи, не блокирует ничего.

Что проверяется:
  1. пересечение по времени    — обязательство блокируется;
  2. недостижимость по дороге  — блокируется;
  3. превышение дневной ёмкости — блокируется;
  4. непротиворечивое обязательство — допускается;
  5. намерение без времени     — предикат воздерживается, не блокирует;
  6. губернатор без guard      — ведёт себя ровно как до этапа 14;
  7. отказ попадает в журнал как decision с verdict=block и внятной причиной.

Запуск:  python3 -m act.tests.test_schedule_guard
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import Agent, Budget, Executor, Governor, Ledger, Registry  # noqa: E402
from act.npp_act.calendar import (  # noqa: E402
    CAPACITY, OVERLAP, TRAVEL, TravelMatrix, detect_conflicts,
)
from act.npp_act.manifest import parse_manifest  # noqa: E402
from act.npp_act.schedule_guard import ScheduleGuard  # noqa: E402

PASSED = 0
FAILED = 0

NORD = "venue-clinic-nord"
SUED = "venue-clinic-sued"
PLACE_NORD = "Клиника Норд (Гамбург)"
PLACE_SUED = "Клиника Зюд (Мюнхен)"
PLACES = {NORD: PLACE_NORD, SUED: PLACE_SUED}

#: Четыре часа между Гамбургом и Мюнхеном. Это не параметр для красоты: именно
#: он превращает пару законных броней в неисполнимое расписание.
TRAVEL_HH_MUC = TravelMatrix({(PLACE_NORD, PLACE_SUED): 240})

#: Потолок цены во входе глагола: `cost.money` у `booking.create` объявлен
#: "variable", и без потолка губернатор обязан эскалировать (S2), а не решать.
MAX_MONEY = 200


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def answers(url: str) -> bool:
    """Отвечает ли по адресу хоть кто-нибудь — одна попытка, без ожидания."""
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            return True
    except Exception:
        return False


def wait_up(url: str, attempts: int = 150) -> bool:
    """Ждать, пока заведение ответит. Запас 15 с, а не 5, намеренно.

    Сценариев семь, и каждый поднимает свою пару сервисов: под нагрузкой
    интерпретатор стартует не мгновенно. Короткое ожидание давало ложное
    «сервис не поднялся» примерно раз на три прогона — а тест, падающий через
    раз, перестают читать, и вместе с ним перестают читать настоящие отказы.
    """
    for _ in range(attempts):
        if answers(url):
            return True
        time.sleep(0.1)
    return False


#: Курсор подбора портов: назад не возвращаемся, чтобы не попасть на порт,
#: который только что освободил предыдущий сценарий и который ещё может
#: ответить. Порт, отданный однажды, в этом прогоне больше не выдаётся.
BASE_PORT = 8241
_PORT_CURSOR = [BASE_PORT]


def pick_port() -> int:
    """Найти порт, который и молчит, и действительно свободен для bind.

    Двух проверок мало по отдельности: молчащий порт может быть занят чужим
    процессом, не отвечающим на HTTP, а успешный bind ничего не говорит о том,
    кто ответит на запрос. Нужны обе.
    """
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
    raise RuntimeError("свободных портов для заведений не нашлось")


# ────────────────────────────────────────────────────────────────────────────
# Инфраструктура: два настоящих заведения, агенты под губернатором
# ────────────────────────────────────────────────────────────────────────────


class Venues:
    """Пара настоящих заведений, поднимаемая заново для каждого сценария.

    Свежие экземпляры на каждый тест — не чистоплюйство: заведение торгует
    ВРЕМЕНЕМ, и забронированный вторник обратно не продаётся. Один общий набор
    слотов сделал бы тесты зависимыми от порядка запуска, а падение одного
    сценария превращалось бы в каскад «слот недоступен» в остальных.

    Порты подбираются свободными, а не берутся константами. Это не
    перестраховка: один раз этот тест уже «проходил» на ЧУЖОМ сервисе — новый
    процесс не смог занять порт, оставшийся от посторонней отладки, а
    `/api/health` отвечал, потому что отвечал тот посторонний. Тест, который
    принимает чужой живой сервис за свой, проверяет не то, что в нём написано, —
    это та же болезнь, что и проверка себя своим же моком.
    """

    def __init__(self, tmp: Path, tag: str):
        self.tmp = tmp / "venues" / tag
        self.ports = (pick_port(), pick_port())
        self.procs: list[subprocess.Popen] = []

    def __enter__(self) -> Registry:
        self.tmp.mkdir(parents=True, exist_ok=True)
        # stderr заведения уходит в файл, а не в /dev/null: сервис, который не
        # поднялся, обязан объяснить причину. Проглоченный stderr уже стоил
        # одного ложного «сервис не поднялся» без всяких подробностей.
        self.log = self.tmp / "venue.log"
        handle = self.log.open("w", encoding="utf-8")
        self._handle = handle
        for port, name in zip(self.ports, ("nord", "sued")):
            self.procs.append(subprocess.Popen(
                [sys.executable, "-m", "act.services.venue.server",
                 "--port", str(port), "--db", str(self.tmp / f"{name}.db"), "--reset"],
                cwd=str(ROOT), stdout=handle, stderr=handle))
        for port, proc in zip(self.ports, self.procs):
            if wait_up(f"http://127.0.0.1:{port}/api/health"):
                continue
            tail = self.log.read_text(encoding="utf-8", errors="replace")[-400:]
            raise RuntimeError(
                f"сервис заведения не поднялся на :{port} "
                f"(код выхода {proc.poll()}): {tail.strip() or 'без сообщений'}")
        return build_registry(f"http://127.0.0.1:{self.ports[0]}",
                              f"http://127.0.0.1:{self.ports[1]}")

    def __exit__(self, *exc) -> None:
        for p in self.procs:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        self.procs.clear()
        handle = getattr(self, "_handle", None)
        if handle is not None:
            handle.close()


def build_registry(nord_base: str, sued_base: str) -> Registry:
    """Реестр с двумя экземплярами одного сервиса.

    Второй манифест не подделка: тот же JSON с другим `service` и адресом
    проходит полную валидацию `parse_manifest`, то есть объявляет ровно те же
    последствия глаголов.
    """
    reg = Registry().load_dir(ROOT / "act/manifests")
    reg.rebind(NORD, nord_base)

    raw = json.loads((ROOT / "act/manifests/venue.act.json").read_text(encoding="utf-8"))
    raw["service"] = SUED
    raw["title"] = "Клиника «Зюд» — Мюнхен"
    raw["base_url"] = sued_base
    reg.add(parse_manifest(raw))
    return reg


def make_party(
    reg: Registry,
    folder: Path,
    name: str,
    *,
    guard: bool = False,
    travel=None,
    capacity_hours: float = 10.0,
    limit: float = 2000.0,
):
    """Сторона со своим журналом, бюджетом и (по желанию) предикатом H8.

    Guard строится на ТОМ ЖЕ объекте журнала, в который пишет исполнитель:
    предикат обязан видеть обязательство, взятое секунду назад, иначе он
    допустит второе на тот же час.
    """
    folder.mkdir(parents=True, exist_ok=True)
    led = Ledger(folder / f"{name.replace(':', '_')}.jsonl", owner=name)
    sg = None
    if guard:
        sg = ScheduleGuard(led, place_of=PLACES, travel=travel,
                           capacity_hours=capacity_hours)
    gov = Governor(reg, led, Budget(limit), schedule_guard=sg)
    return Agent(name, Executor(reg, gov, led)), led, gov, sg


def book(
    anna: Agent,
    clinic: Agent,
    service: str,
    day: str,
    at: str,
    *,
    announce_time: bool = True,
    subject: str | None = None,
) -> dict:
    """Полный цикл: прочитать каталог → удержать → зафиксировать обязательство.

    Время в намерение кладётся ровно то, которое отдал сервис (`slot["day"]`,
    `slot["time"]`), — именно так агент и узнаёт, на какой час он подписывается.
    Сервис лишние поля в теле игнорирует, так что намерение остаётся честным
    вызовом настоящего `POST /api/bookings`.

    `announce_time=False` воспроизводит намерение, в котором времени нет вовсе:
    предикат обязан воздержаться, а не достроить его.
    """
    out: dict = {"service": service, "slot": None, "payload": {}, "error": None,
                 "hold_decision": None, "decision": None, "commitment": None}

    res = anna.read(service, "slot.list", {"day": day})
    if res is None or not res.ok:
        out["error"] = "каталог не прочитан"
        return out
    slot = next((s for s in res.body if s["time"] == at), None)
    if slot is None:
        out["error"] = f"слот {day} {at} недоступен в {service}"
        return out
    out["slot"] = slot

    hold_decision, hold = anna.hold(service, "slot.hold", {"slot_id": slot["id"]})
    out["hold_decision"] = hold_decision
    if hold is None:
        out["error"] = f"удержание не взято: {hold_decision.reason}"
        return out

    payload = {"hold_id": hold.hold_id, "name": "Анна Иванова",
               "note": slot["specialist"], "max_money": MAX_MONEY}
    if announce_time:
        payload["day"] = slot["day"]
        payload["time"] = slot["time"]
    out["payload"] = payload

    out["subject"] = (subject if subject is not None
                      else f"приём {slot['day']} {slot['time']} · {slot['specialist']}")

    decision, cmt = anna.commit_two_party(
        service, "booking.create", payload,
        counterparty=clinic, hold=hold, subject=out["subject"],
    )
    out["decision"], out["commitment"] = decision, cmt
    if cmt is None:
        out["error"] = None  # отказ губернатора — это не сбой теста, а его предмет
    return out


def booking_decisions(led: Ledger) -> list:
    """Решения губернатора именно по `booking.create` — в порядке журнала."""
    return [r for r in led.by_kind("decision") if r.payload.get("verb") == "booking.create"]


def free_times(anna: Agent, service: str, day: str) -> list[str]:
    """Что сервис СЕЙЧАС считает свободным — проверка состояния мира, не теста."""
    res = anna.read(service, "slot.list", {"day": day})
    return [s["time"] for s in (res.body or [])] if res and res.ok else []


# ────────────────────────────────────────────────────────────────────────────
# 1. Пересечение по времени
# ────────────────────────────────────────────────────────────────────────────


def test_overlap(reg: Registry, tmp: Path) -> None:
    print("\nПересечение — в 09:00 нельзя быть в двух городах:")
    folder = tmp / "overlap"
    anna, led, _gov, guard = make_party(reg, folder, "person:anna", guard=True)
    nord, _, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    first = book(anna, nord, NORD, "2026-10-12", "09:00")
    check("первое обязательство допущено: расписание было пустым",
          first.get("commitment") is not None and first["decision"].admitted,
          str(first.get("error") or first["decision"]))
    if first.get("commitment") is None:
        return
    check("в решении отмечен пройденный предикат H8",
          any(c.startswith("H8") for c in first["decision"].checks),
          str(first["decision"].checks))

    # Ключевой инвариант: ТЕКУЩЕЕ расписание бесконфликтно по построению —
    # каждое прошлое обязательство проходило тот же предикат. Значит отказ ниже
    # вызван только новым обязательством, а не прежними грехами владельца.
    check("текущее расписание бесконфликтно (проверяется будущее, не текущее)",
          detect_conflicts(guard.timeline(), capacity_hours=10.0) == [],
          str([c.message for c in detect_conflicts(guard.timeline())]))

    second = book(anna, sued, SUED, "2026-10-12", "09:00")
    decision = second["decision"]
    check("удержание слота (effect=reserve) предикат не трогает",
          second.get("error") is None and second["hold_decision"].admitted,
          str(second.get("error")))
    check("пересекающееся обязательство заблокировано",
          decision.verdict == "block" and second["commitment"] is None, str(decision))
    check("причина названа конфликтом расписания",
          "конфликт расписания" in decision.reason and "неисполнимо" in decision.reason,
          decision.reason)
    check("в причине — объяснение из calendar.explain(): что с чем и на сколько",
          "пересекаются на 60 мин" in decision.reason
          and PLACE_NORD in decision.reason and PLACE_SUED in decision.reason,
          decision.reason)
    check("причина предъявляема: есть ссылка на строку журнала",
          "person:anna#" in decision.reason and "⨯" in decision.reason,
          decision.reason)
    check("предложено ближайшее свободное время (§5.3)",
          (decision.alternative or {}).get("starts_at") == "2026-10-12T10:00",
          str(decision.alternative))

    check("второго обязательства в журнале нет",
          len(led.by_kind("commitment")) == 1, str(len(led.by_kind("commitment"))))
    check("удержание отпущено, слот снова свободен у настоящего сервиса",
          "09:00" in free_times(anna, SUED, "2026-10-12"),
          str(free_times(anna, SUED, "2026-10-12")))


# ────────────────────────────────────────────────────────────────────────────
# 2. Отказ как запись журнала
# ────────────────────────────────────────────────────────────────────────────


def test_block_in_ledger(reg: Registry, tmp: Path) -> None:
    print("\nОтказ в журнале — предъявляемо и переживает перезапуск:")
    folder = tmp / "ledger"
    anna, led, _, _ = make_party(reg, folder, "person:anna", guard=True)
    nord, _, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    ok = book(anna, nord, NORD, "2026-10-12", "15:00")
    bad = book(anna, sued, SUED, "2026-10-12", "15:00")
    check("одно обязательство взято, второе отвергнуто",
          ok.get("commitment") is not None and bad["commitment"] is None,
          str(ok.get("error") or bad["decision"]))

    rows = booking_decisions(led)
    check("в журнале два решения по booking.create", len(rows) == 2, str(len(rows)))
    if len(rows) != 2:
        return
    allow, deny = rows[0].payload, rows[1].payload
    check("первое решение — admit", allow["verdict"] == "admit", str(allow["verdict"]))
    check("второе решение — block с verdict в записи",
          deny["verdict"] == "block", str(deny["verdict"]))
    check("причина отказа лежит в записи целиком, а не пересказом",
          deny["reason"] == bad["decision"].reason, deny["reason"])
    check("альтернатива сохранена вместе с отказом",
          isinstance(deny.get("alternative"), dict)
          and "starts_at" in deny["alternative"], str(deny.get("alternative")))
    check("отказ произошёл до H8 включительно: мягких предикатов в checks нет",
          not any(c.startswith("S") for c in deny["checks"]), str(deny["checks"]))
    execs = [r for r in led.by_kind("execution")
             if r.payload.get("verb") == "booking.create"]
    check("HTTP-вызов состоялся только у допущенного обязательства",
          len(execs) == 1 and execs[0].payload["status"] == 201,
          str([r.payload for r in execs]))

    check("хэш-цепь после отказа цела", led.verify())
    again = led.reload()
    rows2 = booking_decisions(again)
    check("отказ перечитывается с диска тем же текстом",
          len(rows2) == 2 and rows2[1].payload["reason"] == deny["reason"]
          and again.verify(),
          str(len(rows2)))


# ────────────────────────────────────────────────────────────────────────────
# 3. Недостижимость по дороге
# ────────────────────────────────────────────────────────────────────────────


def test_travel(reg: Registry, tmp: Path) -> None:
    print("\nДорога — из Гамбурга в Мюнхен за три с половиной часа не успеть:")
    folder = tmp / "travel"
    anna, led, _, guard = make_party(reg, folder, "person:anna",
                                     guard=True, travel=TRAVEL_HH_MUC)
    nord, _, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    first = book(anna, nord, NORD, "2026-10-12", "10:30")
    check("приём в Гамбурге на 10:30 оформлен",
          first.get("commitment") is not None, str(first.get("error")))
    if first.get("commitment") is None:
        return

    second = book(anna, sued, SUED, "2026-10-12", "15:00")
    decision = second["decision"]
    check("приём в Мюнхене на 15:00 заблокирован дорогой",
          decision.verdict == "block" and second["commitment"] is None, str(decision))
    check("в причине названы дорога, запас и опоздание",
          "дорога занимает 240 мин" in decision.reason
          and "в запасе 210 мин" in decision.reason
          and "опоздание на 30 мин" in decision.reason, decision.reason)
    check("указан источник числа: объявленная матрица, а не догадка",
          "по объявленной матрице" in decision.reason, decision.reason)
    check("предложено время, до которого успеть можно (15:30)",
          (decision.alternative or {}).get("starts_at") == "2026-10-12T15:30",
          str(decision.alternative))

    # То же расписание без объявленной дороги исполнимо — предикат не выдумывает
    # расстояний, которых владелец не объявил (TravelMatrix.default_between = 0).
    blind = ScheduleGuard(led, place_of=PLACES, capacity_hours=10.0)
    check("без матрицы дороги тот же шаг конфликта не даёт",
          blind.check(SUED, "booking.create", second["payload"],
                      reg.manifest(SUED)) == [],
          str([c.kind for c in blind.check(SUED, "booking.create",
                                           second["payload"], reg.manifest(SUED))]))
    with_matrix = guard.check(SUED, "booking.create", second["payload"],
                              reg.manifest(SUED))
    check("с матрицей — ровно один конфликт вида travel",
          [c.kind for c in with_matrix] == [TRAVEL],
          str([(c.kind, c.detail) for c in with_matrix]))


# ────────────────────────────────────────────────────────────────────────────
# 4. Дневная ёмкость
# ────────────────────────────────────────────────────────────────────────────


def test_capacity(reg: Registry, tmp: Path) -> None:
    print("\nЁмкость дня — больше взятого, чем в дне объявлено:")
    folder = tmp / "capacity"
    # 1.5 часа в сутки — заведомо малая ёмкость; взято так, чтобы перегрузка
    # наступила на втором приёме и её арифметику можно было проверить руками.
    anna, led, _, guard = make_party(reg, folder, "person:anna",
                                     guard=True, capacity_hours=1.5)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    first = book(anna, sued, SUED, "2026-10-13", "11:00")
    check("первый приём дня (1.0 ч ≤ 1.5 ч) допущен",
          first.get("commitment") is not None, str(first.get("error")))
    if first.get("commitment") is None:
        return

    second = book(anna, sued, SUED, "2026-10-13", "18:00")
    decision = second["decision"]
    check("второй приём того же дня заблокирован по ёмкости",
          decision.verdict == "block" and second["commitment"] is None, str(decision))
    check("в причине — часы, ёмкость и превышение",
          "на 2.0 ч" in decision.reason and "ёмкости 1.5 ч" in decision.reason
          and "превышение 0.5 ч" in decision.reason, decision.reason)
    check("сказано по-русски, что именно неисполнимо",
          "день не вмещает взятого" in decision.reason and "∑" in decision.reason,
          decision.reason)
    kinds = [c.kind for c in guard.check(SUED, "booking.create", second["payload"],
                                         reg.manifest(SUED))]
    check("вид конфликта — capacity", kinds == [CAPACITY], str(kinds))

    alt = decision.alternative or {}
    check("альтернатива уводит на следующий день — внутри дня места нет",
          str(alt.get("starts_at", "")).startswith("2026-10-14"), str(alt))

    # При объявленной человеком ёмкости тот же день исполним: предикат считает
    # по числу владельца, а не по собственному представлению о «много дел».
    roomy = ScheduleGuard(led, place_of=PLACES, capacity_hours=10.0)
    check("при ёмкости 10 ч тот же шаг проходит",
          roomy.check(SUED, "booking.create", second["payload"],
                      reg.manifest(SUED)) == [])


# ────────────────────────────────────────────────────────────────────────────
# 5. Непротиворечивое обязательство допускается
# ────────────────────────────────────────────────────────────────────────────


def test_admits(reg: Registry, tmp: Path) -> None:
    print("\nНепротиворечивое расписание — предикат не мешает:")
    folder = tmp / "admits"
    anna, led, _, guard = make_party(reg, folder, "person:anna",
                                     guard=True, travel=TRAVEL_HH_MUC)
    nord, _, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    deals = [
        book(anna, nord, NORD, "2026-10-12", "09:00"),   # Гамбург, 09:00–10:00
        book(anna, nord, NORD, "2026-10-12", "15:00"),   # Гамбург же, 15:00–16:00
        book(anna, sued, SUED, "2026-10-13", "11:00"),   # Мюнхен, другой день
    ]
    bad = [d["error"] or (None if d["commitment"] else d["decision"].reason)
           for d in deals]
    bad = [b for b in bad if b]
    check("все три обязательства допущены и записаны", not bad, "; ".join(bad))
    check("в журнале три обязательства",
          len(led.by_kind("commitment")) == 3, str(len(led.by_kind("commitment"))))
    check("ни одного block по booking.create",
          all(r.payload["verdict"] == "admit" for r in booking_decisions(led)),
          str([r.payload["verdict"] for r in booking_decisions(led)]))
    check("H8 отмечен пройденным в каждом решении",
          all(any(c.startswith("H8") for c in r.payload["checks"])
              for r in booking_decisions(led)))
    check("карта того же журнала подтверждает исполнимость",
          detect_conflicts(guard.timeline(), travel=TRAVEL_HH_MUC,
                           capacity_hours=10.0) == [],
          str([c.message for c in detect_conflicts(guard.timeline(),
                                                   travel=TRAVEL_HH_MUC)]))
    check("журнал цел", led.verify())


# ────────────────────────────────────────────────────────────────────────────
# 6. Намерение без времени: предикат воздерживается
# ────────────────────────────────────────────────────────────────────────────


def test_abstains(reg: Registry, tmp: Path) -> None:
    print("\nНамерение без времени — предикат молчит, а не догадывается:")
    folder = tmp / "abstain"
    anna, led, _, guard = make_party(reg, folder, "person:anna", guard=True)
    nord, _, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    first = book(anna, nord, NORD, "2026-10-12", "09:00")
    check("занятый час 09:00 записан настоящим обязательством",
          first.get("commitment") is not None, str(first.get("error")))
    if first.get("commitment") is None:
        return

    # Тот же конфликтующий час, но в намерении времени нет ни в полях, ни в
    # предмете сделки. Предикат обязан пропустить: оснований для отказа нет.
    second = book(anna, sued, SUED, "2026-10-12", "09:00",
                  announce_time=False, subject="приём у специалиста")
    decision = second["decision"]
    check("обязательство без объявленного времени допущено",
          decision.admitted and second["commitment"] is not None, str(decision))
    check("H8 отмечен пройденным, а не пропущенным молча",
          any(c.startswith("H8") for c in decision.checks), str(decision.checks))

    manifest = reg.manifest(SUED)
    check("гипотетическая запись не строится: времени нет",
          guard.proposed(SUED, "booking.create", second["payload"], manifest) is None)
    check("предикат на таком намерении возвращает пусто",
          guard.check(SUED, "booking.create", second["payload"], manifest) == [])
    check("альтернативы предикат тоже не выдумывает",
          guard.alternative(SUED, "booking.create", second["payload"], manifest) is None)

    # Доказательство, что молчание — именно воздержание, а не слепота: добавь в
    # то же намерение время, которое отдал сервис, — и конфликт находится.
    timed = dict(second["payload"])
    timed["day"], timed["time"] = second["slot"]["day"], second["slot"]["time"]
    found = guard.check(SUED, "booking.create", timed, manifest)
    check("то же намерение с объявленным временем конфликт находит",
          [c.kind for c in found] == [OVERLAP],
          str([(c.kind, c.message) for c in found]))
    check("время взято из ответа сервиса, а не из текста теста",
          guard.proposed(SUED, "booking.create", timed, manifest).starts_at.strftime(
              "%Y-%m-%d %H:%M") == f"{second['slot']['day']} {second['slot']['time']}")

    # Достаточно одной даты без часа — это ещё не время: полночь была бы догадкой.
    day_only = dict(second["payload"])
    day_only["day"] = second["slot"]["day"]
    check("одного дня без часа предикату не достаточно",
          guard.proposed(SUED, "booking.create", day_only, manifest) is None)

    # А человекочитаемый предмет сделки со временем — достаточно: именно так
    # агент уже сегодня пишет время, которого формату §7 не хватает полем.
    from_subject = dict(day_only)
    from_subject.pop("day")
    from_subject["subject"] = "приём 2026-10-12 09:30 · Терапевт"
    entry = guard.proposed(SUED, "booking.create", from_subject, manifest)
    check("время разбирается из предмета сделки",
          entry is not None and entry.starts_at.strftime("%H:%M") == "09:30",
          str(entry))
    check("и такое намерение тоже упирается в занятый час",
          [c.kind for c in guard.check(SUED, "booking.create", from_subject,
                                       manifest)] == [OVERLAP])


# ────────────────────────────────────────────────────────────────────────────
# 7. Губернатор без guard: поведение ровно прежнее
# ────────────────────────────────────────────────────────────────────────────


def test_without_guard(reg: Registry, tmp: Path) -> None:
    print("\nГубернатор без guard — поведение в точности как до этапа 14:")
    folder = tmp / "noguard"
    anna, led, gov, sg = make_party(reg, folder, "person:anna")  # guard=False
    nord, _, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    check("guard по умолчанию не подключён", sg is None and gov.schedule_guard is None)

    first = book(anna, nord, NORD, "2026-10-12", "09:00")
    second = book(anna, sued, SUED, "2026-10-12", "09:00")
    check("оба пересекающихся обязательства допущены, как и прежде",
          first.get("commitment") is not None and second.get("commitment") is not None,
          str(first.get("error") or second.get("error")
              or second["decision"].reason))
    check("в журнале два обязательства",
          len(led.by_kind("commitment")) == 2, str(len(led.by_kind("commitment"))))
    check("ни одного упоминания H8 в решениях",
          not any(c.startswith("H8") for r in booking_decisions(led)
                  for c in r.payload["checks"]),
          str([r.payload["checks"] for r in booking_decisions(led)]))

    # Данные при этом конфликтные: изменился предикат, а не расписание.
    after = detect_conflicts(
        ScheduleGuard(led, place_of=PLACES, capacity_hours=10.0).timeline(),
        capacity_hours=10.0)
    check("карта того же журнала показывает невозможную фигуру постфактум",
          [c.kind for c in after] == [OVERLAP],
          str([(c.kind, c.party) for c in after]))

    # Самая строгая форма «поведение прежнее»: решение по одинаковому первому
    # обязательству у губернатора с guard и без него должно совпадать во всём,
    # кроме единственной добавленной строки H8. Обе стороны берутся СВЕЖИМИ — с
    # пустым журналом и нетронутым бюджетом, — иначе в строке H3 разойдутся
    # остатки и сравнение перестанет что-либо доказывать. Два экземпляра одного
    # сервиса объявляют одинаковые последствия и одинаковые цены, поэтому
    # сравнивать их решения честно.
    with_g, _, _, _ = make_party(reg, tmp / "twin-guard", "person:gerda", guard=True)
    venue_g, _, _, _ = make_party(reg, tmp / "twin-guard", "venue:clinic-sued",
                                  limit=10_000.0)
    without_g, _, _, _ = make_party(reg, tmp / "twin-plain", "person:gerda")
    venue_p, _, _, _ = make_party(reg, tmp / "twin-plain", "venue:clinic-nord",
                                  limit=10_000.0)

    guarded = book(with_g, venue_g, SUED, "2026-10-13", "11:00")
    plain = book(without_g, venue_p, NORD, "2026-10-13", "11:00")
    check("обе брони-двойника оформлены",
          guarded["commitment"] is not None and plain["commitment"] is not None,
          str(guarded["error"] or plain["error"]))
    if guarded["commitment"] is None or plain["commitment"] is None:
        return
    minus_h8 = [c for c in guarded["decision"].checks if not c.startswith("H8")]
    check("набор предикатов без H8 совпадает строка в строку",
          minus_h8 == plain["decision"].checks,
          f"{minus_h8} ≠ {plain['decision'].checks}")
    check("вердикт и причина совпадают",
          (guarded["decision"].verdict, guarded["decision"].reason)
          == (plain["decision"].verdict, plain["decision"].reason),
          f"{guarded['decision']} ≠ {plain['decision']}")
    check("H8 добавил ровно одну строку и ничего не убрал",
          len(guarded["decision"].checks) - len(plain["decision"].checks) == 1,
          str(guarded["decision"].checks))


# ────────────────────────────────────────────────────────────────────────────


SCENARIOS = (
    ("overlap", test_overlap),
    ("ledger", test_block_in_ledger),
    ("travel", test_travel),
    ("capacity", test_capacity),
    ("admits", test_admits),
    ("abstain", test_abstains),
    ("noguard", test_without_guard),
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_act_guard_"))
    print(f"Сценариев: {len(SCENARIOS)}; у каждого своя пара настоящих заведений "
          f"(Норд и Зюд) со свежими слотами, порты от :{BASE_PORT}")
    try:
        for tag, scenario in SCENARIOS:
            try:
                with Venues(tmp, tag) as reg:
                    scenario(reg, tmp)
            except RuntimeError as e:
                check(f"сценарий «{tag}»: заведения подняты", False, str(e))
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
