"""Обыкновенное чудо: один агент, два сервиса разной природы, один аудит.

Сценарий. Анне нужно записаться к врачу и отправить цветы.
Это два РАЗНЫХ по природе ресурса:

  • время     — невозвратно (непроданный вторник не продашь завтра) → reserve+commit
  • товар     — возвратен (непроданный букет продашь завтра)        → сразу commit

Агент работает с обоими через один протокол последствий, под одним губернатором
и с одной хэш-цепью аудита. Ничего магического: каждое действие объявлено,
проверено, исполнено по HTTP и записано.

Магазин берётся НАСТОЯЩИЙ — из ветки claude/level1-php-GBpVR, той самой, что
реализует единый контракт daten2. Своего мока здесь нет сознательно: аудит
показал, что проверка сервиса против собственного мока — главный способ
обмануть себя.

Запуск:  python3 -m act.demo.scenario
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import Agent, Budget, Executor, Governor, Ledger, Registry  # noqa: E402

VENUE_PORT = 8210
SHOP_PORT = 8181
SHOP_BRANCH = "origin/claude/level1-php-GBpVR"


def wait_up(url: str, attempts: int = 60) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def start_venue(tmp: Path) -> subprocess.Popen:
    db = tmp / "venue.db"
    return subprocess.Popen(
        [sys.executable, "-m", "act.services.venue.server",
         "--port", str(VENUE_PORT), "--db", str(db), "--reset"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def start_shop(tmp: Path) -> subprocess.Popen | None:
    """Поднять настоящий уровень 1 из его ветки. None, если PHP или ветки нет."""
    if shutil.which("php") is None:
        return None
    work = tmp / "level1"
    work.mkdir(parents=True, exist_ok=True)
    try:
        archive = subprocess.run(
            ["git", "-C", str(ROOT), "archive", SHOP_BRANCH],
            capture_output=True, check=True,
        ).stdout
        subprocess.run(["tar", "-x", "-C", str(work)], input=archive, check=True)
    except subprocess.CalledProcessError:
        return None
    subprocess.run([shutil.which("php"), "init_db.php"], cwd=str(work),
                   capture_output=True)
    return subprocess.Popen(
        [shutil.which("php"), "-S", f"127.0.0.1:{SHOP_PORT}"],
        cwd=str(work), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def line(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def show(decision, note: str = "") -> None:
    colour = {"admit": "\033[32m", "block": "\033[31m", "escalate": "\033[33m"}[decision.verdict]
    print(f"   {colour}{decision}\033[0m" + (f"\n      {note}" if note else ""))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_act_demo_"))
    procs: list[subprocess.Popen] = []

    print("\033[1m⬡ NPP-Act 1.0 — уровень совместимости 4 в работе\033[0m")
    print(f"   рабочий каталог: {tmp}")

    try:
        procs.append(start_venue(tmp))
        if not wait_up(f"http://127.0.0.1:{VENUE_PORT}/api/health"):
            print("✗ сервис заведения не поднялся")
            return 1
        print(f"   ✓ клиника на :{VENUE_PORT} (продаёт время)")

        shop = start_shop(tmp)
        shop_alive = False
        if shop is not None:
            procs.append(shop)
            shop_alive = wait_up(f"http://127.0.0.1:{SHOP_PORT}/api/health")
        if shop_alive:
            print(f"   ✓ магазин цветов на :{SHOP_PORT} (уровень 1, PHP, из своей ветки)")
        else:
            print("   · магазин пропущен (нет php или ветки) — сценарий пойдёт без него")

        # ---------- профили ----------
        registry = Registry().load_dir(ROOT / "act/manifests")
        registry.rebind("venue-clinic-nord", f"http://127.0.0.1:{VENUE_PORT}")
        registry.rebind("flower-shop", f"http://127.0.0.1:{SHOP_PORT}")

        anna_led = Ledger(tmp / "anna.jsonl", owner="person:anna")
        anna_gov = Governor(registry, anna_led, Budget(300.0))
        anna = Agent("person:anna", Executor(registry, anna_gov, anna_led))

        clinic_led = Ledger(tmp / "clinic.jsonl", owner="venue:clinic-nord")
        clinic_gov = Governor(registry, clinic_led, Budget(10_000.0))
        clinic = Agent("venue:clinic-nord", Executor(registry, clinic_gov, clinic_led))

        line("Каталог возможностей — то, что мог бы прочитать n8n:")
        for row in registry.catalog():
            mark = {"read": "·", "reserve": "~", "commit": "!", "money": "€", "destroy": "✖"}[row["effect"]]
            print(f"   {mark} {row['service']:<20} {row['verb']:<16} "
                  f"{row['effect']:<8} consent={row['consent']:<10} "
                  f"{'обратим' if row['reversible'] else 'необратим'}")

        line("1. Чтение — гейт не требуется:")
        res = anna.read("venue-clinic-nord", "slot.list", {"day": "2026-10-12"})
        slots = res.body
        for s in slots:
            print(f"   {s['day']} {s['time']}  {s['specialist']:<12} {s['price']:.2f} €")

        line("2. Попытка сразу забронировать — губернатор не пускает:")
        d = anna_gov.evaluate("venue-clinic-nord", "booking.create", {"max_money": 90})
        show(d, "обязательство без ключа идемпотентности исполнить нельзя: повтор создал бы вторую бронь")

        line("3. Правильный путь — сперва обратимое удержание:")
        slot = slots[0]
        d, hold = anna.hold("venue-clinic-nord", "slot.hold", {"slot_id": slot["id"]})
        show(d)
        print(f"      удержание {hold.hold_id}, истекает {hold.expires_at}")

        line("4. Бронь требует согласия ОБЕИХ сторон (consent=two_party):")
        d = anna_gov.evaluate("venue-clinic-nord", "booking.create",
                              {"max_money": 90}, idempotency_key="demo-1", hold=hold.as_gate_input())
        show(d, "пока согласие не получено — эскалация, а не отказ")

        line("5. Согласие получено — обязательство фиксируется в двух журналах:")
        d, commitment = anna.commit_two_party(
            "venue-clinic-nord", "booking.create",
            {"hold_id": hold.hold_id, "name": "Анна Иванова",
             "note": "первичный приём", "max_money": 90},
            counterparty=clinic, hold=hold,
            subject=f"приём {slot['day']} {slot['time']} {slot['specialist']}",
        )
        show(d)
        if commitment:
            print(f"      обязательство {commitment.id}")
            print(f"      стороны: {', '.join(commitment.parties)}")
            for party, h in commitment.hashes.items():
                print(f"        {party:<22} запись {h[:16]}…")
            ok = commitment.verified_by({"person:anna": anna_led, "venue:clinic-nord": clinic_led})
            print(f"      обе цепи подтверждают одно и то же: {'да' if ok else 'НЕТ'}")

        if shop_alive:
            line("6. Другой сервис, другая природа ресурса — товар:")
            cat = anna.read("flower-shop", "catalog.list")
            products = cat.body if isinstance(cat.body, list) else []
            for p in products[:3]:
                print(f"   {p.get('name'):<20} {float(p.get('price', 0)):.2f} €  остаток {p.get('stock')}")

            if products:
                anna.accept("flower-shop", "order.create", "demo-order")
                d, res = anna.act(
                    "flower-shop", "order.create",
                    {"name": "Анна Иванова", "phone": "+49 170 0000000",
                     "items": [{"product_id": products[0]["id"], "qty": 2}],
                     "max_money": 40},
                    key="demo-order",
                )
                show(d)
                if res and res.ok:
                    print(f"      заказ {res.body.get('order_number')[:16]}… "
                          f"на {res.body.get('total')} €")

        line("7. Бюджет — списан по факту, а не по объявлению:")
        print(f"   лимит {anna_gov.budget.limit:.2f} €  ·  потрачено "
              f"{anna_gov.budget.spent:.2f} €  ·  остаток {anna_gov.budget.remaining:.2f} €")

        line("8. Аудит — вся история решений в хэш-цепи:")
        for r in anna_led:
            p = r.payload
            tail = p.get("verb") or p.get("commitment_id") or ""
            extra = ""
            if r.kind == "decision":
                extra = f" → {p.get('verdict')}"
            elif r.kind == "outcome":
                extra = f" → списано {p.get('charged', 0):.2f} €"
            print(f"   #{r.seq:<2} {r.ts}  {r.kind:<11} {tail:<22}{extra}")
        print(f"   цепь цела: {anna_led.verify()}")
        print(f"   журнал на диске: {anna_led.path}")

        reloaded = anna_led.reload()
        print(f"   перечитан с диска: {len(reloaded)} записей, цепь цела: {reloaded.verify()}")

        line("Итог:")
        print("   Два независимых сервиса. Разная природа ресурса — время и товар.")
        print("   Один протокол последствий, один гейт, одна проверяемая история.")
        print("   Ни одного API-ключа, ни одной внешней зависимости.")
        return 0

    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
