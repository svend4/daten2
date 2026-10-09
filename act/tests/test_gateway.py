"""Тест HTTP-шлюза рантайма: проверяет главный инвариант — гейт не обойти.

Шлюз поднимается подпроцессом вместе с настоящим сервисом заведения.
Моков нет: все проверки идут по сети против живых процессов.

Запуск:  python3 -m act.tests.test_gateway
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PASSED = 0
FAILED = 0

GW_PORT = 8201
VENUE_PORT = 8211


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def wait_up(url: str, attempts: int = 60) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def post(path: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{GW_PORT}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(path: str) -> tuple[int, object]:
    with urllib.request.urlopen(f"http://127.0.0.1:{GW_PORT}{path}", timeout=10) as r:
        return r.status, json.loads(r.read())


def main() -> int:
    global PASSED, FAILED
    tmp = Path(tempfile.mkdtemp(prefix="npp_gw_"))
    procs = []
    try:
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "act.services.venue.server",
             "--port", str(VENUE_PORT), "--db", str(tmp / "v.db"), "--reset"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if not wait_up(f"http://127.0.0.1:{VENUE_PORT}/api/health"):
            print("✗ сервис заведения не поднялся")
            return 1

        procs.append(subprocess.Popen(
            [sys.executable, "-m", "act.gateway",
             "--port", str(GW_PORT), "--ledger", str(tmp / "gw.jsonl"),
             "--budget", "300", "--owner", "person:test",
             "--rebind", f"venue-clinic-nord=http://127.0.0.1:{VENUE_PORT}"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if not wait_up(f"http://127.0.0.1:{GW_PORT}/api/health"):
            print("✗ шлюз не поднялся")
            return 1
        print(f"Шлюз на :{GW_PORT}, заведение на :{VENUE_PORT}")

        print("\nКаталог и состояние:")
        _, health = get("/api/health")
        check("шлюз отвечает и знает профиль", health.get("owner") == "person:test")
        _, catalog = get("/act/catalog")
        check("каталог не пуст", isinstance(catalog, list) and len(catalog) >= 9, str(len(catalog)))
        commits = [r for r in catalog if r["effect"] == "commit"]
        check("у всех обязательств объявлен consent",
              all(r["consent"] != "none" for r in commits))
        _, budget = get("/act/budget")
        check("бюджет виден", budget["limit"] == 300.0)

        print("\nГлавный инвариант — произвольный вызов невозможен:")
        st, body = post("/act/perform", {"service": "venue-clinic-nord", "verb": "slot.teleport"})
        check("необъявленный глагол отвергнут",
              body.get("decision", {}).get("verdict") == "block")
        check("ничего не исполнено", body.get("executed") is False)
        st, body = post("/act/perform", {"payload": {}})
        check("запрос без service/verb отвергнут кодом 400", st == 400)
        st, body = post("/act/raw", {"url": "http://example.com"})
        check("эндпоинта произвольного запроса нет", st == 404)

        print("\nСухой прогон не меняет мир:")
        _, dry = post("/act/perform", {
            "service": "venue-clinic-nord", "verb": "slot.hold",
            "payload": {"slot_id": 1}, "idempotency_key": "dry-1", "dry_run": True})
        check("dry_run допускает удержание", dry["decision"]["verdict"] == "admit")
        check("dry_run ничего не исполнил", dry["executed"] is False)
        with urllib.request.urlopen(f"http://127.0.0.1:{VENUE_PORT}/api/slots") as r:
            free_after_dry = len(json.loads(r.read()))
        check("после dry_run слоты не тронуты", free_after_dry == 5, str(free_after_dry))

        print("\nНастоящее действие проходит через гейт и попадает в журнал:")
        _, real = post("/act/perform", {
            "service": "venue-clinic-nord", "verb": "slot.hold",
            "payload": {"slot_id": 1}, "idempotency_key": "real-1"})
        check("удержание допущено и исполнено",
              real["decision"]["verdict"] == "admit" and real["executed"])
        hold_id = real["result"]["body"]["hold_id"]
        check("сервис вернул удержание", bool(hold_id))
        with urllib.request.urlopen(f"http://127.0.0.1:{VENUE_PORT}/api/slots") as r:
            free_after_real = len(json.loads(r.read()))
        check("после настоящего действия слот занят", free_after_real == 4, str(free_after_real))

        print("\nСогласие и двусторонняя бронь:")
        _, esc = post("/act/perform", {
            "service": "venue-clinic-nord", "verb": "booking.create",
            "payload": {"hold_id": hold_id, "name": "Тест", "max_money": 90},
            "idempotency_key": "bk-1", "dry_run": True})
        check("без согласия — эскалация", esc["decision"]["verdict"] == "escalate")

        post("/act/confirm", {"service": "venue-clinic-nord",
                              "verb": "booking.create", "idempotency_key": "bk-1"})
        _, ok = post("/act/perform", {
            "service": "venue-clinic-nord", "verb": "booking.create",
            "payload": {"hold_id": hold_id, "name": "Тест", "max_money": 90},
            "idempotency_key": "bk-1"})
        check("после confirm бронь допущена", ok["decision"]["verdict"] == "admit",
              ok["decision"]["reason"])
        check("бронь создана", ok.get("result", {}).get("ok") is True)
        check("бюджет списан по факту", ok["budget_remaining"] < 300.0,
              str(ok["budget_remaining"]))

        print("\nПовтор по тому же ключу:")
        _, dup = post("/act/perform", {
            "service": "venue-clinic-nord", "verb": "booking.create",
            "payload": {"hold_id": hold_id, "name": "Тест", "max_money": 90},
            "idempotency_key": "bk-1"})
        check("повтор заблокирован губернатором",
              dup["decision"]["verdict"] == "block" and "овтор" in dup["decision"]["reason"],
              dup["decision"]["reason"])

        print("\nЖурнал:")
        _, ver = get("/act/ledger/verify")
        check("цепь цела", ver["ok"] is True)
        _, recs = get("/act/ledger?limit=100")
        kinds = {r["kind"] for r in recs}
        check("журнал содержит намерения, решения, исполнения и исходы",
              {"intent", "decision", "execution", "outcome"} <= kinds, str(sorted(kinds)))
        blocked = [r for r in recs if r["kind"] == "decision" and r["payload"]["verdict"] == "block"]
        check("отказы тоже записаны", len(blocked) >= 2, str(len(blocked)))
        check("телефон/почта не попадают в журнал",
              all("<скрыто>" == r["payload"].get("payload", {}).get("phone", "<скрыто>")
                  for r in recs if r["kind"] == "intent"))

    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
