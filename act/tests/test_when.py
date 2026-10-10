"""Тесты блока `when` в записи обязательства (§6.1, этап 18).

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ И ПОЧЕМУ ИМЕННО ТАК

До этапа 18 время обязательства существовало только в человекочитаемой строке
`subject`, и предикат H8 выуживал его регуляркой. Такой гейт ломается молча:
стоит агенту написать «приём 12 октября в 9 утра» вместо «приём 2026-10-12
09:00», и H8 перестаёт видеть время — не ошибается, а ВОЗДЕРЖИВАЕТСЯ, оставляя
в журнале зелёное решение. Поэтому главный тест здесь не «when читается», а
«when читается ПЕРВЫМ и вопреки всему остальному»: `subject` во всех ключевых
сценариях подменён бессмыслицей без даты, а плоские `day`/`time` — НЕВЕРНЫМ
временем. Если гейт возьмёт время откуда-нибудь ещё, тест это увидит.

ДИСЦИПЛИНА ПРОВЕРКИ (почему здесь нет моков)

1. Время берётся у НАСТОЯЩЕГО сервиса. Поднимается подпроцессом реальная
   клиника (`act.services.venue.server`) на свободном порту, день и час
   приходят из ответа `slot.list`, а не из ожиданий теста. Если сервис
   передвинет слот, тест это увидит, а не подыграет себе.
2. То, что записано в журнал, сверяется с тем, что сервис говорит о броне:
   `booking.get` отдаёт `day`/`time` проданного слота, и блок `when` в
   хэш-цепи обязан совпасть с ними. Это внешний эталон содержимого записи:
   сверять `when` с константой в тесте значило бы проверять тест, а не запись.
3. Хэш-цепь пересчитывается НЕЗАВИСИМО от проекта. `hashlib` в этом файле не
   используется вообще: SHA-256 считает сторонний оракул — библиотека
   `cryptography` (через интерпретатор, в котором её бинарные привязки живы)
   или командная строка `openssl`. Так проверяется не только целость цепи, но
   и то, что блок `when` ею ПОКРЫТ: достаточно изменить в блоке одну минуту, и
   независимо посчитанный хэш расходится с записанным.
   (Под python3.11 этого окружения `import cryptography` падает: привязки
   `_cffi_backend` собраны для 3.12. Это не повод отказаться от независимой
   сверки — оракул вызывается процессом, и он всё так же сторонний.)
4. Порты не фиксированные: берутся двойной проверкой (молчит по HTTP И
   свободен для bind). Фиксированный порт уже заставлял тест в этом каталоге
   измерять ЧУЖОЙ процесс и отчитываться зелёным.

Сценарии:
  1. `when` записан у ОБЕИХ сторон, совпадает побайтово, покрыт хэш-цепью и
     согласуется с тем, что сервис говорит о проданном слоте;
  2. предикат H8 берёт время ИЗ `when`, хотя `subject` — бессмыслица, а
     плоские `day`/`time` в намерении указывают другое время;
  3. конфликт расписания обнаружен на основании `when` (и только его:
     разбор `subject` на этих записях не даёт ничего);
  4. без `when` поведение в точности прежнее — тело записи то же, что до
     этапа 18, старые записи читаются, деградация работает;
  5. негодный `when` отвергается внятно и ДО любых последствий: ни записи, ни
     брони, ни согласия; и не подменяется догадкой из годного `subject`.

Запуск:  python3 -m act.tests.test_when
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
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import Agent, Budget, Executor, Governor, Ledger, Registry  # noqa: E402
from act.npp_act.calendar import (  # noqa: E402
    DEFAULT_DURATION_MIN, OVERLAP, Entry, When, WhenError, _from_subject,
    build_timeline, normalize_when,
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

#: Потолок цены: `cost.money` у `booking.create` объявлен "variable", и без
#: потолка губернатор обязан эскалировать (S2), а не решать сам.
MAX_MONEY = 200

#: Предмет сделки БЕЗ времени. Ключевой реквизит тестов: пока время жило в
#: строке, такая формулировка ослепляла гейт. Теперь она не должна мешать.
BLIND_SUBJECT = "лот №7 на условиях прейскуранта"

#: Набор ключей тела записи `commitment` ДО этапа 18. Записывается здесь
#: вручную, а не берётся из кода: иначе проверка обратной совместимости
#: сверяла бы реализацию с собой же.
LEGACY_KEYS = {"commitment_id", "parties", "subject", "service", "verb"}


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


# ────────────────────────────────────────────────────────────────────────────
# Независимый оракул SHA-256: ни hashlib, ни код проекта
# ────────────────────────────────────────────────────────────────────────────


def _oracle_cryptography(data: bytes) -> str | None:
    """SHA-256 библиотекой `cryptography` в том интерпретаторе, где она жива."""
    code = (
        "import sys\n"
        "from cryptography.hazmat.primitives import hashes\n"
        "h = hashes.Hash(hashes.SHA256())\n"
        "h.update(sys.stdin.buffer.read())\n"
        "sys.stdout.write(h.finalize().hex())\n"
    )
    for interpreter in ("python3.13", "python3.12", sys.executable):
        try:
            done = subprocess.run([interpreter, "-c", code], input=data,
                                  capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        out = done.stdout.decode("ascii", "replace").strip()
        if done.returncode == 0 and len(out) == 64:
            return f"cryptography/{interpreter}:{out}"
    return None


def _oracle_openssl(data: bytes) -> str | None:
    """SHA-256 командной строкой OpenSSL — отдельный процесс, чужой код."""
    try:
        done = subprocess.run(["openssl", "dgst", "-sha256", "-r"],
                              input=data, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = done.stdout.decode("ascii", "replace").strip().split(" ")[0]
    return f"openssl:{out}" if done.returncode == 0 and len(out) == 64 else None


def independent_sha256(data: bytes) -> tuple[str, str]:
    """(хэш, имя оракула). Падает, если независимого оракула нет вовсе.

    Молча перейти на `hashlib` здесь было бы самосертификацией: проект считает
    свои хэши именно им, и сверка проекта с самим собой ничего не доказывает.
    Лучше красный тест, чем зелёный без внешней проверки.
    """
    for oracle in (_oracle_cryptography, _oracle_openssl):
        answer = oracle(data)
        if answer:
            name, _, digest = answer.partition(":")
            return digest, name
    raise RuntimeError(
        "независимого SHA-256 не нашлось: ни cryptography в доступных "
        "интерпретаторах, ни openssl в PATH — сверять хэш-цепь нечем"
    )


def canonical(obj) -> bytes:
    """Канонический JSON по §6: sort_keys, без пробелов, без ASCII-эскейпов.

    Рецепт взят из текста спецификации, а не из `ledger._canonical`: смысл
    сверки в том, чтобы повторить описанное в документе своими руками.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def raw_records(led: Ledger) -> list[dict]:
    """Строки журнала как они лежат на диске — без участия классов проекта."""
    text = Path(led.path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ────────────────────────────────────────────────────────────────────────────
# Настоящие заведения на свободных портах
# ────────────────────────────────────────────────────────────────────────────


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            return True
    except Exception:
        return False


def wait_up(url: str, attempts: int = 150) -> bool:
    """15 секунд запаса: у каждого сценария своя пара сервисов, старт не мгновенный."""
    for _ in range(attempts):
        if answers(url):
            return True
        time.sleep(0.1)
    return False


#: Курсор портов: назад не возвращаемся, чтобы не попасть на порт, который
#: только что освободил предыдущий сценарий и который ещё может ответить.
BASE_PORT = 8661
_PORT_CURSOR = [BASE_PORT]


def pick_port() -> int:
    """Порт, который и молчит по HTTP, и действительно свободен для bind.

    Двух проверок по отдельности мало: молчащий порт может быть занят чужим
    процессом, не отвечающим на HTTP, а успешный bind ничего не говорит о том,
    кто ответит на запрос.
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


class Venues:
    """Настоящие клиники, поднимаемые заново для каждого сценария.

    Свежие экземпляры на каждый сценарий обязательны: заведение торгует
    ВРЕМЕНЕМ, и забронированный вторник обратно не продаётся. Общий набор
    слотов сделал бы тесты зависимыми от порядка запуска.
    """

    def __init__(self, tmp: Path, tag: str, count: int = 1):
        self.tmp = tmp / "venues" / tag
        self.ports = tuple(pick_port() for _ in range(count))
        self.procs: list[subprocess.Popen] = []

    def __enter__(self) -> Registry:
        self.tmp.mkdir(parents=True, exist_ok=True)
        # stderr уходит в файл, а не в /dev/null: сервис, который не поднялся,
        # обязан объяснить причину.
        self.log = self.tmp / "venue.log"
        self._handle = self.log.open("w", encoding="utf-8")
        for port, name in zip(self.ports, ("nord", "sued", "west")):
            self.procs.append(subprocess.Popen(
                [sys.executable, "-m", "act.services.venue.server",
                 "--port", str(port), "--db", str(self.tmp / f"{name}.db"), "--reset"],
                cwd=str(ROOT), stdout=self._handle, stderr=self._handle))
        for port, proc in zip(self.ports, self.procs):
            if wait_up(f"http://127.0.0.1:{port}/api/health"):
                continue
            tail = self.log.read_text(encoding="utf-8", errors="replace")[-400:]
            raise RuntimeError(
                f"сервис заведения не поднялся на :{port} "
                f"(код выхода {proc.poll()}): {tail.strip() or 'без сообщений'}")
        return build_registry([f"http://127.0.0.1:{p}" for p in self.ports])

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


def build_registry(bases: list[str]) -> Registry:
    """Реестр с настоящими манифестами, перевешенными на поднятые порты.

    Второй экземпляр — не подделка: тот же JSON с другим `service` и адресом
    проходит полную валидацию `parse_manifest`, то есть объявляет ровно те же
    последствия глаголов, включая новый `when` во входе `booking.create`.
    """
    reg = Registry().load_dir(ROOT / "act/manifests")
    reg.rebind(NORD, bases[0])
    if len(bases) > 1:
        raw = json.loads((ROOT / "act/manifests/venue.act.json").read_text(encoding="utf-8"))
        raw["service"] = SUED
        raw["title"] = "Клиника «Зюд» — Мюнхен"
        raw["base_url"] = bases[1]
        reg.add(parse_manifest(raw))
    return reg


def make_party(
    reg: Registry,
    folder: Path,
    name: str,
    *,
    guard: bool = False,
    capacity_hours: float = 10.0,
    duration_of: dict | None = None,
    limit: float = 2000.0,
):
    """Сторона со своим журналом, бюджетом и (по желанию) предикатом H8.

    Guard строится на ТОМ ЖЕ объекте журнала, в который пишет исполнитель:
    предикат обязан видеть обязательство, взятое секунду назад.
    """
    folder.mkdir(parents=True, exist_ok=True)
    led = Ledger(folder / f"{name.replace(':', '_')}.jsonl", owner=name)
    sg = ScheduleGuard(led, place_of=PLACES, capacity_hours=capacity_hours,
                       duration_of=duration_of) if guard else None
    gov = Governor(reg, led, Budget(limit), schedule_guard=sg)
    return Agent(name, Executor(reg, gov, led)), led, gov, sg


def free_slots(agent: Agent, service: str, day: str) -> list[dict]:
    """Что сервис СЕЙЧАС считает свободным — состояние мира, а не теста."""
    res = agent.read(service, "slot.list", {"day": day})
    return list(res.body or []) if res and res.ok else []


def slot_at(agent: Agent, service: str, day: str, at: str) -> dict | None:
    return next((s for s in free_slots(agent, service, day) if s["time"] == at), None)


def take_hold(agent: Agent, service: str, slot: dict):
    return agent.hold(service, "slot.hold", {"slot_id": slot["id"]})


def book(
    anna: Agent,
    clinic: Agent,
    service: str,
    day: str,
    at: str,
    *,
    when: object = None,
    duration_min: int | None = None,
    subject: str = BLIND_SUBJECT,
    announce_flat: tuple[str, str] | None = None,
) -> dict:
    """Полный цикл: каталог → удержание → двустороннее обязательство.

    `when` строится из ОТВЕТА СЕРВИСА (`slot["day"]`, `slot["time"]`) методом
    агента, а не из литералов теста: именно так клиент и узнаёт, на какой час
    он подписывается. `announce_flat` кладёт в намерение плоские `day`/`time` —
    в сценариях приоритета там стоит НЕВЕРНОЕ время, чтобы было видно, какой
    источник выиграл.
    """
    out: dict = {"service": service, "slot": None, "payload": {}, "error": None,
                 "decision": None, "commitment": None, "result": None, "when": None}

    slot = slot_at(anna, service, day, at)
    if slot is None:
        out["error"] = f"слот {day} {at} недоступен в {service}"
        return out
    out["slot"] = slot

    hold_decision, hold = take_hold(anna, service, slot)
    if hold is None:
        out["error"] = f"удержание не взято: {hold_decision.reason}"
        return out
    out["hold"] = hold

    payload = {"hold_id": hold.hold_id, "name": "Анна Иванова",
               "note": slot["specialist"], "max_money": MAX_MONEY,
               "subject": subject}
    if announce_flat is not None:
        payload["day"], payload["time"] = announce_flat
    out["payload"] = payload

    block = when
    if block is None and duration_min is not None:
        block = anna.when_from_response(service, slot, duration_min=duration_min)
    out["when"] = block

    decision, cmt = anna.commit_two_party(
        service, "booking.create", payload,
        counterparty=clinic, hold=hold, subject=subject, when=block,
    )
    out["decision"], out["commitment"] = decision, cmt
    return out


def commitments(led: Ledger) -> list:
    return list(led.by_kind("commitment"))


def booking_decisions(led: Ledger) -> list:
    return [r for r in led.by_kind("decision") if r.payload.get("verb") == "booking.create"]


# ────────────────────────────────────────────────────────────────────────────
# 1. `when` записан у обеих сторон, покрыт цепью и согласован с сервисом
# ────────────────────────────────────────────────────────────────────────────


def test_written(reg: Registry, tmp: Path) -> None:
    print("\n[1] when в записях обеих сторон: цепь, покрытие хэшем, сверка с сервисом")
    folder = tmp / "written"
    anna, anna_led, _gov, _sg = make_party(reg, folder, "person:anna", guard=True)
    nord, nord_led, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)

    deal = book(anna, nord, NORD, "2026-10-12", "09:00", duration_min=30)
    check("обязательство оформлено", deal["commitment"] is not None,
          str(deal["error"] or deal["decision"]))
    if deal["commitment"] is None:
        return
    cmt, slot = deal["commitment"], deal["slot"]

    mine = [r for r in commitments(anna_led) if r.payload.get("commitment_id") == cmt.id]
    theirs = [r for r in commitments(nord_led) if r.payload.get("commitment_id") == cmt.id]
    check("запись commitment есть у обеих сторон", len(mine) == 1 and len(theirs) == 1,
          f"{len(mine)} / {len(theirs)}")
    if not mine or not theirs:
        return

    block_mine = mine[0].payload.get("when")
    block_theirs = theirs[0].payload.get("when")
    check("блок when есть в записи клиента", isinstance(block_mine, dict), str(block_mine))
    check("блок when есть в записи заведения", isinstance(block_theirs, dict),
          str(block_theirs))
    check("блоки сторон совпадают поле в поле", block_mine == block_theirs,
          f"{block_mine} ≠ {block_theirs}")
    if not isinstance(block_mine, dict) or not isinstance(block_theirs, dict):
        # Дальше сверять нечего: без блока проверки ниже не «не пройдены», а
        # бессмысленны. Сценарий выходит, оставив провалы выше как диагноз.
        return
    check("Commitment.when_agrees подтверждает совпадение по журналам",
          cmt.when_agrees({"person:anna": anna_led, "venue:clinic-nord": nord_led}))
    check("объявленная длительность записана как есть (30, а не час по умолчанию)",
          block_mine.get("duration_min") == 30 != DEFAULT_DURATION_MIN, str(block_mine))
    check("место в блоке — название из манифеста, а не идентификатор сервиса",
          block_mine.get("place") == "Клиника «Норд» — запись к специалисту",
          str(block_mine.get("place")))
    check("обе цепи целы после дописанных обязательств",
          anna_led.verify() and nord_led.verify())

    # ---- внешний эталон №1: что говорит о броне САМ СЕРВИС ----
    number = (deal["decision"], cmt)  # результат брони лежит в исходе журнала
    booking_number = ""
    for rec in anna_led.by_kind("outcome"):
        body = rec.payload.get("response")
        if rec.payload.get("verb") == "booking.create" and isinstance(body, dict):
            booking_number = str(body.get("booking_number") or "")
    check("номер брони получен из журнала исходов", bool(booking_number), str(number))
    if booking_number:
        res = anna.read(NORD, "booking.get", {"booking_number": booking_number})
        said = res.body if res and res.ok else {}
        declared = str(block_mine.get("starts_at"))
        check("when.starts_at совпадает с днём и часом, которые сервис продал",
              declared.startswith(str(said.get("day"))) and str(said.get("time")) in declared,
              f"журнал {declared!r} против сервиса {said.get('day')} {said.get('time')}")
        check("тот же час отдал и каталог слотов до брони",
              f"{slot['day']}T{slot['time']}" == declared,
              f"{slot['day']}T{slot['time']} ≠ {declared}")

    # ---- внешний эталон №2: независимый SHA-256 ----
    try:
        lines = raw_records(anna_led)
        target = next(r for r in lines if r.get("hash") == mine[0].hash)
        body = {k: target[k] for k in ("seq", "ts", "kind", "payload", "prev")}
        digest, oracle = independent_sha256(canonical(body))
        check(f"хэш записи воспроизведён независимо ({oracle})", digest == target["hash"],
              f"{digest} ≠ {target['hash']}")

        spoiled = json.loads(json.dumps(body))
        spoiled["payload"]["when"]["starts_at"] = (
            str(block_mine["starts_at"]).replace("09:00", "09:01"))
        other, _ = independent_sha256(canonical(spoiled))
        check("минута, изменённая в when, разрывает хэш — блок покрыт цепью",
              other != target["hash"], f"{other} == {target['hash']}")

        chain_ok = True
        prev = "0" * 64
        for row in lines:
            recomputed, _ = independent_sha256(canonical(
                {k: row[k] for k in ("seq", "ts", "kind", "payload", "prev")}))
            chain_ok = chain_ok and row["prev"] == prev and recomputed == row["hash"]
            prev = row["hash"]
        check(f"вся цепь клиента пересчитана посторонним оракулом ({oracle})", chain_ok,
              f"{len(lines)} записей")
    except RuntimeError as e:
        check("независимый оракул SHA-256 доступен", False, str(e))

    # ---- карта читает блок ----
    timeline = build_timeline({"person:anna": anna_led}, place_of=PLACES)
    check("карта обязательств построила отрезок из when", len(timeline) == 1,
          str([e.to_dict() for e in timeline]))
    if timeline:
        entry = timeline[0]
        check("длительность отрезка — объявленная, а не по умолчанию",
              entry.duration_min == 30, str(entry.duration_min))
        check("в subject времени нет вовсе — карта взяла его только из when",
              _from_subject(entry.subject) is None, entry.subject)


# ────────────────────────────────────────────────────────────────────────────
# 2. Предикат берёт время из `when`, а не из строки и не из плоских полей
# ────────────────────────────────────────────────────────────────────────────


def test_priority(reg: Registry, tmp: Path) -> None:
    print("\n[2] порядок источников: when выигрывает у subject и у day/time")
    folder = tmp / "priority"
    # `duration_of` намеренно врёт про 15 минут: настройки владельца — законный
    # источник, но объявленный блок обязан быть сильнее.
    anna, _led, _gov, guard = make_party(reg, folder, "person:anna", guard=True,
                                         duration_of={NORD: 15})
    manifest = reg.manifest(NORD)

    slot = slot_at(anna, NORD, "2026-10-12", "09:00")
    check("слот 09:00 получен от настоящего сервиса", slot is not None)
    if slot is None:
        return

    block = anna.when_from_response(NORD, slot, duration_min=120).to_dict()
    truth = datetime.fromisoformat(f"{slot['day']}T{slot['time']}")

    # Намерение, враждебное к эвристикам: в строке времени нет, а плоские поля
    # указывают НЕ ТО время (другой день и час — настоящий слот из каталога).
    payload = {"hold_id": "h-0", "name": "Анна", "subject": BLIND_SUBJECT,
               "note": BLIND_SUBJECT, "day": "2026-10-13", "time": "18:00",
               "when": block}

    entry = guard.proposed(NORD, "booking.create", payload, manifest)
    check("кандидат построен", entry is not None)
    if entry is None:
        return
    check("время начала — из when, а не из day/time намерения",
          entry.starts_at == truth, f"{entry.starts_at} ≠ {truth}")
    check("длительность — из when, а не из настроек владельца (15) и не 60",
          entry.duration_min == 120, str(entry.duration_min))
    check("место — из when (название заведения), а не 'venue-clinic-nord'",
          entry.place == block["place"], f"{entry.place} ≠ {block['place']}")

    # Доказательство от противного: уберём блок — и из того же намерения
    # выуживается ДРУГОЕ (неверное) время, то есть выигрывал действительно он.
    without = {k: v for k, v in payload.items() if k != "when"}
    fallback = guard.proposed(NORD, "booking.create", without, manifest)
    check("без when тот же payload даёт другое время — значит выигрывал when",
          fallback is not None and fallback.starts_at != truth,
          str(fallback.starts_at if fallback else None))
    check("без when длительность падает до настроек владельца (15)",
          fallback is not None and fallback.duration_min == 15,
          str(fallback.duration_min if fallback else None))

    # Намерение совсем без подсказок: ни блока, ни полей, ни даты в строке.
    bare = {"hold_id": "h-0", "name": "Анна", "subject": BLIND_SUBJECT}
    check("без when и без подсказок предикат воздерживается (None), а не гадает",
          guard.proposed(NORD, "booking.create", bare, manifest) is None)
    check("и сам предикат при этом молчит, а не блокирует",
          guard.check(NORD, "booking.create", bare, manifest) == [])

    # `role` в блоке — дорожка на карте, её больше взять негде.
    with_role = dict(payload)
    with_role["when"] = {**block, "role": "здоровье"}
    roled = guard.proposed(NORD, "booking.create", with_role, manifest)
    check("роль из when становится дорожкой кандидата",
          roled is not None and roled.role == "здоровье" and roled.track == "здоровье",
          str(roled.role if roled else None))

    # Entry.from_when — единственный путь блока в отрезок; сверим с кандидатом.
    direct = Entry.from_when("person:anna", block, subject=BLIND_SUBJECT,
                             service=NORD, verb="booking.create")
    check("Entry.from_when даёт тот же отрезок, что и предикат",
          (direct.starts_at, direct.duration_min, direct.place)
          == (entry.starts_at, entry.duration_min, entry.place),
          f"{direct.to_dict()} ≠ {entry.to_dict()}")


# ────────────────────────────────────────────────────────────────────────────
# 3. Конфликт обнаружен на основании `when` — и только его
# ────────────────────────────────────────────────────────────────────────────


def test_conflict(reg: Registry, tmp: Path) -> None:
    print("\n[3] конфликт расписания на основании when (subject слеп)")
    folder = tmp / "conflict"
    # Две клиники — чтобы у контрольной стороны был свой непроданный 09:00.
    long_anna, long_led, _, _ = make_party(reg, folder, "person:anna-long", guard=True)
    short_anna, short_led, _, _ = make_party(reg, folder, "person:anna-short", guard=True)
    nord, _, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    sued, _, _, _ = make_party(reg, folder, "venue:clinic-sued", limit=10_000.0)

    # Первое обязательство: 09:00, объявленные ДВА ЧАСА.
    first = book(long_anna, nord, NORD, "2026-10-12", "09:00", duration_min=120)
    check("первое обязательство допущено (расписание было пустым)",
          first["commitment"] is not None, str(first["error"] or first["decision"]))
    if first["commitment"] is None:
        return

    timeline = build_timeline({"person:anna-long": long_led}, place_of=PLACES)
    check("на карте ровно один отрезок, и он взят из when",
          len(timeline) == 1 and timeline[0].duration_min == 120,
          str([e.to_dict() for e in timeline]))
    check("разбор subject на этой записи не даёт ничего — опереться больше не на что",
          all(_from_subject(r.payload.get("subject", "")) is None
              for r in commitments(long_led)),
          str([r.payload.get("subject") for r in commitments(long_led)]))

    # Второе: 10:30 того же дня. Оно попадает внутрь первых двух часов.
    second = book(long_anna, nord, NORD, "2026-10-12", "10:30", duration_min=60)
    check("второе обязательство отклонено предикатом H8",
          second["commitment"] is None and not second["decision"].admitted,
          str(second["decision"]))
    check("вердикт — block, причина называет конфликт расписания",
          second["decision"].verdict == "block"
          and "конфликт расписания" in second["decision"].reason,
          str(second["decision"].reason))
    check("в причине назван именно пересекающийся отрезок (09:00–11:00)",
          "09:00" in second["decision"].reason and "11:00" in second["decision"].reason,
          second["decision"].reason)
    check("отказ записан в журнал как decision с verdict=block",
          any(r.payload.get("verdict") == "block" for r in booking_decisions(long_led)),
          str([r.payload.get("verdict") for r in booking_decisions(long_led)]))
    # Тот же вопрос, заданный предикату напрямую: намерение восстанавливаем с
    # блоком (в `payload` его кладёт сам `commit_two_party`, см. инвариант §7).
    rejected = {**second["payload"], "when": second["when"].to_dict()}
    check("предикат подтверждает конфликт вида overlap",
          [c.kind for c in long_anna.executor.governor.schedule_guard.check(
              NORD, "booking.create", rejected, reg.manifest(NORD))] == [OVERLAP],
          str(second["decision"].reason))
    check("журнал клиента цел после отказа", long_led.verify())
    check("слот 10:30 остался непроданным у СЕРВИСА",
          any(s["time"] == "10:30" for s in free_slots(long_anna, NORD, "2026-10-12")),
          str([s["time"] for s in free_slots(long_anna, NORD, "2026-10-12")]))

    # Контроль: та же пара часов, но объявлен ЧАС вместо двух — места хватает.
    ctl_first = book(short_anna, sued, SUED, "2026-10-12", "09:00", duration_min=60)
    ctl_second = book(short_anna, sued, SUED, "2026-10-12", "10:30", duration_min=60)
    check("контроль: при duration_min=60 обе брони допущены",
          ctl_first["commitment"] is not None and ctl_second["commitment"] is not None,
          f"{ctl_first['error'] or ctl_first['decision']} / "
          f"{ctl_second['error'] or ctl_second['decision']}")
    check("контроль: у стороны два обязательства, и цепь цела",
          len(commitments(short_led)) == 2 and short_led.verify())
    check("значит отказ выше вызван ровно объявленной длительностью, а не порядком броней",
          second["decision"].verdict == "block"
          and ctl_second["decision"].verdict != "block",
          f"{second['decision'].verdict} / {ctl_second['decision'].verdict}")


# ────────────────────────────────────────────────────────────────────────────
# 4. Без `when` — в точности прежнее поведение
# ────────────────────────────────────────────────────────────────────────────


def test_without_when(reg: Registry, tmp: Path) -> None:
    print("\n[4] обратная совместимость: без when всё как до этапа 18")
    folder = tmp / "legacy"
    anna, led, _gov, guard = make_party(reg, folder, "person:anna", guard=True)
    nord, nord_led, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    manifest = reg.manifest(NORD)

    slot = slot_at(anna, NORD, "2026-10-12", "09:00")
    if slot is None:
        check("слот 09:00 доступен", False)
        return
    legacy_subject = f"приём {slot['day']} {slot['time']} · {slot['specialist']}"

    deal = book(anna, nord, NORD, "2026-10-12", "09:00",
                subject=legacy_subject,
                announce_flat=(slot["day"], slot["time"]))
    check("обязательство по старому образцу оформлено", deal["commitment"] is not None,
          str(deal["error"] or deal["decision"]))
    if deal["commitment"] is None:
        return

    rec = commitments(led)[-1]
    check("в теле записи НЕТ ключа when — форма та же, что до этапа 18",
          set(rec.payload) == LEGACY_KEYS, str(sorted(rec.payload)))
    check("то же тело у второй стороны",
          set(commitments(nord_led)[-1].payload) == LEGACY_KEYS,
          str(sorted(commitments(nord_led)[-1].payload)))
    check("Commitment.when равен None, а не пустому словарю",
          deal["commitment"].when is None, str(deal["commitment"].when))
    check("обе цепи целы", led.verify() and nord_led.verify())
    check("H8 отметился пройденным, как и прежде",
          any(c.startswith("H8") for c in deal["decision"].checks),
          str(deal["decision"].checks))

    # Старая запись читается картой — через разбор subject.
    timeline = build_timeline({"person:anna": led}, place_of=PLACES)
    truth = datetime.fromisoformat(f"{slot['day']}T{slot['time']}")
    check("карта прочитала старую запись (время из subject)",
          len(timeline) == 1 and timeline[0].starts_at == truth,
          str([e.to_dict() for e in timeline]))
    check("длительность старой записи — час по умолчанию",
          timeline and timeline[0].duration_min == DEFAULT_DURATION_MIN,
          str(timeline[0].duration_min if timeline else None))

    # Деградация в предикате: плоские поля и строка по-прежнему работают.
    flat = {"hold_id": "h", "name": "Анна", "day": slot["day"], "time": slot["time"]}
    by_flat = guard.proposed(NORD, "booking.create", flat, manifest)
    check("деградация 2 (day+time) по-прежнему даёт время",
          by_flat is not None and by_flat.starts_at == truth,
          str(by_flat.starts_at if by_flat else None))
    by_text = guard.proposed(NORD, "booking.create",
                             {"hold_id": "h", "subject": legacy_subject}, manifest)
    check("деградация 4 (разбор subject) по-прежнему даёт время",
          by_text is not None and by_text.starts_at == truth,
          str(by_text.starts_at if by_text else None))

    # Смесь эпох на одной карте: старая запись (из subject) и новый кандидат
    # (из when) конфликтуют — иначе переход на §6.1 ломал бы учёт прошлого.
    mixed = {"hold_id": "h", "name": "Анна", "subject": BLIND_SUBJECT,
             "when": {"starts_at": f"{slot['day']}T09:30", "duration_min": 60,
                      "place": PLACE_NORD}}
    conflicts = guard.check(NORD, "booking.create", mixed, manifest)
    check("новый кандидат из when конфликтует со СТАРОЙ записью",
          [c.kind for c in conflicts] == [OVERLAP],
          str([(c.kind, c.message) for c in conflicts]))


# ────────────────────────────────────────────────────────────────────────────
# 5. Негодный `when` отвергается внятно и до последствий
# ────────────────────────────────────────────────────────────────────────────


#: Каждая строка: имя, блок, подстрока, которая ОБЯЗАНА быть в объяснении.
#: Третья колонка и есть «внятно»: человек должен прочитать, какое поле
#: поправить, не открывая исходник.
BAD_BLOCKS = [
    ("starts_at отсутствует", {"duration_min": 30}, "starts_at"),
    ("дата без часа", {"starts_at": "2026-10-12"}, "starts_at"),
    ("фраза вместо отметки", {"starts_at": "приём 2026-10-12 09:00"}, "starts_at"),
    ("несуществующая дата", {"starts_at": "2026-13-45T10:00"}, "starts_at"),
    ("отрицательная длительность",
     {"starts_at": "2026-10-12T09:00", "duration_min": -30}, "duration_min"),
    ("нулевая длительность",
     {"starts_at": "2026-10-12T09:00", "duration_min": 0}, "duration_min"),
    ("длительность строкой",
     {"starts_at": "2026-10-12T09:00", "duration_min": "30"}, "duration_min"),
    ("секунды вместо минут",
     {"starts_at": "2026-10-12T09:00", "duration_min": 1_800_000}, "duration_min"),
    ("дробные минуты",
     {"starts_at": "2026-10-12T09:00", "duration_min": 30.5}, "duration_min"),
    ("место числом", {"starts_at": "2026-10-12T09:00", "place": 42}, "place"),
    ("блок не объект", "2026-10-12T09:00", "when"),
]


def test_bad_when(reg: Registry, tmp: Path) -> None:
    print("\n[5] негодный when: отказ внятный и без последствий")
    folder = tmp / "bad"
    anna, led, _gov, guard = make_party(reg, folder, "person:anna", guard=True)
    nord, nord_led, _, _ = make_party(reg, folder, "venue:clinic-nord", limit=10_000.0)
    manifest = reg.manifest(NORD)

    bad_ok = True
    for name, block, needle in BAD_BLOCKS:
        try:
            normalize_when(block)
            bad_ok = False
            print(f"      ! принят негодный блок «{name}»")
        except WhenError as e:
            if needle not in str(e):
                bad_ok = False
                print(f"      ! объяснение «{name}» не называет {needle}: {e}")
    check(f"все {len(BAD_BLOCKS)} негодных блоков отвергнуты с указанием поля", bad_ok)

    slot = slot_at(anna, NORD, "2026-10-12", "09:00")
    if slot is None:
        check("слот 09:00 доступен", False)
        return
    _, hold = take_hold(anna, NORD, slot)
    check("удержание взято", hold is not None)
    if hold is None:
        return

    before = len(list(led)), len(list(nord_led))
    payload = {"hold_id": hold.hold_id, "name": "Анна", "max_money": MAX_MONEY,
               # Годная строка рядом с негодным блоком: если реализация
               # «починит» ошибку догадкой из subject, это видно сразу.
               "subject": f"приём {slot['day']} {slot['time']}"}

    raised = None
    try:
        anna.commit_two_party(NORD, "booking.create", payload, counterparty=nord,
                              hold=hold, subject=payload["subject"],
                              when={"starts_at": "2026-10-12", "duration_min": -5})
    except WhenError as e:
        raised = e
    check("commit_two_party отверг негодный блок исключением WhenError", raised is not None,
          "обязательство оформлено на непонятном времени")
    check("в объяснении названы сервис и глагол — понятно, где искать",
          raised is not None and "booking.create" in str(raised), str(raised))
    check("негодный блок НЕ подменён догадкой из годного subject",
          raised is not None and "starts_at" in str(raised), str(raised))
    check("ни одной новой записи ни у одной стороны: отказ раньше последствий",
          (len(list(led)), len(list(nord_led))) == before,
          f"{before} → {(len(list(led)), len(list(nord_led)))}")
    check("ни одного обязательства в журналах",
          not commitments(led) and not commitments(nord_led))

    # Гейт на негодном блоке тоже обязан кричать, а не воздерживаться.
    guard_raised = None
    try:
        guard.check(NORD, "booking.create", {**payload, "when": {"starts_at": "позже"}},
                    manifest)
    except WhenError as e:
        guard_raised = e
    check("ScheduleGuard на негодном блоке бросает WhenError, а не молчит",
          guard_raised is not None, "предикат воздержался при испорченном объявлении")

    act_raised = None
    try:
        anna.act(NORD, "booking.create", {**payload, "when": {"starts_at": "позже"}},
                 key="k-bad", hold=hold)
    except WhenError as e:
        act_raised = e
    check("действие через губернатора не состоялось (WhenError)", act_raised is not None)
    check("решения губернатора по этой попытке в журнале нет — до него не дошло",
          not booking_decisions(led), str([r.payload for r in booking_decisions(led)]))

    # Двойное объявление с разными значениями — тоже отказ, а не тихий выбор.
    double = None
    try:
        anna.commit_two_party(
            NORD, "booking.create",
            {**payload, "when": {"starts_at": f"{slot['day']}T09:00", "duration_min": 30}},
            counterparty=nord, hold=hold, subject=payload["subject"],
            when={"starts_at": f"{slot['day']}T15:00", "duration_min": 30})
    except WhenError as e:
        double = e
    check("время, объявленное дважды и по-разному, отвергнуто",
          double is not None and "дважды" in str(double), str(double))

    # Внешний эталон: сервис подтверждает, что ничего не продано.
    anna.release(hold)
    times = [s["time"] for s in free_slots(anna, NORD, "2026-10-12")]
    check("СЕРВИС подтверждает: слот 09:00 после отпущенного удержания снова свободен",
          "09:00" in times, str(times))

    # Контроль: тот же путь с годным блоком обязан пройти, иначе «отвергается
    # всё подряд» выглядело бы как успех пяти проверок выше.
    good = book(anna, nord, NORD, "2026-10-12", "09:00", duration_min=30)
    check("контроль: с годным when то же действие проходит",
          good["commitment"] is not None, str(good["error"] or good["decision"]))
    check("контроль: блок записан",
          good["commitment"] is not None
          and isinstance(commitments(led)[-1].payload.get("when"), dict))


# ────────────────────────────────────────────────────────────────────────────


SCENARIOS = (
    ("written", test_written, 1),
    ("priority", test_priority, 1),
    ("conflict", test_conflict, 2),
    ("legacy", test_without_when, 1),
    ("bad", test_bad_when, 1),
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_act_when_"))
    print(f"Сценариев: {len(SCENARIOS)}; у каждого свои настоящие клиники со свежими "
          f"слотами, порты подбираются от :{BASE_PORT}")
    try:
        for tag, scenario, count in SCENARIOS:
            try:
                with Venues(tmp, tag, count) as reg:
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
