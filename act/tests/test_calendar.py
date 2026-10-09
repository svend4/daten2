"""Тесты карты обязательств: журналы настоящие, конфликты настоящие.

Дисциплина та же, что в test_act.py, и по той же причине: модуль не вправе
проверять себя против мока, написанного под его же допущения. Поэтому здесь
поднимаются ДВА настоящих экземпляра сервиса заведения на разных портах —
«Клиника Норд (Гамбург)» и «Клиника Зюд (Мюнхен)», — и Анна бронирует в них
время по настоящему HTTP, через губернатора и двустороннее обязательство.

Ни одна запись журнала в этом файле не пишется руками: все обязательства
появляются как исход реального вызова `booking.create`, а время и деньги карта
достаёт из того, что сервис действительно ответил. Два экземпляра одного
сервиса — не трюк: именно так и выглядит «невозможная фигура» в жизни, когда
человек подписался на один и тот же час в двух разных городах.

Запуск:  python3 -m act.tests.test_calendar
"""

from __future__ import annotations

import json
import shutil
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
    CAPACITY, OVERLAP, TRAVEL, Entry, TravelMatrix, build_timeline,
    detect_conflicts, explain, governor_predicate, load_timeline, summary,
    would_conflict,
)
from act.npp_act.manifest import parse_manifest  # noqa: E402

PASSED = 0
FAILED = 0

NORD = "venue-clinic-nord"
SUED = "venue-clinic-sued"
PLACE_NORD = "Клиника Норд (Гамбург)"
PLACE_SUED = "Клиника Зюд (Мюнхен)"
PLACES = {NORD: PLACE_NORD, SUED: PLACE_SUED}

#: Между Гамбургом и Мюнхеном четыре часа дороги. Это не параметр для красоты:
#: именно он превращает законную пару броней в неисполнимое расписание.
TRAVEL_HH_MUC = TravelMatrix({(PLACE_NORD, PLACE_SUED): 240})


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def wait_up(url: str, attempts: int = 50) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


# ────────────────────────────────────────────────────────────────────────────
# Инфраструктура: два настоящих заведения и агенты под губернатором
# ────────────────────────────────────────────────────────────────────────────


def build_registry(nord_base: str, sued_base: str) -> Registry:
    """Реестр с двумя экземплярами одного сервиса.

    Второй манифест не подделка: тот же JSON с другим `service` и адресом
    проходит полную валидацию `parse_manifest`, то есть объявляет ровно те же
    последствия. Перепривязка адреса — штатная операция реестра (§registry).
    """
    reg = Registry().load_dir(ROOT / "act/manifests")
    reg.rebind(NORD, nord_base)

    raw = json.loads((ROOT / "act/manifests/venue.act.json").read_text(encoding="utf-8"))
    raw["service"] = SUED
    raw["title"] = "Клиника «Зюд» — Мюнхен"
    raw["base_url"] = sued_base
    reg.add(parse_manifest(raw))
    return reg


def make_agent(reg: Registry, folder: Path, name: str,
               limit: float = 1000.0) -> tuple[Agent, Ledger]:
    folder.mkdir(parents=True, exist_ok=True)
    led = Ledger(folder / f"{name.replace(':', '_')}.jsonl", owner=name)
    gov = Governor(reg, led, Budget(limit))
    return Agent(name, Executor(reg, gov, led)), led


def book(anna: Agent, clinic: Agent, service: str, day: str, at: str) -> dict:
    """Полный цикл: прочитать каталог → удержать → зафиксировать обязательство.

    Возвращает слот, который сервис реально отдал, — чтобы потом сверить
    деньги и время на карте с тем, что ответил сервис, а не с ожиданиями теста.
    """
    res = anna.read(service, "slot.list", {"day": day})
    if res is None or not res.ok:
        return {"error": "каталог не прочитан"}
    slot = next((s for s in res.body if s["time"] == at), None)
    if slot is None:
        return {"error": f"слот {day} {at} недоступен в {service}"}

    _, hold = anna.hold(service, "slot.hold", {"slot_id": slot["id"]})
    if hold is None:
        return {"error": "удержание не взято"}

    decision, cmt = anna.commit_two_party(
        service, "booking.create",
        {"hold_id": hold.hold_id, "name": "Анна Иванова",
         "note": slot["specialist"], "max_money": 120},
        counterparty=clinic, hold=hold,
        subject=f"приём {slot['day']} {slot['time']} · {slot['specialist']}",
    )
    return {"service": service, "slot": slot, "decision": decision, "commitment": cmt,
            "error": None if cmt else f"обязательство не создано: {decision.reason}"}


# ────────────────────────────────────────────────────────────────────────────
# 1. Линия времени собирается из настоящих записей
# ────────────────────────────────────────────────────────────────────────────


def test_timeline(reg: Registry, tmp: Path) -> tuple[Path, list[Entry]]:
    print("\nЛиния времени — из настоящих обязательств по HTTP:")
    folder = tmp / "day"
    anna, anna_led = make_agent(reg, folder, "person:anna")
    nord, nord_led = make_agent(reg, folder, "venue:clinic-nord", 10_000.0)
    sued, sued_led = make_agent(reg, folder, "venue:clinic-sued", 10_000.0)

    # Один день Анны, в который она подписалась на невозможное.
    deals = [
        book(anna, nord, NORD, "2026-10-12", "09:00"),
        book(anna, sued, SUED, "2026-10-12", "09:00"),
        book(anna, sued, SUED, "2026-10-12", "10:30"),
        book(anna, nord, NORD, "2026-10-12", "15:00"),
        book(anna, nord, NORD, "2026-10-13", "11:00"),
    ]
    bad = [d["error"] for d in deals if d.get("error")]
    check("пять обязательств оформлены живыми сервисами", not bad, "; ".join(bad))
    if bad:
        return folder, []

    check("журнал Анны цел", anna_led.verify())
    check("в журнале Анны пять записей commitment",
          len(anna_led.by_kind("commitment")) == 5,
          str(len(anna_led.by_kind("commitment"))))

    timeline = build_timeline({"person:anna": anna_led,
                               "venue:clinic-nord": nord_led,
                               "venue:clinic-sued": sued_led},
                              place_of=PLACES)
    mine = [e for e in timeline if e.party == "person:anna"]
    check("все пять попали на карту Анны", len(mine) == 5, str(len(mine)))

    first = mine[0]
    check("время взято из предмета сделки, а не выдумано",
          first.starts_at == datetime(2026, 10, 12, 9, 0), first.starts_at.isoformat())
    check("место подставлено по сервису",
          {e.place for e in mine} == {PLACE_NORD, PLACE_SUED},
          str(sorted({e.place for e in mine})))

    # Деньги карта берёт из исхода, а не из манифеста: в манифесте цена
    # объявлена как "variable" и становится известна только из ответа.
    on_map = {(e.starts_at.strftime("%Y-%m-%d %H:%M"), e.place): e.money for e in mine}
    from_service = {(f"{d['slot']['day']} {d['slot']['time']}", PLACES[d["service"]]):
                    d["slot"]["price"] for d in deals}
    check("деньги на карте равны тому, что ответил сервис", on_map == from_service,
          f"карта {on_map} ≠ сервис {from_service}")
    check("валюта взята из ответа сервиса",
          all(e.currency == "EUR" for e in mine))
    check("обязательство ссылается на строку журнала",
          all(e.seq >= 0 and e.ledger_path.endswith("person_anna.jsonl") for e in mine))

    # Клиники — тоже стороны обязательства, и у них свои карты.
    check("у каждой клиники своя линия времени",
          len([e for e in timeline if e.party == "venue:clinic-nord"]) == 3
          and len([e for e in timeline if e.party == "venue:clinic-sued"]) == 2,
          str([(e.party, e.span()) for e in timeline]))

    s = summary(mine, [])
    check("сводка считает занятые часы", s["busy_hours"] == 5.0, str(s["busy_hours"]))
    check("сводка считает деньги по журналу", s["money"] == 270.0, str(s["money"]))
    return folder, timeline


# ────────────────────────────────────────────────────────────────────────────
# 2. Пересечение по времени
# ────────────────────────────────────────────────────────────────────────────


def test_overlap(timeline: list[Entry]) -> None:
    print("\nПересечение — быть в двух городах в 09:00 нельзя:")
    # На вход идут карты всех трёх сторон сразу: так проверяется, что конфликт
    # считается внутри стороны, а не между чужими расписаниями.
    conflicts = detect_conflicts(timeline, travel=None, capacity_hours=10.0)
    check("найден ровно один конфликт пересечения",
          len(conflicts) == 1 and conflicts[0].kind == OVERLAP,
          str([(c.kind, c.party) for c in conflicts]))
    if not conflicts:
        return
    c = conflicts[0]
    check("конфликт отнесён к Анне, а не к клинике", c.party == "person:anna", c.party)
    check("пересечение посчитано в минутах", c.detail["overlap_min"] == 60,
          str(c.detail))
    check("в конфликте участвуют два разных места",
          set(c.detail["places"]) == {PLACE_NORD, PLACE_SUED}, str(c.detail["places"]))
    text = explain(c)
    check("объяснение по-русски и предъявляемо",
          "пересекаются" in text and "нельзя" in text and "person:anna#" in text, text)
    check("расписания клиник сами по себе непротиворечивы",
          all(c.party == "person:anna" for c in conflicts)
          and len({e.party for e in timeline}) == 3,
          str(sorted({e.party for e in timeline})))


# ────────────────────────────────────────────────────────────────────────────
# 3. Недостижимость по дороге
# ────────────────────────────────────────────────────────────────────────────


def test_travel(reg: Registry, tmp: Path) -> Path:
    print("\nДорога — из Гамбурга в Мюнхен за полчаса не успеть:")
    folder = tmp / "travel"
    anna, anna_led = make_agent(reg, folder, "person:anna")
    nord, _ = make_agent(reg, folder, "venue:clinic-nord", 10_000.0)
    sued, _ = make_agent(reg, folder, "venue:clinic-sued", 10_000.0)

    deals = [book(anna, nord, NORD, "2026-10-12", "10:30"),
             book(anna, sued, SUED, "2026-10-12", "15:00")]
    bad = [d["error"] for d in deals if d.get("error")]
    check("две брони в разных городах оформлены", not bad, "; ".join(bad))
    if bad:
        return folder

    timeline = build_timeline({"person:anna": anna_led}, place_of=PLACES)
    check("оба обязательства на карте", len(timeline) == 2, str(len(timeline)))

    by_path = load_timeline({"person:anna": str(folder / "person_anna.jsonl")},
                            place_of=PLACES)
    check("та же карта собирается прямо по пути к журналу",
          [(e.ref, e.starts_at) for e in by_path] == [(e.ref, e.starts_at) for e in timeline],
          str([e.ref for e in by_path]))

    # То же самое расписание без объявленной дороги — исполнимо.
    check("без матрицы дороги расписание непротиворечиво",
          detect_conflicts(timeline, travel=None, capacity_hours=10.0) == [])

    conflicts = detect_conflicts(timeline, travel=TRAVEL_HH_MUC, capacity_hours=10.0)
    check("с объявленной дорогой найден ровно один конфликт",
          len(conflicts) == 1 and conflicts[0].kind == TRAVEL,
          str([(c.kind, c.detail) for c in conflicts]))
    if not conflicts:
        return folder
    d = conflicts[0].detail
    check("запас времени посчитан верно (11:30 → 15:00 = 210 мин)",
          d["gap_min"] == 210, str(d))
    check("нужная дорога взята из матрицы", d["need_min"] == 240, str(d))
    check("опоздание посчитано", d["late_min"] == 30, str(d))
    check("направление указано от места к месту",
          d["from"] == PLACE_NORD and d["to"] == PLACE_SUED, str(d))
    text = explain(conflicts[0])
    check("объяснение называет дорогу и опоздание",
          "дорога" in text and "опоздание" in text and "по объявленной матрице" in text, text)
    return folder


# ────────────────────────────────────────────────────────────────────────────
# 4. Дневная ёмкость
# ────────────────────────────────────────────────────────────────────────────


def test_capacity(reg: Registry, tmp: Path) -> None:
    print("\nЁмкость дня — больше взятого, чем в дне есть:")
    folder = tmp / "capacity"
    anna, anna_led = make_agent(reg, folder, "person:anna")
    sued, _ = make_agent(reg, folder, "venue:clinic-sued", 10_000.0)

    deals = [book(anna, sued, SUED, "2026-10-13", "11:00"),
             book(anna, sued, SUED, "2026-10-13", "18:00")]
    bad = [d["error"] for d in deals if d.get("error")]
    check("две брони одного дня оформлены", not bad, "; ".join(bad))
    if bad:
        return

    timeline = build_timeline({"person:anna": anna_led}, place_of=PLACES)
    check("при ёмкости 10 ч тот же день исполним",
          detect_conflicts(timeline, capacity_hours=10.0) == [])

    conflicts = detect_conflicts(timeline, capacity_hours=1.5)
    check("при ёмкости 1.5 ч найден конфликт перегрузки",
          len(conflicts) == 1 and conflicts[0].kind == CAPACITY,
          str([(c.kind, c.detail) for c in conflicts]))
    if not conflicts:
        return
    d = conflicts[0].detail
    check("занятое и предел посчитаны в минутах",
          d["busy_min"] == 120 and d["limit_min"] == 90, str(d))
    check("превышение посчитано", d["over_min"] == 30, str(d))
    check("в конфликт попали все записи дня", len(conflicts[0].entries) == 2)
    check("объяснение называет часы и ёмкость",
          "ёмкости" in explain(conflicts[0]) and "2.0 ч" in explain(conflicts[0]),
          explain(conflicts[0]))


# ────────────────────────────────────────────────────────────────────────────
# 5. Аннотация `when` и предикат губернатора
# ────────────────────────────────────────────────────────────────────────────


def test_annotation_and_predicate(reg: Registry, tmp: Path) -> None:
    print("\nАннотация времени и предикат губернатора:")
    folder = tmp / "predicate"
    anna, anna_led = make_agent(reg, folder, "person:anna")
    nord, _ = make_agent(reg, folder, "venue:clinic-nord", 10_000.0)

    deal = book(anna, nord, NORD, "2026-10-13", "18:00")
    check("бронь для проверки предиката оформлена", not deal.get("error"),
          str(deal.get("error")))
    if deal.get("error"):
        return

    # Обязательство, у которого время объявлено полем, а не спрятано в строке.
    # Запись идёт через настоящий Ledger.append — формат не подделывается.
    anna_led.append("commitment", {
        "commitment_id": "cmt_sadik_0001",
        "parties": ["person:anna", "institution:kita-nord"],
        "subject": "забрать ребёнка из садика",
        "service": "kita-nord",
        "verb": "pickup.commit",
        "when": {"starts_at": "2026-10-13T16:30", "duration_min": 30,
                 "place": "Садик", "role": "семья"},
    })
    timeline = build_timeline({"person:anna": anna_led}, place_of=PLACES)
    kita = [e for e in timeline if e.place == "Садик"]
    check("аннотация `when` прочитана как время обязательства", len(kita) == 1,
          str([(e.place, e.starts_at.isoformat()) for e in timeline]))
    if not kita:
        return
    check("длительность и роль взяты из аннотации",
          kita[0].duration_min == 30 and kita[0].role == "семья"
          and kita[0].track == "семья",
          f"{kita[0].duration_min} / {kita[0].role}")
    check("журнал после дописанной записи по-прежнему цел", anna_led.verify())
    check("садик и клиника в один день не конфликтуют (16:30 и 18:00)",
          detect_conflicts(timeline, travel=TravelMatrix({("Садик", PLACE_NORD): 20}),
                           capacity_hours=10.0) == [])

    # Губернатор спрашивает про ЕЩЁ НЕ взятое обязательство.
    candidate = Entry.proposed(
        "person:anna", "родительское собрание", "2026-10-13T18:30",
        duration_min=60, place="Школа", role="семья",
    )
    predicate = governor_predicate(
        timeline, travel=TravelMatrix({(PLACE_NORD, "Школа"): 40}), capacity_hours=10.0)
    reasons = predicate(candidate)
    check("предикат находит основание для отказа до исполнения",
          len(reasons) == 1 and reasons[0].kind == OVERLAP,
          str([(c.kind, c.message) for c in reasons]))

    late = Entry.proposed("person:anna", "родительское собрание", "2026-10-13T19:10",
                          duration_min=60, place="Школа", role="семья")
    check("то же собрание на час позже упирается в дорогу",
          [c.kind for c in predicate(late)] == [TRAVEL],
          str([(c.kind, c.detail) for c in predicate(late)]))

    free = Entry.proposed("person:anna", "родительское собрание", "2026-10-13T20:00",
                          duration_min=60, place="Школа", role="семья")
    check("на 20:00 место в расписании есть", predicate(free) == [])
    check("свои прежние конфликты предикат в вину не ставит",
          would_conflict(timeline, free) == [])


# ────────────────────────────────────────────────────────────────────────────
# 6. build_map.py: настоящий HTML из настоящих журналов
# ────────────────────────────────────────────────────────────────────────────


def run_map(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "act/viz/build_map.py"), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )


def test_build_map(day_folder: Path, travel_folder: Path, tmp: Path) -> None:
    print("\nbuild_map.py — самодостаточный HTML из журналов:")
    out = tmp / "map-test.html"
    proc = run_map([
        "--dir", str(day_folder),
        "--place", f"{NORD}={PLACE_NORD}",
        "--place", f"{SUED}={PLACE_SUED}",
        "--travel", f"{PLACE_NORD}>{PLACE_SUED}=240",
        "--capacity-hours", "3.5",
        "--out", str(out),
    ])
    check("CLI завершился кодом 2 (карта построена, фигуры найдены)",
          proc.returncode == 2, f"код {proc.returncode}: {proc.stderr[-300:]}")
    check("CLI перечислил неисполнимое по-русски",
          "Неисполнимо" in proc.stdout and "пересекаются" in proc.stdout,
          proc.stdout[-300:])
    check("профиль узнан по имени файла журнала",
          "person:anna" in proc.stdout or "person_anna" in proc.stdout, proc.stdout[-200:])

    check("HTML создан", out.exists())
    if not out.exists():
        return
    html = out.read_text(encoding="utf-8")
    check("HTML непустой и целый", len(html) > 4000 and html.endswith("</html>\n"),
          str(len(html)))

    raw = html.split('<script id="payload" type="application/json">', 1)[-1]
    raw = raw.split("</script>", 1)[0].replace("<\\/", "</")
    data = json.loads(raw)
    # 10 = пять обязательств Анны плюс те же пять со стороны двух клиник:
    # обязательство двустороннее, значит на карте оно есть у обоих.
    check("данные встроены в файл и разбираются",
          data["summary"]["entries"] == 10 and len(data["summary"]["parties"]) == 3,
          str(data["summary"]))
    check("в данных настоящие предметы сделок",
          any("Терапевт" in e["label"] for e in data["entries"]),
          str([e["label"] for e in data["entries"]])[:200])
    check("в данных настоящие деньги из журнала",
          data["summary"]["money"] == 270.0, str(data["summary"]["money"]))
    kinds = {c["kind"] for c in data["conflicts"]}
    check("в карте все три вида неисполнимости",
          kinds == {OVERLAP, TRAVEL, CAPACITY}, str(sorted(kinds)))
    check("каждый конфликт несёт объяснение и ссылки на записи",
          all(c["explain"] and c["refs"] for c in data["conflicts"]))

    check("ни одной внешней ссылки: ни CDN, ни <script src>",
          "<script src" not in html and "cdn" not in html.lower()
          and "https://" not in html and "<link" not in html)
    check("обе темы учтены", "prefers-color-scheme: dark" in html)
    check("время в данных наивное, без зоны",
          all("Z" not in e["starts_at"] and "+" not in e["starts_at"]
              for e in data["entries"]))

    # Непротиворечивое расписание: тот же CLI, код возврата 0.
    clean = tmp / "map-clean.html"
    ok = run_map(["--dir", str(travel_folder), "--ledger",
                  f"person:anna={travel_folder / 'person_anna.jsonl'}",
                  "--capacity-hours", "10", "--out", str(clean)])
    check("на непротиворечивом расписании код возврата 0", ok.returncode == 0,
          f"код {ok.returncode}: {ok.stdout[-200:]}")
    check("CLI сказал, что расписание исполнимо",
          "Неисполнимого не найдено" in ok.stdout, ok.stdout[-200:])

    # Карта, которая лежит в репозитории, — результат этого же прогона.
    repo = run_map([
        "--dir", str(day_folder),
        "--place", f"{NORD}={PLACE_NORD}",
        "--place", f"{SUED}={PLACE_SUED}",
        "--travel", f"{PLACE_NORD}>{PLACE_SUED}=240",
        "--capacity-hours", "3.5",
        "--title", "Карта обязательств Анны · 12–13 октября 2026",
        "--quiet",
    ])
    repo_map = ROOT / "act/viz/map.html"
    check("карта по умолчанию легла в act/viz/map.html",
          repo.returncode == 2 and repo_map.exists() and repo_map.stat().st_size > 4000,
          f"код {repo.returncode}")


# ────────────────────────────────────────────────────────────────────────────


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_act_calendar_"))
    ports = (8231, 8232)
    procs = []
    try:
        for port, tag in zip(ports, ("nord", "sued")):
            db = tmp / f"{tag}.db"
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "act.services.venue.server",
                 "--port", str(port), "--db", str(db), "--reset"],
                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for port in ports:
            if not wait_up(f"http://127.0.0.1:{port}/api/health"):
                print(f"✗ сервис заведения не поднялся на :{port}")
                return 1
        print("Два заведения подняты на :%d (Норд) и :%d (Зюд)" % ports)

        reg = build_registry(f"http://127.0.0.1:{ports[0]}", f"http://127.0.0.1:{ports[1]}")
        day_folder, timeline = test_timeline(reg, tmp)
        if timeline:
            test_overlap(timeline)
        travel_folder = test_travel(reg, tmp)
        test_capacity(reg, tmp)
        test_annotation_and_predicate(reg, tmp)
        test_build_map(day_folder, travel_folder, tmp)
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
