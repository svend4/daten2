"""Этап 22: негодный `when` — штатный отказ губернатора, записанный в журнал (§5, §6.1).

ЧТО БЫЛО (проверено на исходном коде из HEAD)
- Со schedule_guard: губернатор бросал WhenError наружу из evaluate. Исполнитель
  к этому моменту уже записал intent, а decision не записывался: в хэш-цепи
  оставалось намерение без решения. Отказ, которого нет в журнале, для аудита
  хуже открытого отказа.
- Без schedule_guard (в том числе в шлюзе): негодный `when` вообще не проверялся.
  Без согласия это эскалация, а после подтверждения шлюз исполнял бронь с
  негодным временем. Это хуже исключения: отказ не случается, мир меняется.

ЧТО ДОЛЖНО БЫТЬ
Негодный `when` → verdict=block с причиной, называющей поле, независимо от
schedule_guard и согласия. В журнале есть и intent, и decision. Цепь цела.
Через шлюз это 200 с verdict=block, и бронь не исполняется.
Ошибка программиста (`Agent.commit_two_party` с негодным блоком) остаётся
исключением до HTTP и до согласий: это проверяет test_when.py, не этот файл.

ДИСЦИПЛИНА ПРОВЕРКИ (почему здесь нет моков сервиса)
1. Заведение — настоящий процесс `act.services.venue.server` на свободном порту.
   Манифесты — настоящие файлы из act/manifests; перевешен только base_url.
2. Журнал — настоящий файл на диске. После сценария он перечитывается заново
   (Ledger(path)), а цепь пересчитывается независимым SHA-256 через `openssl`,
   а не через hashlib проекта: сверять проект с самим собой ничего не доказывает.
3. Состояние мира проверяется СЕРВИСОМ: свободные слоты до и после отказа,
   время брони — через booking.get.
4. Порты не фиксированные: pick_port (молчит по HTTP И свободен для bind).
5. Сценарий 6 проверяет внутренний инвариант исполнителя заглушкой предиката H8,
   которая бросает WhenError. Это не измерение сервиса: отказ сервиса тут не
   проверяется, проверяется только то, что исключение не уходит мимо журнала.

Сценарии:
  1. негодный when → block, причина назвала поле, intent и decision в журнале, цепь цела;
  2. семь видов негодного when — каждый block, а не исключение; NaN — отдельно;
  3. контроль: без when — прежнее поведение (эскалация за согласием);
  4. контроль: валидный when — допуск и бронь у сервиса на объявленное время;
  5. без schedule_guard негодный when тоже block, и до согласия;
  6. страховка исполнителя: WhenError из предиката становится решением block;
  7. через шлюз-подпроцесс: 200 с verdict=block, журнал перечитан с диска.

Запуск:  python3 -m act.tests.test_governor_when
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import Agent, Budget, Executor, Governor, Ledger, Registry  # noqa: E402
from act.npp_act.calendar import WhenError  # noqa: E402
from act.npp_act.schedule_guard import ScheduleGuard  # noqa: E402

NORD = "venue-clinic-nord"
PLACE_NORD = "Клиника Норд (Гамбург)"
DAY = "2026-10-12"
MAX_MONEY = 200
#: Предмет сделки без даты: гейт не должен вытащить время из него.
BLIND_SUBJECT = "лот №7 на условиях прейскуранта"

#: Первая запись цепи ссылается на 64 нуля (§6). Записано здесь вручную, а не
#: взято из ledger.GENESIS: иначе проверка сверяла бы реализацию с собой.
GENESIS = "0" * 64

#: Порты: полоса, которой не пользуются остальные наборы (test_when — с 8661,
#: test_stock_live — с 8930). Назад курсор не отматывается.
BASE_PORT = 9501
_PORT_CURSOR = [BASE_PORT]

PASSED = 0
FAILED = 0
NOTES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


# ────────────────────────────────────────────────────────────────────────────
# Независимая сверка хэш-цепи: SHA-256 считает сторонний процесс openssl
# ────────────────────────────────────────────────────────────────────────────


def sha256_oracle(data: bytes) -> str:
    """SHA-256 командной строкой OpenSSL. Падает, если openssl не найден:
    молча перейти на hashlib значило бы самосертификацию."""
    try:
        done = subprocess.run(["openssl", "dgst", "-sha256", "-r"],
                              input=data, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"openssl недоступен — сверять хэш-цепь нечем: {e}") from e
    out = done.stdout.decode("ascii", "replace").strip().split(" ")[0]
    if done.returncode != 0 or len(out) != 64:
        raise RuntimeError("openssl вернул непонятный ответ")
    return out


def canonical(obj) -> bytes:
    """Канонический JSON по §6: sort_keys, без пробелов, без ASCII-эскейпов."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def chain_on_disk(path: Path) -> tuple[bool, str, list[dict]]:
    """Цепь пересчитана с нуля по файлу: номера, сцепление, хэш каждой строки."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    prev = GENESIS
    for i, row in enumerate(rows):
        if row["seq"] != i:
            return False, f"строка {i}: seq={row['seq']}", rows
        if row["prev"] != prev:
            return False, f"строка {i}: не сцеплена с предыдущей", rows
        digest = sha256_oracle(canonical({"seq": row["seq"], "ts": row["ts"],
                                          "kind": row["kind"], "payload": row["payload"],
                                          "prev": row["prev"]}))
        if digest != row["hash"]:
            return False, f"строка {i}: хэш не сходится с независимым подсчётом", rows
        prev = row["hash"]
    return True, f"{len(rows)} записей", rows


# ────────────────────────────────────────────────────────────────────────────
# Порты и процессы
# ────────────────────────────────────────────────────────────────────────────


def answers(url: str) -> bool:
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


def pick_port() -> int:
    """Порт, который и молчит по HTTP, и действительно свободен для bind.

    Двух проверок по отдельности мало: молчащий порт может быть занят чужим
    процессом, а успешный bind ничего не говорит о том, кто ответит на запрос.
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
    raise RuntimeError("свободных портов не нашлось")


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class Venue:
    """Настоящая клиника: отдельный процесс со своей базой. Свежая на каждый сценарий,
    потому что заведение торгует временем, и проданный слот обратно не возвращается."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.port = pick_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self._log = None

    def __enter__(self) -> "Venue":
        self.folder.mkdir(parents=True, exist_ok=True)
        log = self.folder / "venue.log"
        self._log = log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "act.services.venue.server",
             "--port", str(self.port), "--db", str(self.folder / "venue.db"), "--reset"],
            cwd=str(ROOT), stdout=self._log, stderr=self._log)
        if not wait_up(f"{self.url}/api/health"):
            tail = log.read_text(encoding="utf-8", errors="replace")[-400:]
            raise RuntimeError(f"заведение не поднялось на :{self.port}: {tail.strip()}")
        return self

    def __exit__(self, *exc) -> None:
        stop(self.proc)
        if self._log is not None:
            self._log.close()


class Gateway:
    """Шлюз рантайма подпроцессом, с перевешенным на заведение манифестом."""

    def __init__(self, folder: Path, venue_url: str):
        self.folder = folder
        self.port = pick_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.venue_url = venue_url
        self.journal = folder / "gateway.jsonl"
        self.proc: subprocess.Popen | None = None
        self._log = None

    def __enter__(self) -> "Gateway":
        self.folder.mkdir(parents=True, exist_ok=True)
        self._log = (self.folder / "gateway.log").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "act.gateway",
             "--port", str(self.port), "--manifests", str(ROOT / "act/manifests"),
             "--ledger", str(self.journal), "--budget", "300", "--owner", "person:test",
             "--rebind", f"{NORD}={self.venue_url}"],
            cwd=str(ROOT), stdout=self._log, stderr=self._log)
        if not wait_up(f"{self.url}/api/health"):
            raise RuntimeError(f"шлюз не поднялся на :{self.port}")
        return self

    def __exit__(self, *exc) -> None:
        stop(self.proc)
        if self._log is not None:
            self._log.close()


def build_registry(venue_url: str) -> Registry:
    """Настоящие манифесты; перевешен только адрес заведения."""
    reg = Registry().load_dir(ROOT / "act/manifests")
    reg.rebind(NORD, venue_url)
    return reg


def make_agent(reg: Registry, journal: Path, *, with_guard: bool,
               guard_override=None) -> tuple[Agent, Ledger]:
    """Сторона с настоящим журналом на диске и губернатором.

    Предикат H8 строится на ТОМ ЖЕ объекте журнала, в который пишет исполнитель:
    он обязан видеть то, что записано секунду назад.
    """
    led = Ledger(journal, owner="person:test")
    if guard_override is not None:
        guard = guard_override
    elif with_guard:
        guard = ScheduleGuard(led, place_of={NORD: PLACE_NORD}, capacity_hours=10.0)
    else:
        guard = None
    gov = Governor(reg, led, Budget(2000.0), schedule_guard=guard)
    return Agent("person:test", Executor(reg, gov, led)), led


# ────────────────────────────────────────────────────────────────────────────
# Состояние мира, которое сообщает СЕРВИС
# ────────────────────────────────────────────────────────────────────────────


def free_slots(agent: Agent) -> list[dict]:
    res = agent.read(NORD, "slot.list", {"day": DAY})
    return list(res.body or []) if res and res.ok else []


def hold_slot(agent: Agent, slot: dict):
    _, hold = agent.hold(NORD, "slot.hold", {"slot_id": slot["id"]})
    return hold


def attempts(led: Ledger, verb: str = "booking.create") -> list[dict]:
    """Все intent/decision по глаголу, в порядке записи."""
    return [r.payload for r in led if r.kind in ("intent", "decision")
            and r.payload.get("verb") == verb]


def kinds_since(led: Ledger, n_before: int) -> list[str]:
    return [r.kind for r in list(led)[n_before:]]


def booking_payload(hold_id: str, when=None, **extra) -> dict:
    payload = {"hold_id": hold_id, "name": "Анна Иванова", "max_money": MAX_MONEY,
               "subject": BLIND_SUBJECT}
    if when is not None:
        payload["when"] = when
    payload.update(extra)
    return payload


# ────────────────────────────────────────────────────────────────────────────
# Сценарии
# ────────────────────────────────────────────────────────────────────────────


def scenario_1_block_is_journaled(tmp: Path) -> None:
    print("\n[1] негодный when → block с причиной, intent и decision в журнале")
    folder = tmp / "s1"
    with Venue(folder / "venue") as v:
        reg = build_registry(v.url)
        anna, led = make_agent(reg, folder / "journal.jsonl", with_guard=True)
        hold = hold_slot(anna, free_slots(anna)[0])
        check("удержание взято у настоящего заведения", hold is not None)
        if hold is None:
            return

        free_before = [s["id"] for s in free_slots(anna)]
        n_before = len(led)
        # Классический случай: дата и час слиплись в фразу. До этапа 22 это
        # вылетало исключением; теперь — отказ, который записан.
        decision, result = anna.act(
            NORD, "booking.create",
            booking_payload(hold.hold_id, when={"starts_at": "приём 2026-10-12 09:00"}),
            key="bad-1", hold=hold)

        check("вердикт block, исключения не было", decision.verdict == "block",
              f"verdict={decision.verdict}")
        check("исполнения нет: result пуст", result is None)
        check("причина называет поле starts_at", "starts_at" in decision.reason,
              decision.reason)
        check("причина помечена как §6.1 — понятно, какой закон нарушен",
              "§6.1" in decision.reason, decision.reason)
        check("в журнал за попытку легли ровно intent и decision",
              kinds_since(led, n_before) == ["intent", "decision"],
              str(kinds_since(led, n_before)))
        rec_decision = [r for r in led if r.kind == "decision"][-1]
        check("decision в журнале — block с той же причиной",
              rec_decision.payload.get("verdict") == "block"
              and rec_decision.payload.get("reason") == decision.reason)
        rec_intent = [r for r in led if r.kind == "intent"][-1]
        check("intent в журнале — тот же ключ, что у попытки",
              rec_intent.payload.get("idempotency_key") == "bad-1")
        free_after = [s["id"] for s in free_slots(anna)]
        check("СЕРВИС подтверждает: состояние мира не тронуто",
              free_before == free_after, f"{free_before} → {free_after}")

        ok, detail, _ = chain_on_disk(led.path)
        check("цепь на диске пересчитана независимо и цела", ok, detail)
        check("цепь в памяти цела", led.verify() is True)

    reloaded = Ledger(folder / "journal.jsonl", owner="person:test").reload()
    check("журнал после отказа перечитан с диска", len(reloaded) == len(led),
          f"{len(reloaded)} ≠ {len(led)}")
    check("перечитанный журнал проходит verify()", reloaded.verify() is True)
    # Искать по ключу, а не по хвосту: после отказа были чтения, и каждое чтение
    # тоже пишет четыре записи (perform журналирует и то, что ничего не меняет).
    seqs = [r.seq for r in reloaded
            if r.kind == "intent" and r.payload.get("idempotency_key") == "bad-1"]
    paired = bool(seqs) and any(
        r.kind == "decision" and r.seq == seqs[0] + 1 and r.payload.get("verdict") == "block"
        for r in reloaded)
    check("на диске отказ виден как пара intent(bad-1) → decision block", paired, str(seqs))


def scenario_2_bad_variants(tmp: Path) -> None:
    print("\n[2] семь видов негодного when: каждый — block, не исключение")
    variants = [
        ("starts_at отсутствует", {"duration_min": 30}, "starts_at"),
        ("дата без часа", {"starts_at": "2026-10-12"}, "starts_at"),
        ("фраза вместо отметки", {"starts_at": "приём 2026-10-12 09:00"}, "starts_at"),
        ("несуществующая дата", {"starts_at": "2026-13-45T10:00"}, "starts_at"),
        ("отрицательная длительность",
         {"starts_at": f"{DAY}T10:30", "duration_min": -30}, "duration_min"),
        ("секунды вместо минут",
         {"starts_at": f"{DAY}T10:30", "duration_min": 1_800_000}, "duration_min"),
        ("блок — строка, не объект", f"{DAY}T10:30", "when"),
    ]
    folder = tmp / "s2"
    with Venue(folder / "venue") as v:
        reg = build_registry(v.url)
        anna, led = make_agent(reg, folder / "journal.jsonl", with_guard=True)
        hold = hold_slot(anna, free_slots(anna)[0])
        if hold is None:
            check("удержание взято", False)
            return

        all_block = True
        all_named = True
        for i, (name, when, needle) in enumerate(variants):
            try:
                decision, result = anna.act(
                    NORD, "booking.create", booking_payload(hold.hold_id, when=when),
                    key=f"var-{i}", hold=hold)
            except WhenError as e:
                check(f"«{name}»: исключение вместо решения", False, str(e))
                all_block = False
                continue
            if decision.verdict != "block" or result is not None:
                all_block = False
                print(f"      ! «{name}»: {decision.verdict}")
            if needle not in decision.reason:
                all_named = False
                print(f"      ! «{name}»: причина не называет {needle}: {decision.reason}")

        check(f"все {len(variants)} видов отвергнуты решением block", all_block)
        check("причина каждого вида называет поле, которое надо поправить", all_named)
        blocks = [p for p in attempts(led) if p.get("verdict") == "block"]
        intents = [p for p in attempts(led) if "verdict" not in p]
        check("по каждой попытке в журнале есть decision block",
              len(blocks) == len(variants), f"{len(blocks)} из {len(variants)}")
        check("по каждой попытке в журнале есть intent",
              len(intents) == len(variants), f"{len(intents)} из {len(variants)}")

        # NaN приходит из json.loads шлюза. Валидатор календаря бросает голый
        # ValueError (int(nan)), а не WhenError: отказ всё равно должен быть block.
        decision, result = anna.act(
            NORD, "booking.create",
            booking_payload(hold.hold_id, when={"starts_at": f"{DAY}T10:30",
                                                "duration_min": float("nan")}),
            key="var-nan", hold=hold)
        check("NaN в duration_min: block, а не исключение",
              decision.verdict == "block" and result is None, decision.verdict)
        if "duration_min" not in decision.reason:
            NOTES.append("NaN в duration_min: причина не называет поле, потому что "
                         "calendar.normalize_when бросает голый ValueError из int(nan). "
                         "Корень — в calendar.py; governor лишь не даёт этому стать 500.")

        ok, detail, _ = chain_on_disk(led.path)
        check("после всех отказов цепь на диске цела", ok, detail)


def scenario_3_control_without_when(tmp: Path) -> None:
    print("\n[3] контроль: без when поведение прежнее (эскалация за согласием)")
    folder = tmp / "s3"
    with Venue(folder / "venue") as v:
        reg = build_registry(v.url)
        anna, led = make_agent(reg, folder / "journal.jsonl", with_guard=True)
        hold = hold_slot(anna, free_slots(anna)[0])
        if hold is None:
            check("удержание взято", False)
            return
        n_before = len(led)
        # Без when предикат H8 воздерживается: время из subject не выводится.
        decision, result = anna.act(NORD, "booking.create",
                                    booking_payload(hold.hold_id), key="ctrl-1", hold=hold)
        check("без when — эскалация за согласием, как и раньше",
              decision.verdict == "escalate" and decision.reason.startswith("требуется подтверждение"),
              f"{decision.verdict}: {decision.reason}")
        check("без when исполнения нет", result is None)
        check("без when в журнале intent и decision", kinds_since(led, n_before) == ["intent", "decision"])
        ok, detail, _ = chain_on_disk(led.path)
        check("цепь цела", ok, detail)


def scenario_4_control_valid_when(tmp: Path) -> None:
    print("\n[4] контроль: валидный when — допуск и бронь на объявленное время")
    folder = tmp / "s4"
    with Venue(folder / "venue") as v:
        reg = build_registry(v.url)
        anna, led = make_agent(reg, folder / "journal.jsonl", with_guard=True)
        slot = free_slots(anna)[1]  # 10:30
        hold = hold_slot(anna, slot)
        if hold is None:
            check("удержание взято", False)
            return
        # Время берётся из ОТВЕТА сервиса (слот), а не из литерала теста.
        when = anna.when_from_response(NORD, slot, duration_min=30)
        anna.accept(NORD, "booking.create", "ok-1")  # согласие владельца
        decision, result = anna.act(
            NORD, "booking.create",
            booking_payload(hold.hold_id, when=when.to_dict()), key="ok-1", hold=hold)

        check("валидный when → admit", decision.verdict == "admit", decision.reason)
        check("валидный when → исполнено", result is not None and result.ok)
        check("предикат расписания пройден на объявленном времени (H8 в списке проверок)",
              "H8 расписание вмещает обязательство" in decision.checks, str(decision.checks))
        booking_no = (result.body or {}).get("booking_number") if result else None
        check("сервис выдал номер брони", bool(booking_no))
        if booking_no:
            res = anna.read(NORD, "booking.get", {"booking_number": booking_no})
            body = res.body if res and res.ok else {}
            check("СЕРВИС подтверждает: бронь на объявленный день и час",
                  body.get("day") == slot["day"] and body.get("time") == slot["time"],
                  f"{body.get('day')} {body.get('time')} ≠ {slot['day']} {slot['time']}")
        intent = [r for r in led if r.kind == "intent" and r.payload.get("idempotency_key") == "ok-1"]
        check("объявленный when записан в intent как есть",
              bool(intent) and intent[0].payload["payload"].get("when") == when.to_dict())
        ok, detail, _ = chain_on_disk(led.path)
        check("цепь цела после допуска", ok, detail)


def scenario_5_without_guard(tmp: Path) -> None:
    print("\n[5] без schedule_guard негодный when всё равно block — и до согласия")
    folder = tmp / "s5"
    with Venue(folder / "venue") as v:
        reg = build_registry(v.url)
        anna, led = make_agent(reg, folder / "journal.jsonl", with_guard=False)
        bad = {"starts_at": "позже"}

        # Без согласия раньше был бы escalate (consent=two_party): время не проверялось.
        decision, result = anna.act(NORD, "booking.create",
                                    booking_payload(None, when=bad), key="ng-1")
        check("без согласия и без guard: block, а не escalate",
              decision.verdict == "block" and result is None, f"{decision.verdict}: {decision.reason}")

        # С согласием раньше время не проверялось ни одним предикатом: решение
        # зависело бы только от S-предикатов (здесь — S4, первое взаимодействие).
        # А в шлюзе (сценарий 7 и зонд к отчёту) то же самое при согласии
        # заканчивалось исполнением брони с негодным временем.
        anna.accept(NORD, "booking.create", "ng-2")
        decision, result = anna.act(NORD, "booking.create",
                                    booking_payload(None, when=bad), key="ng-2")
        check("с согласием и без guard: тоже block, исполнения нет",
              decision.verdict == "block" and result is None, f"{decision.verdict}")
        check("в журнале нет исполнения по ng-2",
              not any(r.payload.get("idempotency_key") == "ng-2" for r in led.by_kind("execution")))
        ok, detail, _ = chain_on_disk(led.path)
        check("цепь цела", ok, detail)


class RaisingGuard:
    """Заглушка предиката H8, которая бросает WhenError.

    Проверяет только внутренний инвариант исполнителя: исключение от предиката
    не должно уйти наружу мимо журнала. Сервис здесь не измеряется."""

    def check(self, *args, **kwargs):
        raise WhenError("проверка страховки: предикат H8 бросил WhenError")

    def reason(self, conflicts):
        return ""

    def alternative(self, *args, **kwargs):
        return None


def scenario_6_executor_safety_net(tmp: Path) -> None:
    print("\n[6] страховка исполнителя: WhenError из предиката становится решением block")
    folder = tmp / "s6"
    reg = Registry().load_dir(ROOT / "act/manifests")  # сеть не нужна: исполнения не будет
    anna, led = make_agent(reg, folder / "journal.jsonl", with_guard=False,
                           guard_override=RaisingGuard())
    anna.accept(NORD, "booking.create", "sf-1")
    n_before = len(led)
    try:
        decision, result = anna.act(
            NORD, "booking.create",
            booking_payload(None, when={"starts_at": f"{DAY}T10:30", "duration_min": 30}),
            key="sf-1")
        raised = None
    except WhenError as e:
        decision, result, raised = None, None, e
    check("WhenError не вышел из perform", raised is None, str(raised))
    if decision is not None:
        check("решение block, а не исключение", decision.verdict == "block" and result is None,
              decision.verdict)
        check("причина сохранена в решении", "H8" in decision.reason, decision.reason)
    check("в журнале intent и decision — без цепи без решения",
          kinds_since(led, n_before) == ["intent", "decision"], str(kinds_since(led, n_before)))
    ok, detail, _ = chain_on_disk(led.path)
    check("цепь цела", ok, detail)


def scenario_7_gateway(tmp: Path) -> None:
    print("\n[7] через шлюз (подпроцесс): негодный when → 200 с verdict=block, не 500")
    folder = tmp / "s7"
    with Venue(folder / "venue") as v:
        with Gateway(folder / "gw", v.url) as gw:
            def post(path: str, body: dict) -> tuple[int, dict | None]:
                req = urllib.request.Request(
                    gw.url + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return r.status, json.loads(r.read())
                except urllib.error.HTTPError as e:
                    return e.code, None
                except (OSError, ValueError) as e:
                    # Разрыв соединения: исключение уронило обработчик — это и есть дефект.
                    return -1, {"transport_error": str(e)}

            def get(path: str):
                with urllib.request.urlopen(gw.url + path, timeout=10) as r:
                    return json.loads(r.read())

            # Слот берём из ответа заведения, а не из литерала: id — деталь сервиса.
            slots = json.loads(urllib.request.urlopen(v.url + "/api/slots", timeout=10).read())
            free_before = len(slots)
            target = next((s for s in slots
                           if s.get("day") == DAY and s.get("time") == "15:00"), None)
            if target is None:
                check("у заведения есть слот 15:00 для шлюза", False, str(slots))
                return
            st, held = post("/act/perform", {
                "service": NORD, "verb": "slot.hold", "payload": {"slot_id": target["id"]},
                "idempotency_key": "gw-hold"})
            hold_id = (held or {}).get("result", {}).get("body", {}).get("hold_id") if st == 200 else None
            check("удержание через шлюз допущено", st == 200 and bool(hold_id), f"{st} {held}")
            if not hold_id:
                return

            bad_cases = [
                ("фраза вместо отметки", {"starts_at": "приём 2026-10-12 09:00"}, "starts_at"),
                ("отрицательная длительность",
                 {"starts_at": f"{DAY}T15:00", "duration_min": -30}, "duration_min"),
            ]
            for i, (name, when, needle) in enumerate(bad_cases):
                st, body = post("/act/perform", {
                    "service": NORD, "verb": "booking.create",
                    "payload": {"hold_id": hold_id, "name": "Тест", "max_money": 90, "when": when},
                    "idempotency_key": f"gw-bad-{i}"})
                check(f"«{name}»: статус 200, а не 500 и не обрыв",
                      st == 200, f"статус {st}: {body}")
                if st != 200 or body is None:
                    continue
                dec = body.get("decision", {})
                check(f"«{name}»: verdict=block (без согласия — не escalate)",
                      dec.get("verdict") == "block", str(dec))
                check(f"«{name}»: причина называет поле {needle}",
                      needle in str(dec.get("reason", "")), str(dec.get("reason")))
                check(f"«{name}»: исполнения нет", body.get("executed") is False)

            with urllib.request.urlopen(gw.url + "/api/health", timeout=10) as r:
                check("после отказов шлюз жив", r.status == 200)

            ver = get("/act/ledger/verify")
            check("шлюз сам подтверждает: цепь цела", ver.get("ok") is True, str(ver))

            free_after = len(json.loads(urllib.request.urlopen(v.url + "/api/slots", timeout=10).read()))
            # slot 3 удержан, поэтому свободных стало на один меньше ровно из-за него.
            check("СЕРВИС подтверждает: отказы не тронули слоты",
                  free_after == free_before - 1, f"{free_before} → {free_after}")

        # Шлюз остановлен — журнал перечитывается с диска.
        ok, detail, rows = chain_on_disk(gw.journal)
        check("журнал шлюза на диске: цепь цела (независимый подсчёт)", ok, detail)
        reloaded = Ledger(gw.journal, owner="person:test").reload()
        check("журнал шлюза перечитан проектом и проходит verify()", reloaded.verify() is True)
        for i, _ in enumerate(bad_cases):
            key = f"gw-bad-{i}"
            seqs = [r.seq for r in reloaded if r.kind == "intent" and r.payload.get("idempotency_key") == key]
            paired = bool(seqs) and any(
                r.kind == "decision" and r.seq == seqs[0] + 1 and r.payload.get("verdict") == "block"
                for r in reloaded)
            check(f"на диске: intent {key} сразу за ним decision block", paired, str(seqs))


SCENARIOS = (
    scenario_1_block_is_journaled,
    scenario_2_bad_variants,
    scenario_3_control_without_when,
    scenario_4_control_valid_when,
    scenario_5_without_guard,
    scenario_6_executor_safety_net,
    scenario_7_gateway,
)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_when_gov_"))
    print(f"Сценариев: {len(SCENARIOS)}; у каждого свежее заведение, порты от :{BASE_PORT}")
    try:
        for scenario in SCENARIOS:
            try:
                scenario(tmp)
            except Exception as e:  # noqa: BLE001 — исключение сценария — это провал, а не конец набора
                # WhenError из губернатора — ровно тот дефект, который этот набор
                # ловит: провал должен быть назван, а остальные сценарии — идти дальше.
                check(f"сценарий «{scenario.__name__}» выполнен без исключения", False,
                      f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if NOTES:
        print("\nЗаметки (не провалы, а известные пробелы):")
        for note in NOTES:
            print(f"  · {note}")
    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
