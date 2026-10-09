"""Проверка измерителя профиля — против НАСТОЯЩЕГО сервиса, поднятого подпроцессом.

Дисциплина та же, что во всех наборах каталога act/, и здесь она особенно
уместна: модуль, который существует ради борьбы с самосертификацией, не вправе
проверяться моком. Мок, написанный под те же допущения, что и проба, ответил бы
пробе именно то, чего она ждёт, — и набор был бы зелёным, ничего не доказывая.
Ровно так устроен `plugin-marketplace` в daten2: 14/14 зелёных и отвергнутые
настоящие бэкенды.

Поэтому здесь поднимается `act.services.venue.server` — живой сервис с
обратимыми глаголами (`slot.hold`/`slot.release`), необратимым обязательством
(`booking.create`) и объявленной идемпотентностью. Каждая проверка идёт по сети.

Два места, где подложено заведомо ложное ЗАЯВЛЕНИЕ (но не поддельный сервис):

  · манифест с глаголом `slot.audit`, маршрута которого у сервиса нет —
    так проверяется, что проба находит объявленный, но не реализованный
    глагол. Доктором правится манифест, то есть ровно та сторона, недоверие
    к которой и есть смысл модуля;
  · блоки `level_profile` — приукрашенный и скромный — чтобы `compare`
    показал, что направления расхождения он различает.

Запуск:  python3 -m act.tests.test_prober
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act.manifest import load_manifest, parse_manifest  # noqa: E402
from act.npp_act.profile import parse_level_profile  # noqa: E402
from act.npp_act.prober import (  # noqa: E402
    CONCURRENCY, CONTRACT, EMBELLISHED, IDEMPOTENCY, LATENCY, MODEST, PROBES, STOCK,
    UNVERIFIABLE, Prober, ProbeError, _fresh_key, _spec_base, check_shape, compare,
    embellishments, measure, report,
)

VENUE_MANIFEST = ROOT / "act/manifests/venue.act.json"
FLOWER_MANIFEST = ROOT / "act/manifests/flower-shop.act.json"
LEVEL1_MANIFEST = ROOT / "act/manifests/levels/level1.act.json"

PASSED = 0
FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


# ────────────────────────────────────────────────────────────────────────────
# Живой сервис: один свежий процесс на фазу
# ────────────────────────────────────────────────────────────────────────────

def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.6):
            return True
    except Exception:
        return False


def wait_up(url: str, attempts: int = 150) -> bool:
    for _ in range(attempts):
        if answers(url):
            return True
        time.sleep(0.1)
    return False


BASE_PORT = 8251
_PORT_CURSOR = [BASE_PORT]


def pick_port() -> int:
    """Найти порт, который и молчит по HTTP, и действительно свободен для bind.

    Двух проверок по отдельности мало: молчащий порт может держать чужой
    процесс, не отвечающий на HTTP, а успешный bind ничего не говорит о том,
    кто ответит на следующий запрос.

    Фиксированный порт здесь — не мелочь, а дефект того самого класса, против
    которого построен весь проект. С жёстким :8251 чужой сервис, оставшийся от
    постороннего прогона, отвечал на /api/health, тест считал его своим и мерил
    ЧУЖИЕ слоты. Измеритель, молча измеряющий не тот объект, хуже отсутствующего:
    он выдаёт зелёный отчёт о системе, которой не касался.
    """
    while _PORT_CURSOR[0] < BASE_PORT + 400:
        port = _PORT_CURSOR[0]
        _PORT_CURSOR[0] += 1
        if answers(f"http://127.0.0.1:{port}/api/health"):
            continue
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("свободный порт не найден")


class Venue:
    """Свежий сервис заведения на своём порту и своей базе.

    Отдельный процесс на каждую фазу — не аккуратность, а необходимость:
    `booking.create` необратим и съедает слот, а пробе конкурентности нужны
    свободные цели. Фазы, делящие одну базу, мерили бы последствия друг друга.
    """

    def __init__(self, port: int | None, tag: str) -> None:
        self.port = port or pick_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.db = Path(tempfile.gettempdir()) / f"npp_prober_{tag}.db"
        self.proc: subprocess.Popen | None = None
        self.err = Path(tempfile.gettempdir()) / f"npp_prober_{tag}.err"

    def __enter__(self) -> "Venue":
        if self.db.exists():
            self.db.unlink()
        with self.err.open("wb") as errfile:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "act.services.venue.server",
                 "--port", str(self.port), "--db", str(self.db), "--reset"],
                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=errfile,
            )
        if not wait_up(f"{self.base}/api/health"):
            tail = self.err.read_text(errors="replace")[-400:] if self.err.exists() else ""
            raise RuntimeError(
                f"сервис заведения не поднялся на :{self.port} "
                f"(код выхода {self.proc.poll()}): {tail}"
            )
        # Сервис обязан быть НАШИМ: свежая база отдаёт ровно пять свободных
        # слотов. Чужой процесс на том же порту этой проверки не пройдёт.
        with urllib.request.urlopen(f"{self.base}/api/slots", timeout=2) as r:
            slots = json.loads(r.read())
        if len(slots) != 5:
            raise RuntimeError(
                f"на :{self.port} отвечает не наш сервис: свободных слотов "
                f"{len(slots)}, ожидалось 5 (свежая база)"
            )
        return self

    def __exit__(self, *exc) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    # --- прямой HTTP теста: независимая проверка, а не вера пробе ---

    def get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def post(self, path: str, body: dict, key: str | None = None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))

    def free_slots(self) -> list[int]:
        return [row["id"] for row in self.get("/api/slots")[1]]


# ────────────────────────────────────────────────────────────────────────────
# Подложные ЗАЯВЛЕНИЯ (сервис при этом настоящий)
# ────────────────────────────────────────────────────────────────────────────

#: Глагол, которого у сервиса нет. Форма законная — чтобы манифест прошёл
#: валидатор: ложь должна быть в ПОВЕДЕНИИ, а не в синтаксисе, иначе её поймал
#: бы `parse_manifest`, и пробе было бы нечего ловить.
PHANTOM_VERB = {
    "id": "slot.audit",
    "title": "Аудит расписания",
    "description": "Глагол объявлен, но маршрута у сервиса нет — это и проверяем.",
    "effect": "read",
    "reversible": False,
    "cost": {"money": 0, "time_s": 0.1},
    "consent": "none",
    "binding": {"protocol": "http", "method": "GET", "path": "/api/slots/audit"},
    "input": {},
    "output": {"audited": "boolean"},
}


def _profile_block(**over) -> dict:
    base = {
        "level": 4,
        "stack": "http.server + sqlite3",
        "language": "python",
        "storage": "sqlite",
        "weight": "minimal",
        "runtime_units": 1,
        "transactional": True,
        "stock_checked": False,
        "concurrency_safe": False,
        "concurrency_evidence": "not_measured",
        "contract_conformance": {"passed": 6, "total": 6},
        "missing_verbs": [],
        "features": {"offline_capable": True},
    }
    base.update(over)
    return base


def doctored_manifest(path: Path, profile: dict) -> Path:
    """Настоящий манифест заведения + фантомный глагол + заданный level_profile."""
    raw = json.loads(VENUE_MANIFEST.read_text(encoding="utf-8"))
    raw["capabilities"] = raw["capabilities"] + [dict(PHANTOM_VERB)]
    raw["level_profile"] = profile
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ────────────────────────────────────────────────────────────────────────────
# 1. Сверка формы ответа — на настоящих схемах настоящих манифестов
# ────────────────────────────────────────────────────────────────────────────

def test_shape() -> None:
    print("\n[1] сверка формы ответа с объявленной output-схемой")
    venue = load_manifest(VENUE_MANIFEST)

    slot_list = venue.verb("slot.list").output
    ok, problems = check_shape(slot_list, [{"id": 1, "day": "2026-10-12"}])
    check("схема {\"\": array} принимает массив", ok, str(problems))
    ok, problems = check_shape(slot_list, {"slots": []})
    check("та же схема отвергает конверт вместо массива", not ok and problems)

    booking = venue.verb("booking.create").output
    real = {"booking_number": "ab12", "total": 45.0, "currency": "EUR",
            "status": "confirmed"}
    ok, problems = check_shape(booking, real)
    check("booking.create: настоящая форма ответа принята", ok, str(problems))
    check("лишние поля сверх схемы не считаются нарушением", ok,
          "в ответе есть 'status', которого нет в output")

    ok, problems = check_shape(booking, {"total": 45.0, "currency": "EUR"})
    check("пропущенное объявленное поле — нарушение",
          not ok and any("booking_number" in p for p in problems), str(problems))

    ok, problems = check_shape(booking, {**real, "total": "45"})
    check("число, пришедшее строкой, — нарушение",
          not ok and any("total" in p for p in problems), str(problems))

    ok, _ = check_shape({"n": "integer"}, {"n": True})
    check("boolean не выдаёт себя за число", not ok)
    ok, _ = check_shape({"n": "number"}, {"n": 3})
    check("целое годится под 'number'", ok)

    ok, _ = check_shape(venue.verb("booking.get").output, {"booking_number": None,
                                                           "day": "x", "time": "y"})
    check("null в обязательном поле — нарушение", not ok)

    # Необязательность читается из настоящих input-схем манифеста.
    note = venue.verb("booking.create").input["note"]
    check("'string?' в настоящем манифесте разобрано как необязательное",
          _spec_base(note) == ("string", True), str(_spec_base(note)))
    check("'array of slot' разобрано как массив",
          _spec_base(slot_list[""])[0] == "array", str(_spec_base(slot_list[""])))

    ok, _ = check_shape({"x": "string?"}, {})
    check("отсутствие необязательного поля нарушением не считается", ok)


# ────────────────────────────────────────────────────────────────────────────
# 2. Запреты самой пробы
# ────────────────────────────────────────────────────────────────────────────

def test_guards() -> None:
    print("\n[2] что проба себе запрещает")
    venue = load_manifest(VENUE_MANIFEST)

    try:
        Prober(venue, max_effect="destroy")
        check("effect='destroy' пробовать запрещено", False, "исключения не было")
    except ProbeError as e:
        check("effect='destroy' пробовать запрещено", "destroy" in str(e))

    try:
        Prober(venue, max_effect="wat")
        check("неизвестный max_effect отвергнут", False, "исключения не было")
    except ProbeError:
        check("неизвестный max_effect отвергнут", True)

    p = Prober(venue, base_url="http://127.0.0.1:1", max_calls=0)
    try:
        p._invoke(venue.verb("slot.list"), {})
        check("лимит вызовов останавливает пробу", False, "исключения не было")
    except ProbeError as e:
        check("лимит вызовов останавливает пробу", "лимит" in str(e))

    check("ключ идемпотентности выдаётся только объявившему глаголу",
          _fresh_key(venue.verb("slot.list")) is None
          and isinstance(_fresh_key(venue.verb("booking.create")), str))

    # money за порогом по умолчанию: пробовать деньги без явного разрешения нельзя.
    allowed = {c.id for c in Prober(venue)._allowed()}
    check("по умолчанию допущены глаголы не тяжелее commit",
          allowed == set(venue.capabilities), str(allowed))
    reserve_only = {c.id for c in Prober(venue, max_effect="reserve")._allowed()}
    check("max_effect='reserve' не допускает booking.create",
          "booking.create" not in reserve_only and "slot.hold" in reserve_only,
          str(reserve_only))


def test_dead_service() -> None:
    print("\n[3] мёртвый сервис — это отказ пробы, а не нулевой профиль")
    try:
        measure(VENUE_MANIFEST, base_url="http://127.0.0.1:9", repeats=1, concurrency=2)
        check("измерение недоступного сервиса отказывает", False, "исключения не было")
    except ProbeError as e:
        check("измерение недоступного сервиса отказывает", "недоступен" in str(e), str(e))


# ────────────────────────────────────────────────────────────────────────────
# 4. Пробы по отдельности против живого сервиса
# ────────────────────────────────────────────────────────────────────────────

def test_probes_live(venue: Venue) -> None:
    print("\n[4] пробы против живого сервиса заведения")
    manifest = load_manifest(VENUE_MANIFEST)
    prober = Prober(manifest, base_url=venue.base)

    # --- 4a. конкурентность: первой, пока слоты не израсходованы ---
    before = venue.free_slots()
    conc = prober.concurrency_probe(n=5)
    after = venue.free_slots()

    check("проба конкурентности применима", conc.applicable, conc.evidence)
    check("пробовала обратимым глаголом", conc.data.get("verb") == "slot.hold",
          str(conc.data.get("verb")))
    check("варьировала ручку слота", conc.data.get("vary") == "slot_id",
          str(conc.data.get("vary")))
    dist, cont = conc.data["distinct"], conc.data["contested"]
    check("послала не меньше двух одновременных обязательств", dist["sent"] >= 2,
          str(dist))
    check("успехов не больше, чем послано", dist["ok"] <= dist["sent"], str(dist))
    check("вердикт concurrency_safe вытекает из наблюдения",
          conc.ok == (dist["ok"] == dist["sent"]), f"{conc.ok} при {dist}")
    check("на одну цель хотя бы один успех", cont["ok"] >= 1, str(cont))
    check("вердикт взаимного исключения вытекает из наблюдения",
          conc.data["mutual_exclusion"] == (cont["ok"] == 1), str(cont))
    # Уборка — часть пробы. Но под параллелью живой сервис иногда обрывает
    # соединение или отдаёт 201 с ручкой, которой в базе нет; отпустить такое
    # удержание нечем. Поэтому требование к пробе формулируется строго: либо
    # вернула цель в свободные, либо НАЗВАЛА её незакрытой. Молча потерянный
    # слот — единственное, что запрещено.
    sweep = conc.data["cleanup"]
    leaked = sweep.get("leaked", [])
    check("каждая незакрытая цель посчитана самой пробой",
          sorted(set(after) | set(leaked)) == sorted(before),
          f"было {before}, стало {after}, заявлено незакрытыми {leaked}")
    check("вердикт об уборке согласован с её итогом",
          sweep["clean"] == (not sweep["failed"] and not leaked), str(sweep))
    check("уборка шла обратным глаголом из манифеста",
          "slot.release" in conc.evidence, conc.evidence)
    check("при незакрытых целях названа причина и самоистечение",
          not leaked or ("ОСТАЛОСЬ УДЕРЖАННЫМИ" in conc.evidence
                         and "expires_s" in conc.evidence), conc.evidence)
    check("сбои обратных вызовов не замолчаны",
          not sweep["failed"] or "обратный вызов не удался" in conc.evidence,
          conc.evidence)

    # --- 4b. контракт ---
    contract = prober.contract_probe()
    check("проба контракта применима", contract.applicable)
    check("вызваны все пять объявленных глаголов", contract.data["total"] == 5,
          f"{contract.data['total']}, пропущено {contract.data['skipped']}")
    check("пропущенных не осталось", not contract.data["skipped"],
          str(contract.data["skipped"]))
    check("живой сервис соответствует своей же схеме: 5/5",
          (contract.data["passed"], contract.data["total"]) == (5, 5),
          str(contract.data["verbs"]))
    check("у каждого глагола записан HTTP-код",
          all("status" in v for v in contract.data["verbs"].values()))
    get_booking = contract.data["verbs"].get("booking.get", {})
    check("booking.get добрался до настоящей брони (ручка добыта законно)",
          get_booking.get("status") == 200, str(get_booking))
    hold = contract.data["verbs"].get("slot.hold", {})
    check("slot.hold вернул объявленную форму", hold.get("shape_ok") is True, str(hold))
    check("отсутствующих маршрутов не найдено", contract.data["missing_verbs"] == [],
          str(contract.data["missing_verbs"]))
    check("в наблюдении названо, сколько глаголов вызвано",
          "вызвано 5 из 5" in contract.evidence, contract.evidence)

    # --- 4c. идемпотентность ---
    idem = prober.idempotency_probe()
    check("проба идемпотентности применима", idem.applicable, idem.evidence)
    verbs = idem.data["verbs"]
    check("проверены оба объявивших ключ глагола",
          set(verbs) == {"slot.hold", "booking.create"}, str(list(verbs)))
    booking = verbs.get("booking.create", {})
    check("бронь идемпотентна: повтор вернул ту же ручку",
          booking.get("verdict") == "replay", str(booking))
    check("повтор брони отвечает 2xx, а не ошибкой",
          200 <= booking.get("second_status", 0) < 300, str(booking))
    held = verbs.get("slot.hold", {})
    check("slot.hold объявил ключ, но повтор им не пользуется (находка пробы)",
          held.get("verdict") == "rejected", str(held))
    check("отказ повтора отличён от двойного исполнения",
          idem.data["rejected"] == ["slot.hold"] and idem.data["duplicated"] == [],
          str(idem.data))
    check("двойного обязательства сервис не создал",
          idem.data["double_execution"] is False, str(idem.data))
    check("общий вердикт — не идемпотентен, раз один из двух не держит",
          idem.ok is False, str(idem.ok))

    # Независимая перепроверка вердикта пробы СВОИМ запросом по сети:
    # верить данным пробы о пробе — та же самосертификация.
    st, slots = venue.get("/api/slots")
    free = [r["id"] for r in slots]
    st, h = venue.post("/api/holds", {"slot_id": free[0]})
    key = "test-own-key"
    st1, b1 = venue.post("/api/bookings", {"hold_id": h["hold_id"], "name": "тест"}, key)
    st2, b2 = venue.post("/api/bookings", {"hold_id": h["hold_id"], "name": "тест"}, key)
    check("идемпотентность подтверждена независимым запросом теста",
          st1 == 201 and st2 == 200
          and b1["booking_number"] == b2["booking_number"], f"{st1}/{st2} {b1} {b2}")

    # --- 4d. склад: неприменимость — не отрицательный вердикт ---
    stock = prober.stock_probe()
    check("складская проба объявлена неприменимой к venue", not stock.applicable)
    check("вердикта о складе не выдумано", stock.ok is None, str(stock.ok))
    check("в наблюдении сказано, почему неприменима",
          "venue" in stock.evidence and "выдуман" in stock.evidence, stock.evidence)

    # --- 4e. задержка ---
    lat = prober.latency_probe(repeats=5)
    check("проба задержки применима", lat.applicable, lat.evidence)
    check("p50 не больше p95", lat.data["p50_ms"] <= lat.data["p95_ms"], str(lat.data))
    check("замеров ровно столько, сколько повторов на читающих глаголах",
          lat.data["samples"] >= 5, str(lat.data))

    prober.cleanup()


# ────────────────────────────────────────────────────────────────────────────
# 5. Выбор цели складской пробы — на настоящих vendor-манифестах
# ────────────────────────────────────────────────────────────────────────────

def test_stock_target() -> None:
    print("\n[5] складская проба: выбор цели по настоящим vendor-манифестам")
    for path, label in ((FLOWER_MANIFEST, "flower-shop"), (LEVEL1_MANIFEST, "level1-php")):
        manifest = load_manifest(path)
        target = Prober(manifest)._stock_target()
        check(f"{label}: цель складской пробы найдена", target is not None)
        if target:
            cap, kind, field = target
            check(f"{label}: целью выбран обязывающий глагол заказа",
                  cap.id == "order.create" and cap.is_committing, cap.id)
            check(f"{label}: количество опознано как позиции заказа",
                  (kind, field) == ("items", "items"), f"{kind}/{field}")

    venue = load_manifest(VENUE_MANIFEST)
    check("venue: цели складской пробы нет — он торгует временем",
          Prober(venue)._stock_target() is None)


# ────────────────────────────────────────────────────────────────────────────
# 6. measure(): профиль, у каждого признака — наблюдение
# ────────────────────────────────────────────────────────────────────────────

def test_measure(venue: Venue) -> None:
    print("\n[6] measure(): собранный профиль")
    m = measure(VENUE_MANIFEST, base_url=venue.base, concurrency=4, repeats=5)

    check("сервис в профиле — из манифеста", m.service == "venue-clinic-nord", m.service)
    check("база — та, по которой измеряли", m.base_url == venue.base, m.base_url)
    check("профиль сервиса сохранён", m.service_profile == "venue", m.service_profile)
    try:
        datetime.fromisoformat(m.measured_at.replace("Z", "+00:00"))
        check("measured_at — разбираемая отметка времени", True)
    except ValueError:
        check("measured_at — разбираемая отметка времени", False, m.measured_at)

    check("признаков собрано не меньше десяти", len(m.features) >= 10,
          str(sorted(m.features)))
    missing_ev = [n for n, f in m.features.items() if not f.evidence.strip()]
    check("у КАЖДОГО признака есть наблюдение", not missing_ev, str(missing_ev))
    bad_probe = [n for n, f in m.features.items() if f.probe not in PROBES]
    check("каждый признак помечен пробой, которая его дала", not bad_probe,
          str(bad_probe))

    names = {p.name for p in m.probes}
    check("проведены все пять проб", names == set(PROBES), str(names))
    check("пробу можно найти по имени",
          m.probe(CONTRACT) is not None and m.probe(STOCK).applicable is False
          and m.probe("нет такой") is None)
    check("каждый признак отнесён к той пробе, которая его дала",
          m.feature("contract_conformance").probe == CONTRACT
          and m.feature("latency_p50_ms").probe == LATENCY
          and m.feature("idempotent").probe == IDEMPOTENCY
          and m.feature("concurrency_safe").probe == CONCURRENCY
          and m.feature("stock_checked").probe == STOCK)
    check("contract_conformance измерен 5/5", m.conformance == (5, 5), str(m.conformance))
    check("доля соответствия считается", abs(m.conformance_ratio - 1.0) < 1e-9)
    check("нереализованных глаголов не найдено", m.value("missing_verbs") == [],
          str(m.value("missing_verbs")))
    check("склад: вердикта нет, и это не False", m.value("stock_checked") is None)
    check("идемпотентность измерена как ложная (slot.hold)",
          m.value("idempotent") is False, str(m.value("idempotent")))
    check("объявившие ключ глаголы перечислены",
          m.declared_idempotent_verbs == frozenset({"slot.hold", "booking.create"}),
          str(m.declared_idempotent_verbs))
    check("задержка измерена", isinstance(m.value("latency_p50_ms"), (int, float)))
    swept = m.feature("probe_cleaned_up")
    check("проба либо убрала за собой, либо назвала, что осталось",
          swept.value is True or "осталось удержанными" in swept.evidence,
          str(swept))
    check("в наблюдении об уборке есть и число вызовов, и расход",
          "обратных вызовов" in swept.evidence
          and "необратимо израсходовано" in swept.evidence, swept.evidence)
    check("необратимый расход признан, а не замолчан",
          any("booking.create" in s for s in m.spent), str(m.spent))
    check("число вызовов учтено", m.calls > 0, str(m.calls))

    blob = json.dumps(m.to_json(), ensure_ascii=False)
    back = json.loads(blob)
    check("профиль сериализуется в JSON",
          back["service"] == m.service and "features" in back and "probes" in back)
    check("в JSON у признака есть и значение, и наблюдение",
          all({"value", "evidence", "probe"} <= set(v)
              for v in back["features"].values()))
    check("отчёт человеку содержит сервис и контракт",
          m.service in report(m) and "контракт" in report(m))
    return m


# ────────────────────────────────────────────────────────────────────────────
# 7. compare(): приукрашивание против скромности
# ────────────────────────────────────────────────────────────────────────────

def test_compare(venue: Venue, tmp: Path) -> None:
    print("\n[7] compare(): в какую сторону соврал профиль")

    # Манифест с фантомным глаголом: сервис настоящий, лжёт ЗАЯВЛЕНИЕ.
    flattering = doctored_manifest(
        tmp / "venue-flattering.act.json",
        _profile_block(stock_checked=True, concurrency_safe=True,
                       contract_conformance={"passed": 6, "total": 6},
                       missing_verbs=[]),
    )
    raw = json.loads(flattering.read_text(encoding="utf-8"))
    m = measure(parse_manifest(raw), base_url=venue.base, concurrency=4, repeats=3)

    check("фантомный глагол объявлен в доработанном манифесте",
          "slot.audit" in {c.id for c in parse_manifest(raw)},)
    check("проба нашла отсутствующий маршрут",
          m.value("missing_verbs") == ["slot.audit"], str(m.value("missing_verbs")))
    check("соответствие просело именно на фантомном глаголе",
          m.conformance == (5, 6), str(m.conformance))

    declared = parse_level_profile(raw)
    gaps = compare(declared, m)
    check("расхождения найдены", bool(gaps), "их нет")
    by_field = {d.field: d for d in gaps}

    check("умолчание о нереализованном глаголе — приукрашивание",
          by_field["missing_verbs"].direction == EMBELLISHED
          and by_field["missing_verbs"].severity == "critical",
          str(by_field.get("missing_verbs")))
    check("в расхождении назван именно фантомный глагол",
          "slot.audit" in by_field["missing_verbs"].detail,
          by_field["missing_verbs"].detail)
    check("завышенное соответствие контракту — приукрашивание",
          by_field["contract_conformance"].direction == EMBELLISHED,
          str(by_field.get("contract_conformance")))
    check("заявленное 6/6 против измеренного 5/6",
          by_field["contract_conformance"].declared == "6/6"
          and by_field["contract_conformance"].measured == "5/6",
          str(by_field["contract_conformance"]))
    check("ложь об идемпотентности поймана по манифесту",
          by_field["idempotency"].direction == EMBELLISHED
          and "slot.hold" in by_field["idempotency"].detail,
          str(by_field.get("idempotency")))
    check("непроверяемое положительное заявление о складе помечено особо",
          by_field["stock_checked"].direction == UNVERIFIABLE
          and by_field["stock_checked"].severity == "info",
          str(by_field.get("stock_checked")))
    check("непроверяемое НЕ записано в приукрашивания",
          all(d.field != "stock_checked" for d in embellishments(gaps)))

    lies = embellishments(gaps)
    check("приукрашиваний не меньше трёх", len(lies) >= 3, str([d.field for d in lies]))
    check("все приукрашивания помечены как хуже заявленного",
          all(d.worse_than_declared for d in lies))
    check("приукрашивания идут первыми в списке",
          [d.direction for d in gaps][:len(lies)] == [EMBELLISHED] * len(lies),
          str([d.direction for d in gaps]))
    check("у каждого расхождения есть и объяснение, и наблюдение",
          all(d.detail.strip() and d.evidence.strip() for d in gaps),
          str([d.field for d in gaps if not d.evidence.strip()]))
    check("расхождение сериализуется",
          {"field", "direction", "severity", "detail"} <= set(gaps[0].to_json()))
    check("человекочитаемая строка называет направление",
          "приукрашено" in lies[0].human(), lies[0].human())
    # Если параллель и правда просела, в объяснении обязана быть названа цена
    # заявления: оно сделано с concurrency_evidence='not_measured'.
    conc_gap = by_field.get("concurrency_safe")
    check("приукрашивание о параллели объясняет, что его не измеряли",
          conc_gap is None or conc_gap.direction != EMBELLISHED
          or "not_measured" in conc_gap.detail,
          str(conc_gap))

    # Тот же измеренный профиль против СКРОМНОГО заявления.
    modest_raw = json.loads(doctored_manifest(
        tmp / "venue-modest.act.json",
        _profile_block(stock_checked=False, concurrency_safe=False,
                       contract_conformance={"passed": 1, "total": 6},
                       missing_verbs=["booking.get", "slot.audit"]),
    ).read_text(encoding="utf-8"))
    modest_gaps = compare(parse_level_profile(modest_raw), m)
    modest_by_field = {d.field: d for d in modest_gaps}

    check("занижённое соответствие — скромность, а не ложь",
          modest_by_field["contract_conformance"].direction == MODEST,
          str(modest_by_field.get("contract_conformance")))
    check("признанный, но работающий глагол — скромность",
          modest_by_field["missing_verbs"].direction == MODEST
          and "booking.get" in modest_by_field["missing_verbs"].detail,
          str(modest_by_field.get("missing_verbs")))
    check("скромность не считается приукрашиванием",
          all(d.field not in ("contract_conformance", "missing_verbs")
              for d in embellishments(modest_gaps)),
          str([d.field for d in embellishments(modest_gaps)]))
    check("скромность помечена как info", modest_by_field["missing_verbs"].severity == "info")
    check("одно и то же поле меняет направление вместе с заявлением",
          by_field["missing_verbs"].direction != modest_by_field["missing_verbs"].direction)
    check("ложь об идемпотентности видна при любом профиле уровня",
          modest_by_field.get("idempotency", None) is not None
          and modest_by_field["idempotency"].direction == EMBELLISHED)

    # Совпадение — отсутствие расхождений по сверяемым полям профиля.
    honest_raw = json.loads(doctored_manifest(
        tmp / "venue-honest.act.json",
        _profile_block(stock_checked=False,
                       concurrency_safe=bool(m.value("concurrency_safe")),
                       concurrency_evidence="measured",
                       contract_conformance={"passed": 5, "total": 6},
                       missing_verbs=["slot.audit"]),
    ).read_text(encoding="utf-8"))
    honest_gaps = compare(parse_level_profile(honest_raw), m)
    check("честный профиль не даёт расхождений по своим полям",
          all(d.field == "idempotency" for d in honest_gaps),
          str([(d.field, d.direction) for d in honest_gaps]))
    check("отчёт со сверкой называет число приукрашиваний",
          "приукрашиваний" in report(m, parse_level_profile(raw)))
    return flattering


# ────────────────────────────────────────────────────────────────────────────
# 8. CLI
# ────────────────────────────────────────────────────────────────────────────

def run_cli(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run([sys.executable, "-m", "act.npp_act.prober", *args],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout, proc.stderr


def test_cli(venue: Venue, flattering: Path) -> None:
    print("\n[8] CLI")
    code, out, err = run_cli(["--manifest", str(VENUE_MANIFEST),
                              "--base-url", venue.base, "--json",
                              "--concurrency", "3", "--repeats", "3"])
    check("честный манифест без level_profile → код 0", code == 0, err[-300:])
    try:
        payload = json.loads(out)
        check("вывод --json разбирается", True)
        check("в выводе есть измеренный профиль",
              payload["measured"]["service"] == "venue-clinic-nord")
        check("в выводе есть наблюдения признаков",
              all(v["evidence"] for v in payload["measured"]["features"].values()))
        check("без заявленного профиля сверки нет", payload["discrepancies"] == [])
    except json.JSONDecodeError as e:
        check("вывод --json разбирается", False, str(e))

    code, out, err = run_cli(["--manifest", str(flattering),
                              "--base-url", venue.base,
                              "--concurrency", "3", "--repeats", "3"])
    check("найденное приукрашивание даёт ненулевой код", code == 2, f"код {code}")
    check("в отчёте названо расхождение", "приукрашено" in out, out[-400:])

    code, out, err = run_cli(["--manifest", str(VENUE_MANIFEST),
                              "--base-url", "http://127.0.0.1:9", "--repeats", "1",
                              "--concurrency", "2"])
    check("мёртвый сервис даёт код 1 и сообщение в stderr",
          code == 1 and "проба не состоялась" in err, f"{code} {err[-200:]}")

    code, out, err = run_cli(["--manifest", str(VENUE_MANIFEST),
                              "--base-url", venue.base, "--max-effect", "destroy"])
    check("destroy не принимается даже из CLI", code != 0, f"код {code}")


# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_prober_"))
    try:
        test_shape()
        test_guards()
        test_dead_service()
        test_stock_target()

        with Venue(None, "probes") as v:
            print(f"\nсервис заведения поднят на :{v.port}")
            test_probes_live(v)
        with Venue(None, "measure") as v:
            test_measure(v)
        with Venue(None, "compare") as v:
            flattering = test_compare(v, tmp)
        with Venue(None, "cli") as v:
            test_cli(v, flattering)
    except Exception as e:  # поднять сервис не удалось — это тоже результат
        print(f"\n✗ набор прерван: {type(e).__name__}: {e}")
        return 1

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
