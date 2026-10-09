"""Проверка цеха — Actionable-сервиса сферы услуг.

Дисциплина та же, что в act/tests/test_act.py, и по той же причине: сервис не
вправе проверять себя против собственного мока. Здесь поднимается НАСТОЯЩИЙ
сервис подпроцессом, и каждая проверка идёт по сети. Отдельно проверяется то,
что мок не поймал бы в принципе: что ВСЕ объявленные в манифесте биндинги
действительно существуют на живом сервисе, и что обобщённый агент из npp_act
работает с цехом без единой правки под него.

(В аудите экосистемы самосертификация оказалась главным способом обмануть себя:
 plugin-marketplace имеет 14/14 зелёных и при этом отвергает все настоящие
 бэкенды, потому что его мок не валидирует то, что валидирует контракт.)

Запуск:  python3 -m act.tests.test_freelance
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import (  # noqa: E402
    Agent, Budget, Executor, Governor, Ledger, Registry, load_manifest,
)

SERVICE = "freelance-guild"
MANIFEST_PATH = ROOT / "act/manifests/freelance.act.json"
BASE = ""  # подставляется в main()

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
# HTTP-клиент теста: ничего, кроме стандартной библиотеки
# ────────────────────────────────────────────────────────────────────────────

def call(method: str, path: str, body: dict | None = None,
         key: str | None = None) -> tuple[int, dict | list]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": raw[:200]}


def week_of(offset_weeks: int) -> str:
    d = date.today() + timedelta(days=7 * offset_weeks)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def capacity(contractor_id: int, week: str) -> dict:
    _, body = call("GET", f"/api/capacity?contractor_id={contractor_id}&weeks=8")
    for row in body["weeks"]:
        if row["week"] == week:
            return row
    return {}


def prepare(tag: str, contractor_id: int, hours: int, price: float,
            week: str, budget: float | None = None) -> dict:
    """Довести сценарий до момента перед подписанием: бриф, оценка, эскроу."""
    st, brief = call("POST", "/api/briefs", {
        "client": f"Заказчик {tag}", "title": f"Задача {tag}",
        "spec": "описание работ", "budget_cap": budget or price,
        "client_token": f"ct_{tag}",
    })
    assert st == 201, (st, brief)
    st, req = call("POST", "/api/quote-requests",
                   {"brief_token": brief["brief_token"], "contractor_id": contractor_id})
    assert st == 201, (st, req)
    st, quote = call("POST", "/api/quotes", {
        "request_id": req["request_id"], "price": price, "hours": hours, "week": week,
    }, key=f"q_{tag}")
    if st != 201:
        return {"brief": brief["brief_token"], "quote_status": st, "quote": quote}
    st, esc = call("POST", "/api/escrow",
                   {"brief_token": brief["brief_token"], "amount": price}, key=f"e_{tag}")
    assert st == 201, (st, esc)
    return {
        "brief": brief["brief_token"], "request": req["request_id"],
        "quote": quote["quote_token"], "escrow": esc["escrow_token"],
        "quote_status": 201, "price": price, "hours": hours, "week": week,
    }


def sign(tag: str, chain: dict) -> tuple[int, dict]:
    return call("POST", "/api/contracts", {
        "brief_token": chain["brief"], "quote_token": chain["quote"],
        "escrow_token": chain["escrow"],
    }, key=f"c_{tag}")


# ────────────────────────────────────────────────────────────────────────────
# 1. Манифест: объявленные последствия жизненного цикла услуги
# ────────────────────────────────────────────────────────────────────────────

def test_manifest() -> None:
    print("\nМанифест цеха — последствия жизненного цикла:")
    man = load_manifest(MANIFEST_PATH)
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    check("манифест цеха загружен", man.service == SERVICE, man.service)
    check("профиль — посредник, а не продавец", man.profile == "broker", man.profile)
    check("объявлено 19 глаголов", len(man.capabilities) == 19, str(len(man.capabilities)))

    lifecycle = raw.get("lifecycle", [])
    check("жизненный цикл объявлен в манифесте", len(lifecycle) == 9, str(len(lifecycle)))
    check("каждый шаг цикла объявлен глаголом",
          all(man.verb(step) is not None for step in lifecycle),
          str([s for s in lifecycle if man.verb(s) is None]))

    # §4.2: многошаговый сценарий MUST начинаться с обратимых шагов.
    steps = [man.verb(s) for s in lifecycle]
    first_irreversible = next(i for i, c in enumerate(steps) if not c.reversible)
    check("цикл начинается с обратимых шагов (их 5 до первого необратимого)",
          first_irreversible == 5, f"первый необратимый — №{first_irreversible}")
    check("первый необратимый шаг — сдача работы",
          lifecycle[first_irreversible] == "work.deliver", lifecycle[first_irreversible])

    sign_cap = man.verb("contract.sign")
    check("контракт — двустороннее обязательство", sign_cap.consent == "two_party")
    check("контракт обратим расторжением", sign_cap.reverse == "contract.cancel")
    check("обратимость контракта объявлена ЧАСТИЧНОЙ (ёмкость не возвращается)",
          any(c["id"] == "contract.sign" and c.get("reverse_is_partial") is True
              for c in raw["capabilities"]))

    qreq, qgive = man.verb("quote.request"), man.verb("quote.give")
    check("запрос оценки — удержание с объявленным сроком",
          qreq.effect == "reserve" and qreq.expires_s == 300)
    check("оценка — обязательство исполнителя, обратимое до контракта",
          qgive.effect == "commit" and qgive.reversible and qgive.reverse == "quote.revoke")

    fund, refund = man.verb("escrow.fund"), man.verb("escrow.refund")
    check("эскроу двигает деньги обратимо", fund.effect == "money" and fund.reversible)
    check("возврат эскроу объявлен обратным глаголом", fund.reverse == refund.id)

    pay = man.verb("payment.release")
    check("выплата — деньги и необратима", pay.effect == "money" and not pay.reversible)
    check("выплата требует подтверждения", pay.consent == "confirm")
    check("выплата объявила идемпотентность",
          pay.idempotency_slot() == ("header", "Idempotency-Key"))
    check("цена выплаты переменная", pay.money_is_variable)

    revise = man.verb("work.revise")
    check("доработка обратима повторной сдачей",
          revise.reversible and revise.reverse == "work.deliver")

    check("тяжесть монотонна: выплата > контракт > удержание > чтение",
          pay.severity > sign_cap.severity > qreq.severity > man.verb("capacity.get").severity)
    check("все обратные глаголы разрешаются внутри манифеста",
          all(c.reverse is None or man.verb(c.reverse) is not None for c in man))


# ────────────────────────────────────────────────────────────────────────────
# 2. Губернатор над настоящим манифестом цеха
# ────────────────────────────────────────────────────────────────────────────

def build(tmp: Path, limit: float, name: str) -> tuple[Agent, Governor, Ledger]:
    reg = Registry().load_dir(ROOT / "act/manifests")
    if BASE:
        reg.rebind(SERVICE, BASE)
    led = Ledger(tmp / f"{name.replace(':', '_')}.jsonl", owner=name)
    gov = Governor(reg, led, Budget(limit))
    return Agent(name, Executor(reg, gov, led)), gov, led


def test_governor() -> None:
    print("\nГубернатор над глаголами цеха:")
    with tempfile.TemporaryDirectory() as t:
        _, gov, _ = build(Path(t), 1000.0, "person:client")

        d = gov.evaluate(SERVICE, "payment.release", {"max_money": 100})
        check("выплата без ключа идемпотентности заблокирована",
              d.verdict == "block" and "идемпотент" in d.reason, d.reason)

        d = gov.evaluate(SERVICE, "payment.release", {"max_money": 100}, idempotency_key="k1")
        check("выплата без подтверждения — эскалация",
              d.verdict == "escalate" and "подтверждени" in d.reason, d.reason)

        d = gov.evaluate(SERVICE, "contract.sign", {"max_money": 100}, idempotency_key="k2")
        check("контракт без согласия обеих сторон — эскалация",
              d.verdict == "escalate", d.reason)

        d = gov.evaluate(SERVICE, "capacity.get", {"contractor_id": 1})
        check("чтение ёмкости проходит без гейта", d.verdict == "admit", d.reason)

        d = gov.evaluate(SERVICE, "work.subcontract", {})
        check("необъявленный глагол заблокирован", d.verdict == "block", d.reason)

        _, poor_gov, _ = build(Path(t), 50.0, "person:poor")
        d = poor_gov.evaluate(SERVICE, "escrow.fund", {"max_money": 480}, idempotency_key="k3")
        check("эскроу сверх бюджета профиля заблокирован",
              d.verdict == "block" and "бюджет" in d.reason, d.reason)


# ────────────────────────────────────────────────────────────────────────────
# 3. Полный цикл по живому HTTP
# ────────────────────────────────────────────────────────────────────────────

def test_cycle() -> None:
    print("\nЖивой сервис — манифест и каталог компетенций:")
    st, served = call("GET", "/.well-known/npp-act.json")
    on_disk = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    check("сервис публикует манифест по /.well-known/npp-act.json", st == 200, str(st))
    check("опубликованный манифест совпадает с файлом реестра", served == on_disk)

    st, people = call("GET", "/api/contractors")
    check("каталог исполнителей прочитан", st == 200 and len(people) == 3, str(st))
    check("у исполнителя объявлена ёмкость, а не склад",
          all({"hours_per_week", "free_hours"} <= set(p) for p in people))

    print("\nПолный цикл услуги: бриф → оценка → контракт → сдача → доработка → приёмка → выплата:")
    week = week_of(2)
    contractor = 2  # Игорь Лапин, 10 часов в неделю

    st, brief = call("POST", "/api/briefs", {
        "client": "ООО «Ромашка»", "title": "Миграция каталога на новую схему",
        "spec": "перенести 12 тысяч позиций без простоя", "budget_cap": 600,
        "client_token": "ct_main",
    })
    check("бриф создан", st == 201 and brief["status"] == "open", str((st, brief)))
    bt = brief["brief_token"]

    st, replay = call("POST", "/api/briefs", {
        "client": "ООО «Ромашка»", "title": "Миграция каталога на новую схему",
        "budget_cap": 600, "client_token": "ct_main",
    })
    check("повтор брифа с тем же client_token не создал второй",
          replay.get("brief_token") == bt and replay.get("idempotent_replay") is True)

    st, req = call("POST", "/api/quote-requests", {"brief_token": bt, "contractor_id": contractor})
    check("запрос оценки удерживает внимание исполнителя на срок",
          st == 201 and req["ttl_s"] == 300 and req["expires_at"] > "", str((st, req)))

    st, quote = call("POST", "/api/quotes", {
        "request_id": req["request_id"], "price": 480, "hours": 8, "week": week,
    }, key="q_main")
    check("исполнитель дал оценку: цена, часы, неделя",
          st == 201 and quote["price"] == 480.0 and quote["hours"] == 8 and quote["week"] == week,
          str((st, quote)))
    check("оценка имеет срок действия", quote["valid_until"] > "")

    st, esc = call("POST", "/api/escrow", {"brief_token": bt, "amount": 480}, key="e_main")
    check("эскроу удержан до работы", st == 201 and esc["state"] == "held", str((st, esc)))

    st, contract = call("POST", "/api/contracts", {
        "brief_token": bt, "quote_token": quote["quote_token"], "escrow_token": esc["escrow_token"],
    }, key="c_main")
    check("контракт подписан", st == 201 and contract["status"] == "signed", str((st, contract)))
    ct = contract["contract_token"]
    check("ёмкость недели занята обязательством",
          capacity(contractor, week)["committed_hours"] == 8,
          str(capacity(contractor, week)))

    st, again = call("POST", "/api/contracts", {
        "brief_token": bt, "quote_token": quote["quote_token"], "escrow_token": esc["escrow_token"],
    }, key="c_main")
    check("повтор с тем же ключом вернул тот же контракт",
          again.get("contract_token") == ct and again.get("idempotent_replay") is True, str(again))
    check("повтор не занял ёмкость второй раз",
          capacity(contractor, week)["committed_hours"] == 8,
          str(capacity(contractor, week)))

    st, denied = call("POST", f"/api/contracts/{ct}/payment", None, key="p_early")
    check("эскроу нельзя выплатить до приёмки",
          st == 409 and "после приёмки" in denied["error"], str((st, denied)))

    st, first = call("POST", f"/api/contracts/{ct}/deliveries",
                     {"artifact": "migration-01.sql", "note": "первая версия"}, key="d_1")
    check("работа сдана", st == 201 and first["revision"] == 0, str((st, first)))

    _, rep = call("GET", f"/api/reputation?contractor_id={contractor}")
    check("после сдачи репутации ещё нет", rep["completed_contracts"] == 0, str(rep))

    st, back = call("POST", f"/api/contracts/{ct}/revision",
                    {"comment": "нет индексов на внешние ключи"}, key="r_1")
    check("заказчик вернул работу на доработку",
          st == 200 and back["status"] == "in_work" and back["revisions"] == 1, str((st, back)))
    check("возврат не разорвал контракт", back["contract_alive"] is True)

    _, view = call("GET", f"/api/contracts/{ct}")
    check("при доработке ёмкость остаётся занятой",
          capacity(contractor, week)["committed_hours"] == 8)
    check("при доработке эскроу остаётся удержанным", view["escrow_state"] == "held")

    st, second = call("POST", f"/api/contracts/{ct}/deliveries",
                      {"artifact": "migration-02.sql", "note": "индексы добавлены"}, key="d_2")
    check("повторная сдача после доработки принята сервисом",
          st == 201 and second["revision"] == 1, str((st, second)))

    st, accepted = call("POST", f"/api/contracts/{ct}/acceptance", None, key="a_1")
    check("работа принята", st == 200 and accepted["status"] == "accepted", str((st, accepted)))

    _, rep2 = call("GET", f"/api/reputation?contractor_id={contractor}")
    check("репутация выросла ТОЛЬКО после приёмки",
          rep2["completed_contracts"] == 1 and rep2["hours_delivered"] == 8, str(rep2))
    check("доработка учтена в репутации как факт, а не как провал",
          rep2["revisions_requested"] == 1, str(rep2))

    st, paid = call("POST", f"/api/contracts/{ct}/payment", None, key="p_1")
    check("эскроу выплачен после приёмки",
          st == 200 and paid["status"] == "paid" and paid["amount"] == 480.0, str((st, paid)))
    check("деньги ушли исполнителю из эскроу", paid["escrow_state"] == "released")

    st, twice = call("POST", f"/api/contracts/{ct}/payment", None, key="p_2")
    check("второй выплаты по тому же контракту нет", st == 409, str((st, twice)))

    st, end = call("POST", f"/api/contracts/{ct}/endorsement",
                   {"verdict": "recommend", "comment": "сделал в срок, доработку закрыл за день"},
                   key="en_1")
    check("рекомендация выдана на конкретную работу",
          st == 201 and end["work_ref"] == contract["work_ref"], str((st, end)))

    _, rep3 = call("GET", f"/api/reputation?contractor_id={contractor}")
    refs = [e["work_ref"] for e in rep3["endorsements"]]
    check("репутация — список работ, а не рейтинг профиля",
          refs == [contract["work_ref"]] and len(rep3["works"]) == 1, str(rep3))
    check("токен контракта в публичной репутации не раскрыт",
          ct not in json.dumps(rep3, ensure_ascii=False))

    st, bad = call("POST", f"/api/contracts/{ct}/endorsement", {"verdict": "пятёрочка"}, key="en_2")
    check("вердикт вне цехового словаря отвергнут", st == 400, str((st, bad)))


# ────────────────────────────────────────────────────────────────────────────
# 4. Ёмкость исполнителя и невозвратность времени
# ────────────────────────────────────────────────────────────────────────────

def test_capacity() -> None:
    print("\nЁмкость исполнителя: её нельзя пополнить:")
    week = week_of(2)  # та же неделя, где у Игоря уже занято 8 из 10 часов

    huge = prepare("huge", 2, 99, 100, week, budget=200)
    check("оценка сверх недельной ёмкости отвергнута на этапе оценки",
          huge["quote_status"] == 409 and "ёмкость" in huge["quote"]["error"],
          str(huge.get("quote")))

    over = prepare("over", 2, 4, 150, week, budget=200)
    st, body = sign("over", over)
    check("контракт сверх остатка ёмкости не подписан",
          st == 409 and body["error"] == "сверх ёмкости исполнителя", str((st, body)))
    check("отказ объясняет, сколько часов свободно",
          body.get("free_hours") == 2 and body.get("requested_hours") == 4, str(body))

    fits = prepare("fits", 2, 2, 120, week, budget=200)
    st, body = sign("fits", fits)
    check("ровно в остаток ёмкости контракт подписан",
          st == 201 and body["free_hours_left"] == 0, str((st, body)))

    print("\nНевозвратность времени: прошедшая неделя не возвращается в ёмкость:")
    cur = week_of(0)
    now_chain = prepare("cur", 1, 5, 300, cur, budget=400)
    st, c_now = sign("cur", now_chain)
    check("контракт на текущую неделю подписан", st == 201, str((st, c_now)))
    before = capacity(1, cur)
    st, cancelled = call("POST", f"/api/contracts/{c_now['contract_token']}/cancel",
                         {"reason": "заказчик передумал"}, key="x_cur")
    after = capacity(1, cur)
    check("расторжение текущей недели сожгло часы",
          st == 200 and cancelled["capacity_burned_hours"] == 5
          and cancelled["capacity_returned_hours"] == 0, str((st, cancelled)))
    check("свободных часов начавшейся недели не прибавилось",
          after["free_hours"] == before["free_hours"] and after["burned_hours"] == 5,
          f"{before} → {after}")

    future = week_of(3)
    fut_chain = prepare("fut", 1, 5, 300, future, budget=400)
    st, c_fut = sign("fut", fut_chain)
    check("контракт на будущую неделю подписан", st == 201, str((st, c_fut)))
    busy = capacity(1, future)["free_hours"]
    st, cancelled2 = call("POST", f"/api/contracts/{c_fut['contract_token']}/cancel", {},
                          key="x_fut")
    free_again = capacity(1, future)["free_hours"]
    check("расторжение будущей недели вернуло часы",
          st == 200 and cancelled2["capacity_returned_hours"] == 5, str((st, cancelled2)))
    check("ёмкость будущей недели восстановлена",
          free_again == busy + 5, f"{busy} → {free_again}")

    print("\nЭскроу и расторжение — разные последствия, разные глаголы:")
    live = prepare("live", 3, 6, 200, week_of(4))
    st, c_live = sign("live", live)
    check("контракт для проверки эскроу подписан", st == 201, str((st, c_live)))
    st, blocked = call("POST", f"/api/escrow/{live['escrow']}/refund", None, key="rf_live")
    check("эскроу действующего контракта не возвращается",
          st == 409 and "действующий контракт" in blocked["error"], str((st, blocked)))
    st, nope = call("DELETE", f"/api/briefs/{live['brief']}", None, key="bc_live")
    check("бриф под контрактом не снимается — расторгать нужно контракт",
          st == 409, str((st, nope)))
    st, nope2 = call("DELETE", f"/api/quotes/{live['quote']}")
    check("оценку, ставшую контрактом, уже не снять", st == 409, str((st, nope2)))

    call("POST", f"/api/contracts/{c_live['contract_token']}/cancel", {}, key="x_live")
    st, no_rep = call("POST", f"/api/contracts/{c_live['contract_token']}/endorsement",
                      {"verdict": "recommend"}, key="en_live")
    check("рекомендация на невыполненную работу невозможна",
          st == 409 and "выполненной работе" in no_rep["error"], str((st, no_rep)))
    st, refunded = call("POST", f"/api/escrow/{live['escrow']}/refund", None, key="rf_live2")
    check("после расторжения эскроу возвращается заказчику",
          st == 200 and refunded["state"] == "refunded", str((st, refunded)))

    st, conflict = call("POST", f"/api/contracts/{c_live['contract_token']}/cancel", {},
                        key="rf_live2")
    check("один ключ идемпотентности не обслуживает два разных глагола",
          st == 409 and "уже использован" in conflict["error"], str((st, conflict)))


# ────────────────────────────────────────────────────────────────────────────
# 5. Конкуренция: ёмкость под одновременными подписаниями
# ────────────────────────────────────────────────────────────────────────────

def test_concurrency() -> None:
    print("\nКонкуренция (L4 из daten2 ломался здесь: 1 успех, 5 отказов базы):")
    week = week_of(5)
    chains = [prepare(f"par{i}", 1, 8, 100, week, budget=200) for i in range(6)]
    results: list[tuple[int, dict]] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        out = sign(f"par{i}", chains[i])
        with lock:
            results.append(out)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    codes = sorted(st for st, _ in results)
    ok = [b for st, b in results if st == 201]
    over = [b for st, b in results if st == 409 and b.get("error") == "сверх ёмкости исполнителя"]
    check("все шесть одновременных подписаний получили ответ", len(results) == 6, str(codes))
    check("ни одного внутреннего сбоя базы", all(st != 500 for st in codes), str(codes))
    check("ёмкость 20 часов вместила ровно два контракта по 8",
          len(ok) == 2, f"успехов {len(ok)}: {codes}")
    check("остальные отвергнуты именно по ёмкости, а не по занятости базы",
          len(over) == 4, f"отказов по ёмкости {len(over)} из {len(results) - len(ok)}")
    cap = capacity(1, week)
    check("занятых часов ровно 16 — ёмкость не превышена",
          cap["committed_hours"] == 16 and cap["free_hours"] == 4, str(cap))


# ────────────────────────────────────────────────────────────────────────────
# 6. Манифест против живого сервиса: обобщённый агент без правок под цех
# ────────────────────────────────────────────────────────────────────────────

def test_bindings_and_agent() -> None:
    print("\nМанифест против живого сервиса:")
    man = load_manifest(MANIFEST_PATH)

    missing: list[str] = []
    for cap in man:
        path = cap.binding["path"]
        for token in ("{brief_token}", "{hold_id}", "{quote_token}",
                      "{contract_token}", "{escrow_token}"):
            path = path.replace(token, "zzz-no-such-token")
        method = cap.binding["method"]
        st, body = call(method, path, {} if method in ("POST", "PUT", "PATCH") else None)
        # Маршрут обязан существовать. Что он отвергнет вызов без ключа или с
        # несуществующим токеном — нормально; чего быть не должно, так это
        # объявленного в манифесте глагола без маршрута на живом сервисе.
        if isinstance(body, dict) and body.get("error") == "неизвестный маршрут":
            missing.append(f"{cap.id} → {method} {cap.binding['path']}")
    check("все 19 объявленных биндингов существуют на живом сервисе",
          not missing, "без маршрута: " + ", ".join(missing))

    print("\nОбобщённый агент npp_act работает с цехом без правок под него:")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        client, gov, led = build(tmp, 2000.0, "person:client")

        res = client.read(SERVICE, "contractor.list", {})
        check("каталог компетенций прочитан исполнителем npp_act",
              res is not None and res.ok and len(res.body) == 3)

        res = client.read(SERVICE, "capacity.get", {"contractor_id": 1, "weeks": 3})
        check("ёмкость прочитана по объявленному биндингу",
              res is not None and res.ok and res.body["hours_per_week"] == 20)

        res = client.read(SERVICE, "reputation.get", {"contractor_id": 2})
        check("репутация прочитана по объявленному биндингу",
              res is not None and res.ok and res.body["completed_contracts"] >= 1)

        # Бриф создаём напрямую: ниже проверяется именно пара reserve/reverse.
        _, brief = call("POST", "/api/briefs", {
            "client": "Агент", "title": "Проверка удержания", "budget_cap": 100,
            "client_token": "ct_agent",
        })
        bt = brief["brief_token"]

        dec, hold = client.hold(SERVICE, "quote.request", {"brief_token": bt, "contractor_id": 3})
        check("удержание внимания взято обобщённым агентом",
              dec.admitted and hold is not None and hold.hold_id.startswith("qr_"), dec.reason)
        check("удержание знает свой обратный глагол",
              hold is not None and hold.reverse_verb == "quote.withdraw")
        st, _ = call("POST", "/api/quote-requests", {"brief_token": bt, "contractor_id": 3})
        check("пока удержание живо, второго запроса к тому же исполнителю нет", st == 409, str(st))

        client.release(hold)
        st, again = call("POST", "/api/quote-requests", {"brief_token": bt, "contractor_id": 3})
        check("после обратного глагола запрос оценки снова возможен", st == 201, str((st, again)))

        # Деньги под гейтом: эскроу — money-глагол, допуск только с подтверждением.
        key = "agent-escrow-1"
        d = gov.evaluate(SERVICE, "escrow.fund", {"brief_token": bt, "amount": 100,
                                                  "max_money": 100}, idempotency_key=key)
        check("эскроу без подтверждения владельца не допущен",
              d.verdict == "escalate" and "подтверждени" in d.reason, d.reason)

        client.accept(SERVICE, "escrow.fund", key)
        dec, res = client.act(SERVICE, "escrow.fund",
                              {"brief_token": bt, "amount": 100, "max_money": 100}, key=key)
        check("с подтверждением эскроу внесён через живой HTTP",
              dec.admitted and res is not None and res.ok and res.body["state"] == "held",
              dec.reason)
        check("бюджет профиля списан по факту", gov.budget.spent == 100.0, str(gov.budget.spent))

        dec2, _ = client.act(SERVICE, "escrow.fund",
                             {"brief_token": bt, "amount": 100, "max_money": 100}, key=key)
        check("повтор ключа идемпотентности заблокирован губернатором по журналу",
              dec2.verdict == "block" and "повтор" in dec2.reason, dec2.reason)

        check("журнал агента цел", led.verify())
        kinds = {r.kind for r in led}
        check("журнал содержит намерение, решение, исполнение и исход",
              {"intent", "decision", "execution", "outcome"} <= kinds, str(sorted(kinds)))


# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    db = Path(tempfile.gettempdir()) / "npp_freelance_test.db"
    if db.exists():
        db.unlink()
    port = 8229
    global BASE
    BASE = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "-m", "act.services.freelance.server",
         "--port", str(port), "--db", str(db), "--reset"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_up(f"{BASE}/api/health"):
            print("✗ сервис цеха не поднялся")
            return 1
        print(f"Сервис цеха поднят на :{port}")
        test_manifest()
        test_governor()
        test_cycle()
        test_capacity()
        test_concurrency()
        test_bindings_and_agent()
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
