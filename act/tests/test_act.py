"""Smoke-тесты NPP-Act: реальный HTTP через границы процессов, без моков самого себя.

Дисциплина взята из daten2 (каждый компонент — свой smoke-тест), но с поправкой
на главный изъян, найденный при аудите: сервис не вправе проверять себя против
собственного мока. Поэтому здесь поднимается НАСТОЯЩИЙ сервис заведения, и все
проверки идут по сети.

Запуск:  python3 -m act.tests.test_act
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import (  # noqa: E402
    Agent, Budget, Executor, Governor, Ledger, Registry, load_manifest,
)
from act.npp_act.manifest import ManifestError, parse_manifest  # noqa: E402

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


def wait_up(url: str, attempts: int = 50) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


# ────────────────────────────────────────────────────────────────────────────
# 1. Манифест: валидатор ловит то, на чём стоит губернатор
# ────────────────────────────────────────────────────────────────────────────

def test_manifest() -> None:
    print("\nМанифест — валидация последствий:")

    man = load_manifest(ROOT / "act/manifests/venue.act.json")
    check("манифест заведения загружен", man.service == "venue-clinic-nord")
    check("объявлено 5 глаголов", len(man.capabilities) == 5, str(len(man.capabilities)))

    hold = man.verb("slot.hold")
    check("slot.hold обратим и знает обратный глагол",
          hold.reversible and hold.reverse == "slot.release")
    check("удержание обязано истекать", hold.expires_s == 120)

    booking = man.verb("booking.create")
    check("booking.create — обязательство", booking.effect == "commit")
    check("тяжесть монотонна: commit > reserve", booking.severity > hold.severity)
    check("бронь требует согласия обеих сторон", booking.consent == "two_party")
    check("бронь объявила идемпотентность",
          booking.idempotency_slot() == ("header", "Idempotency-Key"))
    check("цена брони переменная", booking.money_is_variable)

    base = json.loads((ROOT / "act/manifests/venue.act.json").read_text(encoding="utf-8"))

    # Необратимое обязательство без участия человека нельзя даже объявить.
    bad = json.loads(json.dumps(base))
    for c in bad["capabilities"]:
        if c["id"] == "booking.create":
            c["consent"] = "none"
    try:
        parse_manifest(bad)
        check("необратимое без consent отвергнуто", False, "принято, а не должно")
    except ManifestError as e:
        check("необратимое с consent='none' отвергнуто", "consent='none'" in str(e))

    # Обязательство без ключа идемпотентности — отказ.
    bad2 = json.loads(json.dumps(base))
    for c in bad2["capabilities"]:
        if c["id"] == "booking.create":
            c.pop("idempotency", None)
    try:
        parse_manifest(bad2)
        check("commit без идемпотентности отвергнут", False, "принято")
    except ManifestError as e:
        check("commit без идемпотентности отвергнут", "idempotency" in str(e))

    # Обратимость без обратного глагола — декларация, а не возможность.
    bad3 = json.loads(json.dumps(base))
    for c in bad3["capabilities"]:
        if c["id"] == "slot.hold":
            c.pop("reverse", None)
    try:
        parse_manifest(bad3)
        check("reversible без reverse отвергнут", False, "принято")
    except ManifestError:
        check("reversible без обратного глагола отвергнут", True)


# ────────────────────────────────────────────────────────────────────────────
# 2. Журнал: цепь, персистентность, обнаружение подделки
# ────────────────────────────────────────────────────────────────────────────

def test_ledger() -> None:
    print("\nЖурнал — хэш-цепь и персистентность:")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "led.jsonl"
        led = Ledger(path, owner="person:anna")
        r1 = led.append("intent", {"verb": "slot.hold"})
        r2 = led.append("decision", {"verdict": "admit"})
        check("цепь сцеплена", r2.prev == r1.hash)
        check("цепь проверяется", led.verify())

        again = led.reload()
        check("журнал пережил перезапуск", len(again) == 2 and again.verify())

        # Подделка содержимого должна разрывать цепь.
        raw = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(raw[0])
        rec["payload"]["verb"] = "booking.create"
        raw[0] = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        path.write_text("\n".join(raw) + "\n", encoding="utf-8")

        tampered = Ledger(path)
        try:
            tampered.verify()
            check("подделка обнаружена", False, "verify() не заметил подмену")
        except Exception as e:
            check("подделка обнаружена", "изменено" in str(e) or "сцеплен" in str(e))


# ────────────────────────────────────────────────────────────────────────────
# 3-5. Губернатор и сквозной сценарий против живого сервиса
# ────────────────────────────────────────────────────────────────────────────

VENUE = "venue-clinic-nord"
BASE = ""  # подставляется в main() — перепривязка манифеста на тестовый порт


def build(tmp: Path, limit: float, name: str) -> tuple[Agent, Governor, Ledger]:
    reg = Registry().load_dir(ROOT / "act/manifests")
    if BASE:
        reg.rebind(VENUE, BASE)
    led = Ledger(tmp / f"{name.replace(':', '_')}.jsonl", owner=name)
    gov = Governor(reg, led, Budget(limit))
    ex = Executor(reg, gov, led)
    return Agent(name, ex), gov, led


def test_live(port: int) -> None:
    base = f"http://127.0.0.1:{port}"

    print("\nГубернатор — жёсткие предикаты:")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        anna, gov, led = build(tmp, 100.0, "person:anna")

        d = gov.evaluate("нет-такого", "slot.list")
        check("H1 неизвестный сервис заблокирован", d.verdict == "block")

        d = gov.evaluate("venue-clinic-nord", "slot.teleport")
        check("H2 необъявленный глагол заблокирован", d.verdict == "block")

        d = gov.evaluate("venue-clinic-nord", "booking.create", {"max_money": 90})
        check("H5 обязательство без ключа идемпотентности заблокировано",
              d.verdict == "block" and "идемпотент" in d.reason)

        poor, poor_gov, _ = build(tmp, 10.0, "person:poor")
        d = poor_gov.evaluate("venue-clinic-nord", "booking.create",
                              {"max_money": 90}, idempotency_key="k1")
        check("H3 превышение бюджета заблокировано",
              d.verdict == "block" and "бюджет" in d.reason)

        d = gov.evaluate("venue-clinic-nord", "slot.list")
        check("чтение проходит без гейта", d.verdict == "admit")

        d = gov.evaluate("venue-clinic-nord", "booking.create",
                         {"max_money": 45}, idempotency_key="k2")
        check("S3 без согласия сторон — эскалация",
              d.verdict == "escalate" and "подтверждени" in d.reason)

    print("\nСквозной сценарий — два профиля, живой HTTP:")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        anna, anna_gov, anna_led = build(tmp, 200.0, "person:anna")
        clinic, _, clinic_led = build(tmp, 10_000.0, "venue:clinic-nord")

        res = anna.read("venue-clinic-nord", "slot.list", {"day": "2026-10-12"})
        check("каталог времени прочитан живым сервисом", res is not None and res.ok)
        slots = res.body
        check("слоты пришли", isinstance(slots, list) and len(slots) >= 2, str(slots)[:80])
        slot = slots[0]

        dec, hold = anna.hold("venue-clinic-nord", "slot.hold", {"slot_id": slot["id"]})
        check("удержание взято", dec.admitted and hold is not None and hold.hold_id)
        check("удержание имеет срок", hold is not None and not hold.expired)

        with urllib.request.urlopen(f"{base}/api/slots?day=2026-10-12") as r:
            free_now = json.loads(r.read())
        check("удержанный слот исчез из свободных",
              all(s["id"] != slot["id"] for s in free_now))

        dec, cmt = anna.commit_two_party(
            "venue-clinic-nord", "booking.create",
            {"hold_id": hold.hold_id, "name": "Анна Иванова",
             "note": "первичный приём", "max_money": 90},
            counterparty=clinic, hold=hold,
            subject=f"приём {slot['day']} {slot['time']}",
        )
        check("бронь допущена губернатором", dec.admitted, dec.reason)
        check("обязательство создано", cmt is not None)
        if cmt:
            check("в обязательстве две стороны", len(cmt.parties) == 2)
            check("обе цепи подтверждают обязательство",
                  cmt.verified_by({"person:anna": anna_led, "venue:clinic-nord": clinic_led}))

        check("бюджет списан по факту", anna_gov.budget.spent == slot["price"],
              f"списано {anna_gov.budget.spent}")

        # Повтор того же обязательства не должен пройти второй раз.
        dec2, _ = anna.act("venue-clinic-nord", "booking.create",
                           {"hold_id": hold.hold_id, "name": "Анна Иванова"},
                           key="повтор-вручную")
        check("повторная бронь без согласия сторон не допущена",
              not dec2.admitted, f"verdict={dec2.verdict}: {dec2.reason}")

        check("журнал Анны цел", anna_led.verify())
        check("журнал клиники цел", clinic_led.verify())
        kinds = [r.kind for r in anna_led]
        check("журнал содержит все стадии",
              {"intent", "decision", "execution", "outcome", "commitment"} <= set(kinds),
              str(sorted(set(kinds))))

    print("\nОтпускание несостоявшейся сделки:")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        bob, _, _ = build(tmp, 200.0, "person:bob")
        res = bob.read("venue-clinic-nord", "slot.list", {})
        free_before = len(res.body)
        _, hold = bob.hold("venue-clinic-nord", "slot.hold", {"slot_id": res.body[0]["id"]})
        check("слот удержан", hold is not None)
        bob.release(hold)
        res2 = bob.read("venue-clinic-nord", "slot.list", {})
        check("после release слот снова свободен", len(res2.body) == free_before,
              f"{free_before} → {len(res2.body)}")

    print("\nИдемпотентность на стороне сервиса:")
    with urllib.request.urlopen(f"{base}/api/slots") as r:
        free = json.loads(r.read())
    req = urllib.request.Request(
        f"{base}/api/holds", method="POST",
        data=json.dumps({"slot_id": free[0]["id"]}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        h = json.loads(r.read())

    def book(key: str) -> dict:
        rq = urllib.request.Request(
            f"{base}/api/bookings", method="POST",
            data=json.dumps({"hold_id": h["hold_id"], "name": "Повтор Тестов"}).encode(),
            headers={"Content-Type": "application/json", "Idempotency-Key": key})
        with urllib.request.urlopen(rq) as r:
            return json.loads(r.read())

    first = book("same-key-001")
    second = book("same-key-001")
    check("первая бронь создана", "booking_number" in first)
    check("повтор с тем же ключом вернул ту же бронь",
          second.get("booking_number") == first.get("booking_number"))
    check("повтор помечен как воспроизведение", second.get("idempotent_replay") is True)


def main() -> int:
    db = Path(tempfile.gettempdir()) / "npp_act_test.db"
    if db.exists():
        db.unlink()
    port = 8219
    global BASE
    BASE = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "act.services.venue.server",
         "--port", str(port), "--db", str(db), "--reset"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_up(f"http://127.0.0.1:{port}/api/health"):
            print("✗ сервис заведения не поднялся")
            return 1
        print("Сервис заведения поднят на :%d" % port)
        test_manifest()
        test_ledger()
        test_live(port)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
