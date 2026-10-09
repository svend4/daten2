"""Проверка переговоров и расчёта: против живого сервиса и против инварианта.

ПОЧЕМУ ЭТОТ ТЕСТ УСТРОЕН ИМЕННО ТАК
-----------------------------------
Самосертификация запрещена, и в этом модуле соблазн особенно велик: расчётный
слой легко «проверить» против мока, написанного под те же допущения, —
получится 20/20 зелёных и ноль знания. В аудите экосистемы это уже случалось:
plugin-marketplace имеет 14/14 зелёных и при этом отвергает все настоящие
бэкенды, потому что его мок валидирует не то, что валидирует контракт.

Поэтому здесь два вида проверок, и ни один не сводится к моку:

1. ИНВАРИАНТЫ ПРОТИВ СЛУЧАЙНОСТИ. Масса денег, удержания и состояния саг
   проверяются не на одном удачном сценарии, а на 200 расчётах, собранных из
   фиксированного зерна. Проверяется свойство, которое обязано держаться при
   любом порядке событий, а не поведение, подогнанное под пример.

2. СДЕЛКА ПРОТИВ НАСТОЯЩЕЙ ВТОРОЙ СТОРОНЫ. Подпроцессом поднимается цех —
   Actionable-сервис из этапа 11, — и обязательство оформляется по сети против
   него. Цена, о которой договорились агенты, обязана доехать до живого
   контракта с точностью до цента, а неисполнимая договорённость обязана быть
   отвергнута сервисом, а не нами. Торг, который «договорился» о двенадцати
   часах у исполнителя с десятью часами в неделю, — не сделка, и узнать это мы
   должны от сервиса.

Запуск:  python3 -m act.tests.test_market
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import (  # noqa: E402
    Agent, Budget, Executor, Governor, Ledger, Registry,
)
from act.npp_act.market import (  # noqa: E402
    client_party, conclude, contractor_party, negotiate, pay_out,
)
from act.npp_act.settlement import (  # noqa: E402
    Book, Leg, SettlementError, money, split_with_fee, to_cents,
)

SERVICE = "freelance-guild"
PORT = 8231
BASE = f"http://127.0.0.1:{PORT}"

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


def next_week() -> str:
    """Неделя, которая точно не прошла: цех отвергает прошедшие недели."""
    d = date.today() + timedelta(days=7)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ────────────────────────────────────────────────────────────────────────────
# 1. Двойная запись: масса денег под 200 расчётами
# ────────────────────────────────────────────────────────────────────────────

def test_mass(tmp: Path) -> None:
    print("\nДвойная запись — масса денег под 200 расчётами:")
    book = Book(tmp / "mass.jsonl")
    names = ["person:anna", "person:bob", "guild:marina", "guild:igor",
             "platform", "escrow:transit"]
    for i, n in enumerate(names):
        book.open(n, initial_cents=(i + 1) * 10_000)
    start_mass = book.total_mass()
    check("начальная масса равна сумме эмиссий",
          start_mass == book.issued == sum((i + 1) * 10_000 for i in range(len(names))),
          f"{start_mass} / {book.issued}")

    # Зерно фиксировано: исход прогона воспроизводим, и упавшая проверка
    # указывает на конкретный расчёт, а не на «иногда ломается».
    rnd = random.Random(20261009)
    settled = aborted = 0
    rolled_back_clean = True
    for i in range(200):
        legs = []
        for _ in range(rnd.randint(1, 3)):
            src, dst = rnd.sample(names, 2)
            legs.append(Leg(src, dst, rnd.randint(1, 4_000), f"плечо {i}"))
        deliver = rnd.random() > 0.2  # пятая часть сделок не подтверждается
        before = {n: book.balance(n) for n in names}
        rec = book.settle(f"stl_{i:03d}", legs, deliver=deliver)
        if rec.ok:
            settled += 1
        else:
            aborted += 1
            after = {n: book.balance(n) for n in names}
            if after != before:
                rolled_back_clean = False
        if book.total_mass() != start_mass:
            check(f"масса сохранилась на расчёте {i}", False,
                  f"{book.total_mass()} ≠ {start_mass}")
            return

    check(f"масса денег сохранилась после 200 расчётов ({settled} прошло, {aborted} откатано)",
          book.total_mass() == start_mass == book.issued,
          f"{book.total_mass()} / {start_mass} / {book.issued}")
    check("все 200 расчётов получили окончательное состояние",
          settled + aborted == 200 and len(book.settlements) == 200,
          f"{settled}+{aborted}, записей {len(book.settlements)}")
    check("ни один откат не оставил следа в остатках", rolled_back_clean)
    check("ни один счёт не ушёл в минус",
          all(book.balance(n) >= 0 for n in names),
          str({n: money(book.balance(n)) for n in names}))
    check("нарушений инвариантов нет", book.verify_invariants() == [],
          str(book.verify_invariants()[:3]))

    # Проверка не на мок: состояние сворачивается из журнала заново.
    again = book.reload()
    check("перечитанная книга даёт те же остатки",
          again.statement() == book.statement())
    check("перечитанная книга тоже без нарушений", again.verify_invariants() == [])


# ────────────────────────────────────────────────────────────────────────────
# 2. Эскроу: обратимое удержание и необратимая выплата
# ────────────────────────────────────────────────────────────────────────────

def test_escrow(tmp: Path) -> None:
    print("\nЭскроу — удержание обратимо, выплата один раз:")
    book = Book(tmp / "escrow.jsonl")
    book.open("person:anna", 100_00)
    book.open("guild:marina")
    book.open("platform")

    book.reserve("person:anna", 60_00, "esc_a")
    check("удержание не двигает деньги, но делает их недоступными",
          book.balance("person:anna") == 100_00 and book.available("person:anna") == 40_00,
          f"{book.balance('person:anna')} / {book.available('person:anna')}")
    check("удержание выше доступного невозможно",
          _raises(lambda: book.reserve("person:anna", 50_00, "esc_b")))

    book.reserve("person:anna", 10_00, "esc_c")
    book.release("esc_c")
    check("после отпускания удержания деньги снова доступны",
          book.available("person:anna") == 40_00, str(book.available("person:anna")))

    legs = split_with_fee("person:anna", "guild:marina", "platform", 60_00, fee_bps=500)
    rec = book.capture("esc_a", legs, settlement_id="stl_a")
    check("выплата прошла двумя плечами: исполнителю и платформе",
          rec.ok and book.balance("guild:marina") == 57_00 and book.balance("platform") == 3_00,
          f"{rec.state}: {money(book.balance('guild:marina'))} / {money(book.balance('platform'))}")
    check("комиссия не выдумала денег: масса сохранилась",
          book.total_mass() == book.issued == 100_00)

    check("второй capture того же эскроу невозможен",
          _raises(lambda: book.capture("esc_a", legs, settlement_id="stl_a2")))
    check("после выплаты остатки не изменились повторной попыткой",
          book.balance("guild:marina") == 57_00 and book.balance("platform") == 3_00)
    check("выплаченный эскроу нельзя отпустить", _raises(lambda: book.release("esc_a")))
    check("закрытый ключ эскроу не переиспользуется",
          _raises(lambda: book.reserve("person:anna", 60_00, "esc_a")))

    bad = [Leg("person:anna", "guild:marina", 10_00)]
    book.reserve("person:anna", 20_00, "esc_d")
    check("выплата, не сошедшаяся с удержанием, отвергается до движения денег",
          _raises(lambda: book.capture("esc_d", bad)))
    check("после отказа эскроу остался удержанным",
          book.escrows["esc_d"].active and book.available("person:anna") == 20_00,
          str(book.available("person:anna")))
    check("инварианты целы", book.verify_invariants() == [], str(book.verify_invariants()))


# ────────────────────────────────────────────────────────────────────────────
# 3. Сага: компенсация, идемпотентность, реверс
# ────────────────────────────────────────────────────────────────────────────

def test_saga(tmp: Path) -> None:
    print("\nSaga-клиринг — сбой плеча откатывает всё:")
    book = Book(tmp / "saga.jsonl")
    book.open("client", 50_00)
    book.open("transit")
    book.open("worker")
    book.open("platform")

    # Три плеча, третье неисполнимо: на transit к тому моменту лежит 30.00,
    # а просят 99.00. Первые два обязаны откатиться.
    rec = book.settle("s1", [
        Leg("client", "transit", 30_00, "в транзит"),
        Leg("transit", "worker", 20_00, "исполнителю"),
        Leg("transit", "platform", 99_00, "неисполнимая комиссия"),
    ])
    check("сага отвергнута целиком", not rec.ok and "недостаточно" in rec.reason, rec.reason)
    check("плечи, прошедшие до сбоя, откатаны",
          book.balance("client") == 50_00 and book.balance("transit") == 0
          and book.balance("worker") == 0,
          str(book.statement()))
    check("компенсация видна в журнале, а не затёрта",
          any(r["kind"] == "transfer" and r["payload"].get("ref") == "s1:comp" for r in book),
          "нет компенсирующих проводок")

    rec = book.settle("s2", [Leg("client", "worker", 10_00)], deliver=False)
    check("неподтверждённая поставка откатывает расчёт",
          not rec.ok and "поставка" in rec.reason and book.balance("worker") == 0,
          rec.reason)

    ok1 = book.settle("s3", [Leg("client", "worker", 12_00, "оплата")])
    before = book.statement()
    ok2 = book.settle("s3", [Leg("client", "worker", 12_00, "оплата")])
    check("расчёт идемпотентен по ключу: повтор не исполняется второй раз",
          ok1.ok and ok2.ok and book.statement() == before
          and book.balance("worker") == 12_00,
          str(book.statement()))
    check("повтор вернул тот же расчёт, а не новый",
          ok2.id == ok1.id and len([s for s in book.settlements if s == "s3"]) == 1)

    rev = book.reverse("s3")
    check("реверс состоявшегося расчёта вернул деньги",
          rev.ok and book.balance("worker") == 0 and book.balance("client") == 50_00,
          f"{rev.state}: {book.statement()}")
    check("повторный реверс возвращает тот же результат",
          book.reverse("s3").id == rev.id)

    book.settle("s4", [Leg("client", "worker", 5_00)])
    book.settle("s5", [Leg("worker", "platform", 5_00)])
    rev2 = book.reverse("s4")
    check("реверс невозможен, если получатель уже распорядился деньгами",
          not rev2.ok and "распорядился" in rev2.reason, rev2.reason)
    check("неудавшийся реверс не оставил следа",
          book.balance("worker") == 0 and book.balance("platform") == 5_00,
          str(book.statement()))
    check("инварианты целы после всех саг", book.verify_invariants() == [],
          str(book.verify_invariants()))


# ────────────────────────────────────────────────────────────────────────────
# 4. Перезапуск: прерванная сага обязана быть видна
# ────────────────────────────────────────────────────────────────────────────

def test_restart(tmp: Path) -> None:
    print("\nПерезапуск — состояние расчётов на диске:")
    path = tmp / "restart.jsonl"
    book = Book(path)
    book.open("client", 80_00)
    book.open("worker")
    book.reserve("client", 30_00, "esc_live")
    book.settle("done", [Leg("client", "worker", 10_00, "аванс")])

    revived = Book(path)
    check("остатки пережили перезапуск",
          revived.balance("client") == 70_00 and revived.balance("worker") == 10_00,
          str(revived.statement()))
    check("удержание пережило перезапуск",
          revived.escrows["esc_live"].active and revived.available("client") == 40_00,
          str(revived.available("client")))
    check("состоявшийся расчёт найден по ключу",
          revived.settlements["done"].ok)
    check("восстановленная книга без нарушений", revived.verify_invariants() == [])

    # Имитация смерти процесса: из журнала убирается последняя запись —
    # закрытие саги. Это не подделка данных, а ровно то, что остаётся на диске,
    # если процесс умер между проводкой и закрытием расчёта.
    book2 = Book(path)
    book2.settle("torn", [Leg("client", "worker", 7_00), Leg("worker", "client", 2_00)])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert '"saga.end"' in lines[-1]
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    torn = Book(path)
    check("прерванная сага обнаружена при загрузке",
          [s.id for s in torn.interrupted()] == ["torn"],
          str([(s.id, s.state) for s in torn.settlements.values()]))
    check("прерванная сага названа нарушением инварианта",
          any("прерван" in v for v in torn.verify_invariants()),
          str(torn.verify_invariants()))
    check("повторить прерванный расчёт нельзя до восстановления",
          _raises(lambda: torn.settle("torn", [Leg("client", "worker", 7_00)])))

    healed = torn.recover()
    check("восстановление компенсировало применённые плечи", healed == ["torn"], str(healed))
    check("после восстановления остатки вернулись к состоянию до саги",
          torn.balance("client") == 70_00 and torn.balance("worker") == 10_00,
          str(torn.statement()))
    check("после восстановления нарушений нет", torn.verify_invariants() == [],
          str(torn.verify_invariants()))


# ────────────────────────────────────────────────────────────────────────────
# 5. Переговоры: сходимость, расхождение, детерминизм
# ────────────────────────────────────────────────────────────────────────────

def test_negotiation() -> None:
    print("\nПереговоры — уступки, резервы, детерминизм:")
    client = client_party("person:anna", max_price_cents=700_00, want_price_cents=400_00,
                          max_term=14, want_term=6, min_quality=3, want_quality=5)
    marina = contractor_party("guild:marina", min_price_cents=450_00, want_price_cents=900_00,
                              min_term=8, want_term=16, max_quality=4, want_quality=2)

    out = negotiate(client, marina, rounds=8)
    check("при пересекающихся резервных ценах сделка состоялась",
          out.agreed, out.reason)
    deal = out.deal
    check("цена сделки внутри резервов обеих сторон",
          450_00 <= deal.price_cents <= 700_00, str(deal.price_cents))
    check("срок сделки внутри допустимых диапазонов",
          8 <= deal.offer.term <= 14, str(deal.offer.term))
    check("качество сделки внутри допустимых диапазонов",
          3 <= deal.offer.quality <= 4, str(deal.offer.quality))
    check("сделка обеим сторонам не хуже резерва",
          all(u >= 0 for u in deal.utilities.values()), str(deal.utilities))

    # Уступки: цена в предложениях продавца не растёт, покупателя — не падает.
    asks = [m.offer.price_cents for m in out.moves
            if m.profile == marina.profile and m.kind in ("open", "counter")]
    bids = [m.offer.price_cents for m in out.moves
            if m.profile == client.profile and m.kind == "counter"]
    check("продавец уступает монотонно",
          all(a >= b for a, b in zip(asks, asks[1:])), str([money(a) for a in asks]))
    check("покупатель уступает монотонно",
          all(a <= b for a, b in zip(bids, bids[1:])), str([money(b) for b in bids]))
    check("стороны уступали обе, а не одна",
          len(set(asks)) > 1 and len(set(bids)) > 1)

    again = negotiate(
        client_party("person:anna", max_price_cents=700_00, want_price_cents=400_00,
                     max_term=14, want_term=6, min_quality=3, want_quality=5),
        contractor_party("guild:marina", min_price_cents=450_00, want_price_cents=900_00,
                         min_term=8, want_term=16, max_quality=4, want_quality=2),
        rounds=8)
    check("торг детерминирован: тот же вход — тот же исход",
          again.deal.offer.key() == deal.offer.key()
          and again.transcript() == out.transcript(),
          f"{again.deal.offer} vs {deal.offer}")

    greedy = contractor_party("guild:igor", min_price_cents=900_00, want_price_cents=1500_00,
                              min_term=8, want_term=16)
    miss = negotiate(client_party("person:anna", max_price_cents=700_00,
                                  want_price_cents=400_00, max_term=14, want_term=6),
                     greedy, rounds=8)
    check("при непересекающихся резервных ценах переговоры расходятся", not miss.agreed)
    check("расхождение называет измерение, на котором разошлись",
          "цена" in miss.reason, miss.reason)
    check("у расхождения есть стенограмма — объяснимый отказ",
          len(miss.transcript()) >= 8 and miss.transcript()[-1]["kind"] == "reject")

    # Свойство, которое обязано держаться на всей сетке параметров, а не в
    # одном удачном примере: сделка есть тогда и только тогда, когда резервы
    # пересеклись, и цена всегда внутри обоих пределов.
    broken = []
    for buyer_max in range(300_00, 900_00, 100_00):
        for seller_min in range(250_00, 950_00, 100_00):
            for beta in (0.6, 1.0, 1.8):
                b = client_party("person:b", max_price_cents=buyer_max,
                                 want_price_cents=200_00, max_term=14, want_term=6, beta=beta)
                s = contractor_party("guild:s", min_price_cents=seller_min,
                                     want_price_cents=1000_00, min_term=8, want_term=16)
                res = negotiate(b, s, rounds=8)
                overlap = seller_min <= buyer_max
                if res.agreed != overlap:
                    broken.append((buyer_max, seller_min, beta, res.agreed, overlap))
                elif res.agreed and not (seller_min <= res.deal.price_cents <= buyer_max):
                    broken.append((buyer_max, seller_min, beta, res.deal.price_cents))
    check(f"на всей сетке параметров ({6 * 7 * 3} прогонов) сделка ⇔ пересечение резервов",
          not broken, str(broken[:3]))


# ────────────────────────────────────────────────────────────────────────────
# 6. Сделка против живого сервиса: обязательство в обоих журналах
# ────────────────────────────────────────────────────────────────────────────

def build(tmp: Path, profile: str, limit: float) -> tuple[Agent, Governor, Ledger]:
    reg = Registry().load_dir(ROOT / "act/manifests").rebind(SERVICE, BASE)
    led = Ledger(tmp / f"{profile.replace(':', '_')}.jsonl", owner=profile)
    gov = Governor(reg, led, Budget(limit))
    return Agent(profile, Executor(reg, gov, led)), gov, led


def http(method: str, path: str, body: dict | None = None,
         key: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body or {}).encode() if method != "GET" else None
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_live_deal(tmp: Path) -> None:
    print("\nСделка против живого цеха — обязательство и расчёт:")
    client, client_gov, client_led = build(tmp, "person:anna", 10_000.0)
    marina_agent, marina_gov, marina_led = build(tmp, "guild:marina", 10_000.0)

    # Книга расчётов — сторона заказчика. Эскроу цеха и эскроу книги живут
    # параллельно сознательно: сервис удерживает своё обязательство, книга —
    # свои деньги, и сверить их должен именно инвариант, а не доверие.
    book = Book(tmp / "deal.jsonl")
    book.open("person:anna", 2_000_00)
    book.open("guild:marina")
    book.open("platform")

    rows = client.read(SERVICE, "contractor.list", {})
    check("каталог исполнителей прочитан у живого сервиса",
          rows is not None and rows.ok and len(rows.body) >= 3, str(rows and rows.status))
    marina = next(r for r in rows.body if r["hours_per_week"] == 20)
    check("ёмкость исполнителя взята из сервиса, а не придумана",
          marina["free_hours"] == 20, str(marina))

    # Торг. Предел исполнителя опирается на его ставку из сервиса: 45.00/час.
    rate = to_cents(marina["rate"])
    buyer = client_party("person:anna", max_price_cents=700_00, want_price_cents=400_00,
                         max_term=14, want_term=6, min_quality=3, want_quality=5)
    seller = contractor_party("guild:marina", min_price_cents=10 * rate,
                              want_price_cents=20 * rate,
                              min_term=8, want_term=16, max_quality=4, want_quality=2)
    out = negotiate(buyer, seller, rounds=8)
    check("агенты договорились", out.agreed, out.reason)
    deal = out.deal
    print(f"    договорились: {deal.offer} за {deal.round} раунд(ов), "
          f"принял {deal.accepted_by}")

    week = next_week()
    dec, res = client.act(SERVICE, "brief.create", {
        "client_token": f"brief-{deal.fingerprint(['person:anna', 'guild:marina'])}",
        "client": "Анна Иванова", "title": "Вёрстка лендинга",
        "spec": f"качество {deal.offer.quality}, {deal.offer.term} ч, неделя {week}",
        "budget_cap": 700.0,
    }, key=f"brief-{deal.fingerprint(['person:anna', 'guild:marina'])}")
    check("бриф создан живым сервисом", dec.admitted and res.ok, dec.reason)
    brief = res.body["brief_token"]

    dec, hold = client.hold(SERVICE, "quote.request",
                            {"brief_token": brief, "contractor_id": marina["id"]})
    check("запрос оценки удержан обратимо", dec.admitted and hold is not None and not hold.expired,
          dec.reason)

    # Оценку даёт АГЕНТ ИСПОЛНИТЕЛЯ, под своим губернатором и своим журналом:
    # две независимые стороны, а не одна, играющая в две руки. Перед тем как
    # связать себя ценой, он читает собственную ёмкость у сервиса — и это же
    # первое взаимодействие с сервисом, без которого губернатор эскалировал бы
    # обязательство как первое (мягкий предикат S4).
    cap = marina_agent.read(SERVICE, "capacity.get",
                            {"contractor_id": marina["id"], "weeks": 3})
    check("исполнитель сверил ёмкость у сервиса перед оценкой",
          cap is not None and cap.ok and cap.body["hours_per_week"] == 20,
          str(cap and cap.body)[:120])
    free = next(w["free_hours"] for w in cap.body["weeks"] if w["week"] == week)
    check("договорённый срок укладывается в свободные часы недели",
          deal.offer.term <= free, f"{deal.offer.term} > {free}")

    qkey = f"quote-{deal.fingerprint(['guild:marina'])}"
    d_no = marina_gov.evaluate(SERVICE, "quote.give", {"request_id": hold.hold_id},
                               idempotency_key=qkey)
    check("оценка без подтверждения исполнителя не допущена",
          d_no.verdict == "escalate" and "подтверждени" in d_no.reason, d_no.reason)
    marina_agent.accept(SERVICE, "quote.give", qkey)
    dec, res = marina_agent.act(SERVICE, "quote.give", {
        "request_id": hold.hold_id, "price": deal.offer.price,
        "hours": deal.offer.term, "week": week,
    }, key=qkey)
    check("оценка дана по договорённой цене", dec.admitted and res.ok, str(res and res.body))
    check("цена доехала до сервиса с точностью до цента",
          res.body["price_cents"] == deal.price_cents,
          f"{res.body['price_cents']} ≠ {deal.price_cents}")
    quote = res.body["quote_token"]

    ekey = f"escrow-{deal.fingerprint(['person:anna'])}"
    client.accept(SERVICE, "escrow.fund", ekey)
    dec, res = client.act(SERVICE, "escrow.fund", {
        "brief_token": brief, "amount": deal.offer.price, "max_money": deal.offer.price,
    }, key=ekey)
    check("эскроу цеха внесён до работы", dec.admitted and res.ok and res.body["state"] == "held",
          dec.reason)
    escrow = res.body["escrow_token"]

    # ---- главный шаг: сделка → двустороннее обязательство + удержание денег ----
    done = conclude(
        out, initiator=client, counterparty=marina_agent,
        service=SERVICE, verb="contract.sign",
        payload={"brief_token": brief, "quote_token": quote, "escrow_token": escrow,
                 "max_money": deal.offer.price},
        book=book, payer="person:anna", payee="guild:marina", platform="platform",
        fee_bps=500, subject=f"вёрстка лендинга, неделя {week}",
    )
    check("обязательство оформлено", done.ok, done.reason)
    check("обязательство записано в журналы ОБЕИХ сторон",
          done.commitment is not None and done.commitment.verified_by(
              {"person:anna": client_led, "guild:marina": marina_led}),
          str(done.commitment))
    check("в обязательстве обе стороны",
          done.commitment is not None and
          sorted(done.commitment.parties) == ["guild:marina", "person:anna"])

    # Доказательство персистентности: обязательство проверяется по журналам,
    # перечитанным с диска, а не по объектам в памяти этого процесса.
    check("обязательство подтверждается журналами, перечитанными с диска",
          done.commitment.verified_by({"person:anna": client_led.reload(),
                                       "guild:marina": marina_led.reload()}))
    ids = [r.payload["commitment_id"] for r in client_led.by_kind("commitment")]
    ids_m = [r.payload["commitment_id"] for r in marina_led.by_kind("commitment")]
    check("идентификатор обязательства у сторон один и тот же",
          ids and ids == ids_m == [done.commitment.id], f"{ids} / {ids_m}")
    check("стенограмма торга попала в журнал инициатора",
          any(r.payload.get("kind") == "negotiation" for r in client_led.by_kind("outcome")))

    status, view = http("GET", f"/api/contracts/{_token(client_led)}")
    check("контракт существует на живом сервисе", status == 200 and view["status"] == "signed",
          str((status, view))[:120])
    check("цена контракта равна договорённой до цента",
          to_cents(view["price"]) == deal.price_cents, f"{view['price']} vs {deal.offer.price}")
    check("ёмкость исполнителя уменьшилась на договорённые часы",
          view["hours"] == deal.offer.term, str(view.get("hours")))

    check("деньги удержаны, но не выплачены",
          book.escrows[done.escrow_id].active
          and book.balance("guild:marina") == 0
          and book.available("person:anna") == 2_000_00 - deal.price_cents,
          str(book.statement()))

    # Повтор той же сделки не создаёт второго обязательства и не снимает
    # обеспечение с уже подписанного контракта.
    repeat = conclude(
        out, initiator=client, counterparty=marina_agent,
        service=SERVICE, verb="contract.sign",
        payload={"brief_token": brief, "quote_token": quote, "escrow_token": escrow,
                 "max_money": deal.offer.price},
        book=book, payer="person:anna", payee="guild:marina", platform="platform",
        fee_bps=500, subject=f"вёрстка лендинга, неделя {week}",
    )
    check("повтор сделки не исполняется второй раз",
          not repeat.ok and "уже оформлена" in repeat.reason, repeat.reason)
    check("повтор не снял обеспечение с живого контракта",
          book.escrows[done.escrow_id].active
          and len(client_led.by_kind("commitment")) == 1,
          str(book.escrows[done.escrow_id]))

    # ---- эскроу имеет смысл только пока отказывает ----
    pkey = "pay-before-accept"
    client.accept(SERVICE, "payment.release", pkey)
    dec, res = client.act(SERVICE, "payment.release",
                          {"contract_token": _token(client_led),
                           "max_money": deal.offer.price}, key=pkey)
    check("живой сервис отказал в выплате до приёмки",
          dec.admitted and res is not None and not res.ok and res.status == 409,
          str(res and res.body))
    check("книга расчётов тоже ничего не выплатила",
          book.balance("guild:marina") == 0)

    # ---- работа, приёмка, выплата ----
    dkey = "deliver-1"
    dec, res = marina_agent.act(SERVICE, "work.deliver", {
        "contract_token": _token(client_led), "artifact": "landing.zip", "note": "готово",
    }, key=dkey)
    check("исполнитель сдал работу", dec.admitted and res.ok, str(res and res.body)[:100])

    akey = "accept-1"
    client.accept(SERVICE, "work.accept", akey)
    dec, res = client.act(SERVICE, "work.accept",
                          {"contract_token": _token(client_led)}, key=akey)
    check("заказчик принял работу", dec.admitted and res.ok and res.body["status"] == "accepted",
          str(res and res.body)[:100])

    pkey2 = "pay-after-accept"
    client.accept(SERVICE, "payment.release", pkey2)
    dec, res = client.act(SERVICE, "payment.release",
                          {"contract_token": _token(client_led),
                           "max_money": deal.offer.price}, key=pkey2)
    check("после приёмки сервис выплатил эскроу",
          dec.admitted and res.ok and res.body["status"] == "paid", str(res and res.body)[:120])

    stl = pay_out(book, done.escrow_id, payer="person:anna", payee="guild:marina",
                  platform="platform", fee_bps=500, settlement_id=done.settlement_id)
    fee = deal.price_cents * 500 // 10_000
    check("расчёт прошёл сагой из двух плеч",
          stl.ok and book.balance("guild:marina") == deal.price_cents - fee
          and book.balance("platform") == fee,
          f"{stl.state}: {book.statement()}")
    check("масса денег сохранилась и после выплаты",
          book.total_mass() == book.issued == 2_000_00)
    check("после выплаты удержаний не осталось",
          book.available("person:anna") == book.balance("person:anna"))
    check("нарушений инвариантов нет", book.verify_invariants() == [],
          str(book.verify_invariants()))

    revived = book.reload()
    check("расчёт сделки пережил перезапуск",
          revived.settlements[done.settlement_id].ok
          and revived.statement() == book.statement()
          and revived.verify_invariants() == [],
          str(revived.statement()))


def _token(led: Ledger) -> str:
    """Токен контракта — из ответа сервиса, записанного в журнал исходов."""
    for r in reversed(list(led.by_kind("outcome"))):
        body = r.payload.get("response")
        if isinstance(body, dict) and body.get("contract_token"):
            return str(body["contract_token"])
    raise AssertionError("в журнале нет контракта")


# ────────────────────────────────────────────────────────────────────────────
# 7. Рынок не отменяет реальность
# ────────────────────────────────────────────────────────────────────────────

def test_market_cannot_override_reality(tmp: Path) -> None:
    print("\nДоговорённость против ёмкости — сервис сильнее рынка:")
    client, _, led = build(tmp, "person:bob", 10_000.0)
    igor_agent, _, _ = build(tmp, "guild:igor", 10_000.0)

    rows = client.read(SERVICE, "contractor.list", {})
    igor = next(r for r in rows.body if r["hours_per_week"] == 10)
    check("у исполнителя в сервисе десять часов в неделю", igor["hours_per_week"] == 10)

    # Агенты договариваются о двенадцати часах. По их функциям полезности это
    # отличная сделка — и она неисполнима: часов столько не существует.
    buyer = client_party("person:bob", max_price_cents=900_00, want_price_cents=500_00,
                         max_term=16, want_term=11)
    seller = contractor_party("guild:igor", min_price_cents=400_00, want_price_cents=1000_00,
                              min_term=11, want_term=16)
    out = negotiate(buyer, seller, rounds=8)
    check("агенты договорились о сроке сверх ёмкости",
          out.agreed and out.deal.offer.term > igor["hours_per_week"],
          str(out.deal and out.deal.offer))

    week = next_week()
    dec, res = client.act(SERVICE, "brief.create", {
        "client_token": "brief-over-capacity", "client": "Борис",
        "title": "Миграция данных", "spec": f"{out.deal.offer.term} ч", "budget_cap": 900.0,
    }, key="brief-over-capacity")
    check("бриф создан", dec.admitted and res.ok, dec.reason)
    brief = res.body["brief_token"]

    _, hold = client.hold(SERVICE, "quote.request",
                          {"brief_token": brief, "contractor_id": igor["id"]})
    igor_agent.read(SERVICE, "capacity.get", {"contractor_id": igor["id"], "weeks": 3})
    qkey = "quote-over-capacity"
    igor_agent.accept(SERVICE, "quote.give", qkey)
    dec, res = igor_agent.act(SERVICE, "quote.give", {
        "request_id": hold.hold_id, "price": out.deal.offer.price,
        "hours": out.deal.offer.term, "week": week,
    }, key=qkey)
    check("живой сервис отверг неисполнимую договорённость",
          dec.admitted and res is not None and not res.ok and res.status == 409,
          str(res and res.body))
    check("отказ назвал причину: недельная ёмкость",
          isinstance(res.body, dict) and "ёмкост" in str(res.body.get("error", "")),
          str(res.body))
    check("обязательства ни у кого не возникло", not led.by_kind("commitment"))


def test_divergence_changes_nothing(tmp: Path) -> None:
    print("\nРасхождение — мир остался нетронутым:")
    client, _, client_led = build(tmp, "person:cara", 500.0)
    guild, _, guild_led = build(tmp, "guild:olga", 500.0)
    book = Book(tmp / "diverged.jsonl")
    book.open("person:cara", 100_00)
    book.open("guild:olga")

    out = negotiate(
        client_party("person:cara", max_price_cents=300_00, want_price_cents=200_00,
                     max_term=14, want_term=6),
        contractor_party("guild:olga", min_price_cents=800_00, want_price_cents=1200_00,
                         min_term=8, want_term=16),
        rounds=8)
    done = conclude(out, initiator=client, counterparty=guild, service=SERVICE,
                    verb="contract.sign", payload={"brief_token": "нет"},
                    book=book, payer="person:cara", payee="guild:olga")
    check("без сделки обязательства нет", not done.ok and done.commitment is None)
    check("деньги не удержаны", book.escrows == {} and book.available("person:cara") == 100_00)
    check("сервис не вызывался: в журналах нет исполнений",
          not client_led.by_kind("execution") and not guild_led.by_kind("execution"),
          f"{len(client_led.by_kind('execution'))} / {len(guild_led.by_kind('execution'))}")
    check("причина расхождения названа", "цена" in done.reason, done.reason)


def test_failed_commitment_releases_money(tmp: Path) -> None:
    print("\nНесостоявшееся обязательство — деньги не залипают:")
    client, _, client_led = build(tmp, "person:dana", 10_000.0)
    guild, _, _ = build(tmp, "guild:nobody", 10_000.0)
    book = Book(tmp / "failed.jsonl")
    book.open("person:dana", 1_000_00)
    book.open("guild:nobody")

    out = negotiate(
        client_party("person:dana", max_price_cents=700_00, want_price_cents=400_00,
                     max_term=14, want_term=6),
        contractor_party("guild:nobody", min_price_cents=450_00, want_price_cents=900_00,
                         min_term=8, want_term=16),
        rounds=8)
    check("сделка состоялась в переговорах", out.agreed)

    # Обе стороны сначала читают сервис: иначе до его отказа дело не дойдёт —
    # губернатор эскалирует первое обязывающее взаимодействие сам, и проверялся
    # бы наш гейт, а не поведение живого сервиса.
    client.read(SERVICE, "contractor.list", {})
    guild.read(SERVICE, "contractor.list", {})

    # Контракт подписать не на что: брифа с таким токеном в живом сервисе нет,
    # и сервис обязан ответить отказом. Удержание денег обязано быть снято.
    done = conclude(out, initiator=client, counterparty=guild, service=SERVICE,
                    verb="contract.sign",
                    payload={"brief_token": "нет-такого", "quote_token": "нет",
                             "escrow_token": "нет", "max_money": out.deal.offer.price},
                    book=book, payer="person:dana", payee="guild:nobody")
    check("обязательство не оформлено", not done.ok, done.reason)
    check("отказ пришёл от живого сервиса, а не от нашего губернатора",
          done.decision is not None and done.decision.admitted
          and any(r.payload.get("verb") == "contract.sign" and r.payload.get("ok") is False
                  for r in client_led.by_kind("execution")),
          str(done.decision))
    check("удержание отпущено: деньги снова доступны",
          book.available("person:dana") == 1_000_00
          and book.escrows[done.escrow_id].state == "released",
          str(book.statement()))
    check("масса денег не пострадала", book.total_mass() == book.issued == 1_000_00)
    check("инварианты целы", book.verify_invariants() == [], str(book.verify_invariants()))

    # Осознанная вторая попытка берёт свой ключ и снова удерживает деньги.
    retry = conclude(out, initiator=client, counterparty=guild, service=SERVICE,
                     verb="contract.sign", payload={"brief_token": "снова-нет"},
                     book=book, payer="person:dana", payee="guild:nobody", attempt="2")
    check("повторная попытка получила отдельный ключ",
          retry.escrow_id != done.escrow_id and not retry.ok, retry.reason)
    check("и её удержание тоже отпущено",
          book.available("person:dana") == 1_000_00, str(book.statement()))


def _raises(fn) -> bool:
    try:
        fn()
    except SettlementError:
        return True
    return False


# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    db = Path(tempfile.gettempdir()) / "npp_market_test.db"
    if db.exists():
        db.unlink()
    proc = subprocess.Popen(
        [sys.executable, "-m", "act.services.freelance.server",
         "--port", str(PORT), "--db", str(db), "--reset"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_up(f"{BASE}/api/health"):
            print("✗ сервис цеха не поднялся")
            return 1
        print(f"Сервис цеха поднят на :{PORT} — вторая сторона сделки настоящая")
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            test_mass(tmp)
            test_escrow(tmp)
            test_saga(tmp)
            test_restart(tmp)
            test_negotiation()
            test_live_deal(tmp)
            test_market_cannot_override_reality(tmp)
            test_divergence_changes_nothing(tmp)
            test_failed_commitment_releases_money(tmp)
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
