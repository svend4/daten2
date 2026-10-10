"""Проверка переносимой репутации (act/npp_act/credential.py).

ДИСЦИПЛИНА ТА ЖЕ, ЧТО В ОСТАЛЬНЫХ НАБОРАХ: никаких моков. Свидетельство о
работе проверяется против НАСТОЯЩЕЙ работы — здесь поднимается подпроцессом
живой цех (act.services.freelance.server) и прогоняется полный цикл по HTTP:
бриф → запрос оценки → оценка → эскроу → двустороннее обязательство →
сдача → приёмка → рекомендация. Только после приёмки появляется то, подо что
письмо вообще можно выдать.

Проверять модуль репутации против собственного мока было бы здесь особенно
бессмысленно: мок написал бы те же допущения, под которые писался модуль, и
«обязательство есть в двух цепях» означало бы «я сам положил туда две строки».
(Образец этой ошибки в экосистеме известен: смоук plugin-marketplace имеет
14/14 зелёных и при этом сервис отвергает все настоящие бэкенды.)

ЧТО ДОБАВИЛОСЬ ВМЕСТЕ С АСИММЕТРИЧНОЙ ПОДПИСЬЮ
----------------------------------------------
Теперь свидетельство подписывается Ed25519, и главное новое утверждение —
«проверить может КТО УГОДНО, не имея никаких секретов». Проверяется оно так:
письмо о настоящей работе выдаётся с парой ключей заказчика, после чего
проверяющему отдают только журналы сторон и публичный ключ из паспорта — ни
приватного ключа, ни доступа к сервису. Сама подпись сверена с двумя внешними
эталонами в `act/tests/test_ed25519.py`; здесь проверяется не арифметика, а то,
что протокол ею пользуется и что уровни доверия не путаются между собой.

Запуск:  python3 -m act.tests.test_credential
"""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import (  # noqa: E402
    Agent, Budget, Commitment, Executor, Governor, Ledger, Registry,
)
from act.npp_act.credential import (  # noqa: E402
    ALG_ED25519, ALG_HMAC, LEVEL_DECLARED, LEVEL_NONE, LEVEL_PUBLIC, LEVEL_SECRET,
    RATING_MAX, Credential, CredentialError, Portfolio, SigningKey,
    examine, issue, key_id, new_issuer_key, public_key_id, sign, verify, work_proven,
)

SERVICE = "freelance-guild"
BASE = ""  # подставляется в main()

#: Унаследованные симметричные секреты. Оставлены в наборе не для полноты, а
#: потому что совместимость — отдельное требование: ранее выданные письма с
#: alg="hmac-sha256" обязаны проверяться и после перехода на Ed25519.
KOLYA_KEY = "secret-kolya-0001"
PETRA_KEY = "secret-petra-0002"
STRANGER_KEY = "secret-stranger-9999"

#: Пары ключей Ed25519. Seed фиксирован, чтобы прогон был воспроизводим: это
#: тест, а не выдача настоящих ключей, и секретность здесь ничего не защищает.
KOLYA_PAIR = new_issuer_key(bytes([11]) * 32)
PETRA_PAIR = new_issuer_key(bytes([22]) * 32)
STRANGER_PAIR = new_issuer_key(bytes([99]) * 32)

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


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            return True
    except Exception:
        return False


def wait_up(url: str, attempts: int = 50) -> bool:
    for _ in range(attempts):
        if answers(url):
            return True
        time.sleep(0.1)
    return False


def pick_port() -> int:
    """Порт, который и молчит по HTTP, и действительно свободен для bind.

    Фиксированный номер здесь уже стоил одного молчаливого ложного прогона в
    соседнем наборе: тест мерил ЧУЖОЙ процесс, случайно занявший порт, и
    отчитывался зелёным. Двух проверок мало по отдельности — молчащий порт
    может быть занят процессом, который не отвечает на HTTP, а успешный bind
    ничего не говорит о том, кто ответит на запрос. Нужны обе.
    """
    port = 8241
    while port < 8641:
        candidate, port = port, port + 1
        if answers(f"http://127.0.0.1:{candidate}/api/health"):
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
        return candidate
    raise RuntimeError("свободных портов для цеха не нашлось")


def week_of(offset_weeks: int) -> str:
    d = date.today() + timedelta(days=7 * offset_weeks)
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def has(reasons: list[str], needle: str) -> bool:
    return any(needle in r for r in reasons)


# ────────────────────────────────────────────────────────────────────────────
# Настоящая работа: цех по HTTP, два профиля, обязательство в двух журналах
# ────────────────────────────────────────────────────────────────────────────


def make_agent(reg: Registry, folder: Path, name: str,
               limit: float = 5000.0) -> tuple[Agent, Ledger]:
    folder.mkdir(parents=True, exist_ok=True)
    led = Ledger(folder / f"{name.replace(':', '_')}.jsonl", owner=name)
    gov = Governor(reg, led, Budget(limit))
    return Agent(name, Executor(reg, gov, led)), led


def last_response(led: Ledger, verb: str) -> dict:
    """Ответ сервиса на последний УДАЧНЫЙ вызов глагола — из журнала.

    Токен контракта берётся не из возвращённого значения, а из записи `outcome`:
    `commit_two_party` намеренно отдаёт только обязательство, и журнал здесь —
    единственный источник, что полностью соответствует §6 (всё, что произошло,
    лежит в цепи).
    """
    for rec in reversed(list(led)):
        if rec.kind == "outcome" and rec.payload.get("verb") == verb and rec.payload.get("ok"):
            resp = rec.payload.get("response")
            return resp if isinstance(resp, dict) else {}
    return {}


def do_contract(client: Agent, contractor: Agent, *, contractor_id: int, hours: int,
                price: float, week: str, subject: str, tag: str) -> dict:
    """Полный цикл цеха живым HTTP — до принятой работы включительно.

    Возвращает обязательство и публичную ссылку на работу (`work_ref`), которую
    выдал САМ СЕРВИС при приёмке. Эта ссылка потом попадает в свидетельство, и
    проверяющий сверяет её с журналом заказчика, а не с ожиданиями теста.
    """
    out: dict = {"subject": subject, "error": None}

    # Чтение сначала: и каталог нужен, и сервис должен появиться в журналах —
    # иначе губернатор справедливо эскалирует первое обязывающее взаимодействие.
    cat = client.read(SERVICE, "contractor.list", {})
    if cat is None or not cat.ok:
        return {**out, "error": "каталог цеха не прочитан"}
    cap = contractor.read(SERVICE, "capacity.get", {"contractor_id": contractor_id, "weeks": 8})
    if cap is None or not cap.ok:
        return {**out, "error": "ёмкость исполнителя не прочитана"}

    dec, res = client.act(SERVICE, "brief.create", {
        "client": client.profile, "title": subject,
        "spec": "работа по договору цеха", "budget_cap": price,
    }, key=f"bt_{tag}")
    if res is None or not res.ok:
        return {**out, "error": f"бриф: {dec.reason} / {res.body if res else '—'}"}
    brief = res.body["brief_token"]

    dec, hold = client.hold(SERVICE, "quote.request",
                            {"brief_token": brief, "contractor_id": contractor_id})
    if hold is None:
        return {**out, "error": f"запрос оценки: {dec.reason}"}

    k = f"q_{tag}"
    contractor.accept(SERVICE, "quote.give", k)
    dec, res = contractor.act(SERVICE, "quote.give", {
        "request_id": hold.hold_id, "price": price, "hours": hours, "week": week,
    }, key=k)
    if res is None or not res.ok:
        return {**out, "error": f"оценка: {dec.reason} / {res.body if res else '—'}"}
    quote = res.body["quote_token"]

    k = f"e_{tag}"
    client.accept(SERVICE, "escrow.fund", k)
    dec, res = client.act(SERVICE, "escrow.fund", {
        "brief_token": brief, "amount": price, "max_money": price,
    }, key=k)
    if res is None or not res.ok:
        return {**out, "error": f"эскроу: {dec.reason} / {res.body if res else '—'}"}
    escrow = res.body["escrow_token"]

    dec, cmt = client.commit_two_party(SERVICE, "contract.sign", {
        "brief_token": brief, "quote_token": quote, "escrow_token": escrow,
        "max_money": price,
    }, counterparty=contractor, subject=subject)
    if cmt is None:
        return {**out, "error": f"контракт: {dec.reason}"}

    contract = str(last_response(client.ledger, "contract.sign").get("contract_token") or "")
    if not contract:
        return {**out, "error": "токен контракта не найден в журнале заказчика"}

    k = f"d_{tag}"
    dec, res = contractor.act(SERVICE, "work.deliver", {
        "contract_token": contract, "artifact": f"архив работ {tag}",
        "note": "готово",
    }, key=k)
    if res is None or not res.ok:
        return {**out, "error": f"сдача: {dec.reason} / {res.body if res else '—'}"}

    k = f"a_{tag}"
    client.accept(SERVICE, "work.accept", k)
    dec, res = client.act(SERVICE, "work.accept", {"contract_token": contract}, key=k)
    if res is None or not res.ok:
        return {**out, "error": f"приёмка: {dec.reason} / {res.body if res else '—'}"}
    work_ref = str(res.body.get("work_ref") or "")

    k = f"r_{tag}"
    client.accept(SERVICE, "reputation.endorse", k)
    dec, res = client.act(SERVICE, "reputation.endorse", {
        "contract_token": contract, "verdict": "recommend",
        "comment": "работа принята без доработок",
    }, key=k)
    if res is None or not res.ok:
        return {**out, "error": f"рекомендация сервиса: {dec.reason} / {res.body if res else '—'}"}

    return {**out, "commitment": cmt, "contract": contract, "work_ref": work_ref,
            "endorsement": res.body}


# ────────────────────────────────────────────────────────────────────────────
# 1. Основание: работа действительно состоялась и лежит в двух цепях
# ────────────────────────────────────────────────────────────────────────────


def test_real_work(reg: Registry, tmp: Path) -> dict:
    print("\nНастоящая работа через живой цех — основание для свидетельства:")
    folder = tmp / "journals"
    marina, marina_led = make_agent(reg, folder, "person:marina")
    kolya, kolya_led = make_agent(reg, folder, "person:kolya")
    petra, petra_led = make_agent(reg, folder, "person:petra")

    w1 = do_contract(kolya, marina, contractor_id=1, hours=8, price=400.0,
                     week=week_of(1), subject="вёрстка каталога, 8 часов", tag="w1")
    check("первая работа доведена до приёмки живым сервисом", w1["error"] is None, str(w1["error"]))
    w2 = do_contract(petra, marina, contractor_id=1, hours=6, price=300.0,
                     week=week_of(2), subject="доступность форм, 6 часов", tag="w2")
    check("вторая работа доведена до приёмки живым сервисом", w2["error"] is None, str(w2["error"]))
    if w1["error"] or w2["error"]:
        return {}

    ledgers = {"person:marina": marina_led, "person:kolya": kolya_led,
               "person:petra": petra_led}

    check("журнал исполнителя цел", marina_led.verify())
    check("журнал первого заказчика цел", kolya_led.verify())
    check("в журнале исполнителя два обязательства",
          len(marina_led.by_kind("commitment")) == 2,
          str(len(marina_led.by_kind("commitment"))))
    check("обязательство записано у обеих сторон",
          w1["commitment"].verified_by(ledgers))
    check("сервис выдал публичную ссылку на принятую работу",
          w1["work_ref"].startswith("work_"), w1["work_ref"])
    check("ссылка сервиса на работу и ссылка в рекомендации совпадают",
          w1["endorsement"].get("work_ref") == w1["work_ref"],
          str(w1["endorsement"]))

    return {"ledgers": ledgers, "w1": w1, "w2": w2,
            "marina_led": marina_led, "kolya_led": kolya_led, "petra_led": petra_led}


# ────────────────────────────────────────────────────────────────────────────
# 2. Выдача: только под подтверждённую работу
# ────────────────────────────────────────────────────────────────────────────


def test_issue(env: dict) -> dict:
    print("\nВыдача свидетельства — только под работу, которая была:")
    ledgers, w1, w2 = env["ledgers"], env["w1"], env["w2"]
    cmt1, cmt2 = w1["commitment"], w2["commitment"]

    cred1 = issue(cmt1, ledgers, "person:kolya", "person:marina", 5,
                  "сдано с первого раза, без доработок",
                  key=KOLYA_KEY, work_ref=w1["work_ref"],
                  service=SERVICE, verb="contract.sign")
    check("свидетельство выдано под настоящее обязательство",
          cred1.commitment_id == cmt1.id, cred1.commitment_id)
    check("свидетельство привязано к записям ОБЕИХ сторон",
          set(cred1.anchors) == {"person:kolya", "person:marina"}, str(cred1.anchors))
    check("привязки — это хэши записей из журналов",
          cred1.anchors == cmt1.hashes)
    check("предмет работы взят из обязательства, а не из слов issuer",
          cred1.work == cmt1.subject, cred1.work)
    check("клеймо поставлено", cred1.signature.startswith("hs256:"), cred1.signature[:16])
    check("отпечаток ключа объявлен и совпадает с ключом issuer",
          cred1.key_id == key_id(KOLYA_KEY), cred1.key_id)
    check("алгоритм подписи объявлен в самом свидетельстве",
          cred1.alg == ALG_HMAC, cred1.alg)
    check("секрет issuer в свидетельство не попал",
          KOLYA_KEY not in cred1.to_json())

    cred2 = issue(cmt2, ledgers, "person:petra", "person:marina", 4,
                  "одна доработка по текстам", key=PETRA_KEY,
                  work_ref=w2["work_ref"], service=SERVICE, verb="contract.sign")
    check("второе свидетельство выдано другим заказчиком",
          cred2.issuer == "person:petra" and cred2.commitment_id == cmt2.id)

    unsigned = issue(cmt1, ledgers, "person:kolya", "person:marina", 5, "без клейма",
                     work_ref=w1["work_ref"], service=SERVICE)
    check("без ключа письмо выдаётся, но неподписанным",
          unsigned.signature == "" and unsigned.key_id == "")

    # ── отказы выдачи ──────────────────────────────────────────────────────
    fake_id = Commitment(id="cmt_0000000000000000", parties=cmt1.parties,
                         subject=cmt1.subject, hashes=dict(cmt1.hashes))
    try:
        issue(fake_id, ledgers, "person:kolya", "person:marina", 5, "выдумка", key=KOLYA_KEY)
        check("выдуманный commitment_id отвергнут", False, "выдача прошла")
    except CredentialError as e:
        check("выдуманный commitment_id отвергнут", "другому обязательству" in str(e), str(e))

    check("проверка выдачи строже, чем Commitment.verified_by (тот принял бы подделку)",
          fake_id.verified_by(ledgers))

    fake_hashes = Commitment(id=cmt1.id, parties=cmt1.parties, subject=cmt1.subject,
                             hashes={"person:kolya": "f" * 64, "person:marina": "e" * 64})
    try:
        issue(fake_hashes, ledgers, "person:kolya", "person:marina", 5, "х", key=KOLYA_KEY)
        check("выдуманные хэши записей отвергнуты", False, "выдача прошла")
    except CredentialError as e:
        check("выдуманные хэши записей отвергнуты", "нет записи" in str(e), str(e))

    try:
        issue(cmt1, ledgers, "person:stranger", "person:marina", 5, "я видел", key=STRANGER_KEY)
        check("посторонний не может выдать свидетельство", False, "выдача прошла")
    except CredentialError as e:
        check("посторонний не может выдать свидетельство", "не сторона" in str(e), str(e))

    try:
        issue(cmt1, ledgers, "person:marina", "person:marina", 5, "сама себе", key=KOLYA_KEY)
        check("свидетельство самому себе отвергнуто", False, "выдача прошла")
    except CredentialError as e:
        check("свидетельство самому себе отвергнуто", "самому себе" in str(e), str(e))

    try:
        issue(cmt1, ledgers, "person:kolya", "person:marina", 7, "семь из пяти", key=KOLYA_KEY)
        check("оценка вне шкалы отвергнута", False, "выдача прошла")
    except CredentialError as e:
        check("оценка вне шкалы отвергнута", "шкал" in str(e) or "1..5" in str(e), str(e))

    try:
        issue(cmt1, ledgers, "person:kolya", "person:marina", 5, "чужая ссылка",
              key=KOLYA_KEY, work_ref="work_deadbeef00")
        check("ссылка на работу, которой нет в журнале issuer, отвергнута",
              False, "выдача прошла")
    except CredentialError as e:
        check("ссылка на работу, которой нет в журнале issuer, отвергнута",
              "не встречается в журнале issuer" in str(e), str(e))

    orphan = Commitment(id="cmt_нигде", parties=["person:kolya", "person:marina"],
                        subject="ничего", hashes={})
    try:
        issue(orphan, ledgers, "person:kolya", "person:marina", 5, "", key=KOLYA_KEY)
        check("обязательство без хэшей записей отвергнуто", False, "выдача прошла")
    except CredentialError as e:
        check("обязательство без хэшей записей отвергнуто", "не несёт хэшей" in str(e), str(e))

    return {"cred1": cred1, "cred2": cred2, "unsigned": unsigned}


# ────────────────────────────────────────────────────────────────────────────
# 3. Проверка предъявленного письма
# ────────────────────────────────────────────────────────────────────────────


def test_verify(env: dict, creds: dict) -> None:
    print("\nПроверка предъявленного свидетельства:")
    ledgers = env["ledgers"]
    cred1, unsigned = creds["cred1"], creds["unsigned"]

    ok, reasons = verify(cred1, ledgers, key=KOLYA_KEY)
    check("подлинное свидетельство подтверждено", ok, "; ".join(reasons))

    ok, reasons = work_proven(cred1, ledgers)
    check("работа доказуема и без ключа — доказывают цепи, а не подпись",
          ok, "; ".join(reasons))

    ok, reasons = verify(cred1, ledgers)
    check("без ключа issuer подпись не считается проверенной", not ok)
    check("причина названа честно: симметричная схема",
          has(reasons, "симметричная схема"), "; ".join(reasons))
    check("и там же сказано, что сама работа всё равно доказана",
          has(reasons, "доказана цепями"), "; ".join(reasons))

    ok, reasons = verify(cred1, ledgers, key=STRANGER_KEY)
    check("чужой ключ подпись не подтверждает",
          not ok and has(reasons, "подпись не сходится"), "; ".join(reasons))

    ok, reasons = verify(unsigned, ledgers, key=KOLYA_KEY)
    check("неподписанное письмо не проходит строгую проверку",
          not ok and has(reasons, "не подписано"), "; ".join(reasons))
    ok, _ = verify(unsigned, ledgers, require_signature=False)
    check("но работа по нему подтверждается, если клеймо не требуют", ok)

    # ── подмена оценки ломает подпись ──────────────────────────────────────
    louder = replace(cred1, rating=1)
    ok, reasons = verify(louder, ledgers, key=KOLYA_KEY)
    check("подмена оценки ломает подпись",
          not ok and has(reasons, "подпись не сходится"), "; ".join(reasons))
    better = replace(cred1, note="лучший мастер города")
    ok, reasons = verify(better, ledgers, key=KOLYA_KEY)
    check("подмена отзыва ломает подпись",
          not ok and has(reasons, "подпись не сходится"), "; ".join(reasons))
    retold = replace(cred1, work="проектирование архитектуры, 200 часов")
    ok, reasons = verify(retold, ledgers, key=KOLYA_KEY)
    check("подмена описания работы расходится с предметом обязательства",
          not ok and has(reasons, "не совпадает с предметом обязательства"), "; ".join(reasons))

    # ── подмена issuer ─────────────────────────────────────────────────────
    stolen = replace(cred1, issuer="person:petra")
    ok, reasons = verify(stolen, ledgers, key=KOLYA_KEY)
    check("подмена issuer ломает подпись", not ok and has(reasons, "подпись не сходится"))

    forged = sign(stolen, PETRA_KEY)
    check("подделыватель может поставить СВОЁ клеймо и оно сойдётся",
          forged.signed_by(PETRA_KEY))
    ok, reasons = verify(forged, ledgers, key=PETRA_KEY)
    check("но цепи всё равно отвергают подменённого issuer", not ok, "; ".join(reasons))
    check("причина — его нет среди сторон обязательства",
          has(reasons, "не является стороной обязательства")
          or has(reasons, "нет хэша-привязки"), "; ".join(reasons))

    # ── чужая работа под своим письмом ─────────────────────────────────────
    swapped = sign(replace(cred1, commitment_id=creds["cred2"].commitment_id), KOLYA_KEY)
    ok, reasons = verify(swapped, ledgers, key=KOLYA_KEY)
    check("письмо нельзя перевесить на другое обязательство",
          not ok and has(reasons, "другому обязательству"), "; ".join(reasons))

    # ── непредъявленный журнал ─────────────────────────────────────────────
    ok, reasons = verify(cred1, {"person:kolya": ledgers["person:kolya"]}, key=KOLYA_KEY)
    check("без журнала второй стороны проверять нечем",
          not ok and has(reasons, "не предъявлен"), "; ".join(reasons))


# ────────────────────────────────────────────────────────────────────────────
# 4. Подделка журнала
# ────────────────────────────────────────────────────────────────────────────


def test_tampered_ledger(env: dict, creds: dict, tmp: Path) -> None:
    print("\nПодделка журнала ломает проверку:")
    ledgers, cred1 = env["ledgers"], creds["cred1"]
    source = env["marina_led"].path
    lines = source.read_text(encoding="utf-8").splitlines()
    anchor = cred1.anchors["person:marina"]

    # (а) содержимое записи переписано, хэш оставлен прежним
    patched = []
    idx = -1
    for i, line in enumerate(lines):
        rec = json.loads(line)
        if rec["hash"] == anchor:
            idx = i
            rec["payload"] = dict(rec["payload"])
            rec["payload"]["subject"] = rec["payload"]["subject"] + " (переписано задним числом)"
        patched.append(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False))
    check("запись обязательства найдена в журнале исполнителя", idx >= 0)

    forged_path = tmp / "forged" / "marina.jsonl"
    forged_path.parent.mkdir(parents=True, exist_ok=True)
    forged_path.write_text("\n".join(patched) + "\n", encoding="utf-8")
    forged_led = Ledger(forged_path, owner="person:marina")

    ok, reasons = verify(cred1, {**ledgers, "person:marina": forged_led}, key=KOLYA_KEY)
    check("переписанная запись ломает проверку свидетельства", not ok)
    check("причина указывает на разорванную цепь, а не на подпись",
          has(reasons, "цепь стороны 'person:marina' нарушена"), "; ".join(reasons))

    # (б) запись просто удалена: цепь-обрубок цела, но обязательства в ней нет.
    #     Это отдельный случай, и назвать его нужно отдельно — «работы не было»,
    #     а не «журнал испорчен».
    cut_path = tmp / "forged" / "marina_cut.jsonl"
    cut_path.write_text("\n".join(lines[:idx]) + ("\n" if idx else ""), encoding="utf-8")
    cut_led = Ledger(cut_path, owner="person:marina")
    check("усечённая цепь сама по себе цела", cut_led.verify())
    ok, reasons = verify(cred1, {**ledgers, "person:marina": cut_led}, key=KOLYA_KEY)
    check("удалённое обязательство ломает проверку", not ok)
    check("причина — такого обязательства не было",
          has(reasons, "такого обязательства не было"), "; ".join(reasons))

    # (в) подмена вида записи: хэш есть, но это не обязательство
    first = json.loads(lines[0])
    sideways = replace(cred1, anchors={**cred1.anchors, "person:marina": first["hash"]})
    ok, reasons = verify(sideways, ledgers, key=KOLYA_KEY)
    check("привязка к не-обязательству отвергнута",
          not ok and has(reasons, "не обязательство"), "; ".join(reasons))


# ────────────────────────────────────────────────────────────────────────────
# 5. Переносимость: письмо уезжает файлом
# ────────────────────────────────────────────────────────────────────────────


def test_portable(env: dict, creds: dict) -> None:
    print("\nПереносимость: письмо живёт отдельно от сервиса:")
    ledgers, cred1 = env["ledgers"], creds["cred1"]

    raw = cred1.to_json()
    back = Credential.from_json(raw)
    check("письмо выдерживает перенос через JSON без потерь", back == cred1)
    ok, reasons = verify(back, ledgers, key=KOLYA_KEY)
    check("перенесённое письмо проверяется так же", ok, "; ".join(reasons))
    check("в письме нет непубличного токена контракта (§10.3)",
          env["w1"]["contract"] not in raw)
    check("публичная ссылка на работу в письме есть",
          env["w1"]["work_ref"] in raw)


# ────────────────────────────────────────────────────────────────────────────
# 6. Портфолио: проверяемое отдельно от заявленного
# ────────────────────────────────────────────────────────────────────────────


def test_portfolio(env: dict, creds: dict) -> None:
    print("\nПортфолио исполнителя — папка, а не рейтинг:")
    ledgers = env["ledgers"]
    cred1, cred2 = creds["cred1"], creds["cred2"]

    # Письмо, выданное «под работу», которой никогда не было: ровно то, что
    # умеют звёздочки и не умеет цеховая папка.
    invented = sign(Credential(
        commitment_id="cmt_придумано000",
        issuer="person:stranger", subject="person:marina",
        work="проект под ключ, 500 часов", rating=5, note="блестяще",
        anchors={"person:stranger": "a" * 64, "person:marina": "b" * 64},
        service=SERVICE,
    ), STRANGER_KEY)
    # Письмо о настоящей работе, но подписанное посторонним.
    hijacked = sign(replace(cred1, issuer="person:stranger"), STRANGER_KEY)
    # Письмо, адресованное другому человеку.
    not_mine = replace(cred2, subject="person:igor")

    port = Portfolio("person:marina")
    for c in (cred1, cred2, invented, hijacked, not_mine):
        port.add(c)
    check("папка принимает всё, что предъявили", len(port) == 5, str(len(port)))

    keys = {"person:kolya": KOLYA_KEY, "person:petra": PETRA_KEY,
            "person:stranger": STRANGER_KEY}
    good, bad = port.verifiable(ledgers, keys)
    check("проверяемыми оказались только настоящие работы", len(good) == 2, str(len(good)))
    check("непроверяемые отделены и каждое с причиной",
          len(bad) == 3 and all(rs for _, rs in bad), str([(c.issuer, rs) for c, rs in bad]))
    by_id = {c.commitment_id for c in good}
    check("в проверяемых — именно те два обязательства",
          by_id == {cred1.commitment_id, cred2.commitment_id}, str(by_id))
    reasons_invented = next(rs for c, rs in bad if c.commitment_id == "cmt_придумано000")
    check("выдуманная работа отвергнута по отсутствию записей в цепях",
          has(reasons_invented, "такого обязательства не было"), "; ".join(reasons_invented))
    reasons_other = next(rs for c, rs in bad if c.subject == "person:igor")
    check("чужое письмо отвергнуто по адресату",
          has(reasons_other, "адресовано не"), "; ".join(reasons_other))

    summary = port.summary(ledgers, keys)
    check("сводка считается по проверяемому", summary["basis"] == "проверенное", summary["basis"])
    check("работ в сводке две", summary["works"] == 2, str(summary["works"]))
    check("средняя оценка считается по работам, а не по письмам",
          summary["average_rating"] == 4.5, str(summary["average_rating"]))
    check("видно, с кем работал исполнитель",
          summary["issuers"] == ["person:kolya", "person:petra"], str(summary["issuers"]))
    check("отвергнутые посчитаны отдельно", summary["rejected"] == 3, str(summary["rejected"]))
    check("у каждого отвергнутого в сводке есть причина",
          all(r["reasons"] for r in summary["rejected_reasons"]))
    check("сервис работы назван в сводке", summary["services"] == [SERVICE],
          str(summary["services"]))
    check("подписанных писем столько же, сколько проверяемых",
          summary["signed"] == 2, str(summary["signed"]))

    claimed = port.summary()
    check("без журналов сводка честно помечена заявленной",
          claimed["basis"] == "заявленное", claimed["basis"])
    check("заявленное выглядит лучше проверенного — в этом и смысл различия",
          claimed["works"] > summary["works"] and
          (claimed["average_rating"] or 0) > (summary["average_rating"] or 0),
          f"{claimed['works']}/{claimed['average_rating']} против "
          f"{summary['works']}/{summary['average_rating']}")

    # Два письма об одной работе не удваивают репутацию.
    again = issue(env["w1"]["commitment"], ledgers, "person:kolya", "person:marina", 5,
                  "подтверждаю ещё раз", key=KOLYA_KEY,
                  work_ref=env["w1"]["work_ref"], service=SERVICE)
    port.add(again)
    s2 = port.summary(ledgers, keys)
    check("второе письмо о той же работе не добавляет работу",
          s2["works"] == 2, str(s2["works"]))
    check("но учтено как ещё одно проверяемое письмо",
          s2["credentials"] == 3, str(s2["credentials"]))

    # Папка тоже переносима: её уносят вместе с письмами.
    restored = Portfolio.from_json(port.to_json())
    check("папка выдерживает перенос через JSON",
          len(restored) == len(port) and restored.subject == port.subject)
    g2, _ = restored.verifiable(ledgers, keys)
    check("перенесённая папка проверяется так же", len(g2) == 3, str(len(g2)))

    only_mine = Portfolio.collect("person:marina", restored)
    check("сборка папки отбрасывает письма, адресованные другим",
          len(only_mine) == len(port) - 1, str(len(only_mine)))

    check("шкала оценок объявлена модулем, а не угадывается",
          RATING_MAX == 5 and all(1 <= c.rating <= RATING_MAX for c in good))


# ────────────────────────────────────────────────────────────────────────────
# 7. Асимметричная подпись: письмо проверяет кто угодно, без секретов
# ────────────────────────────────────────────────────────────────────────────

#: Проверка «третьей стороной» выполняется ОТДЕЛЬНЫМ ПРОЦЕССОМ, которому
#: передают только путь к журналам, текст письма и публичный ключ из паспорта.
#: Так проверяемое утверждение становится буквальным: никакого секрета, никакой
#: общей памяти, никакого доступа к сервису — и всё равно «годно».
THIRD_PARTY = r'''
import json, sys
root, raw, public = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, root)
from act.npp_act.ledger import Ledger
from act.npp_act.credential import Credential, examine
ledgers = {}
for pair in sys.argv[4:]:
    owner, path = pair.split("=", 1)
    ledgers[owner] = Ledger(path, owner=owner)
v = examine(Credential.from_json(raw), ledgers,
            public_key=(public or None))
print(json.dumps({"ok": v.ok, "level": v.level, "work": v.work_proven,
                  "reasons": v.reasons}, ensure_ascii=False))
'''


def third_party(cred: Credential, ledgers: dict, public: str) -> dict:
    args = [sys.executable, "-I", "-c", THIRD_PARTY, str(ROOT), cred.to_json(), public]
    args += [f"{owner}={led.path}" for owner, led in sorted(ledgers.items())]
    run = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        return {"ok": False, "level": "—", "work": False,
                "reasons": [f"проверяющий процесс упал: {run.stderr.strip()[-300:]}"]}
    return json.loads(run.stdout)


def canonical(obj) -> str:
    """Каноническая форма JSON — вписана в тест, а не взята из модуля.

    Нарочно: от неё зависит ПОДПИСЬ, и если тест будет спрашивать форму у
    того же модуля, который подписывает, то согласованная ошибка пройдёт
    незамеченной. Здесь форма зафиксирована как внешнее требование к формату.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def legacy_hmac_letter(cred: Credential, secret: str) -> str:
    """Собрать письмо СТАРОГО формата вручную и вернуть его JSON.

    Это проверка совместимости «снизу»: тест не спрашивает у новой реализации,
    как выглядел прежний формат, а воспроизводит его по первоисточнику —
    тринадцать полей тела, та же метка домена, тот же HMAC-SHA256. Если новая
    версия незаметно изменит состав подписываемого тела, все ранее выданные
    письма станут недействительными, и узнать об этом нужно здесь, а не от
    исполнителя, которому откажут в его собственной репутации.
    """
    sig_label = b"npp-act/credential/signature/v1\x00"
    kid_label = b"npp-act/credential/key-id/v1"
    key = secret.encode("utf-8")
    kid = "kid_" + hmac.new(key, kid_label, hashlib.sha256).hexdigest()[:16]
    body = {
        "commitment_id": cred.commitment_id, "issuer": cred.issuer,
        "subject": cred.subject, "work": cred.work, "rating": cred.rating,
        "note": cred.note, "issued_at": cred.issued_at,
        "anchors": dict(cred.anchors), "service": cred.service,
        "verb": cred.verb, "work_ref": cred.work_ref,
        "alg": "hmac-sha256", "key_id": kid,
    }
    signature = "hs256:" + hmac.new(
        key, sig_label + canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()
    return canonical({**body, "signature": signature})


def test_asymmetric(env: dict) -> dict:
    print("\nАсимметричная подпись: публичная проверка без всяких секретов:")
    ledgers, w1 = env["ledgers"], env["w1"]
    cmt1 = w1["commitment"]

    cred = issue(cmt1, ledgers, "person:kolya", "person:marina", 5,
                 "сдано с первого раза", key=KOLYA_PAIR,
                 work_ref=w1["work_ref"], service=SERVICE, verb="contract.sign")

    check("алгоритм в письме — ed25519", cred.alg == ALG_ED25519, cred.alg)
    check("клеймо поставлено Ed25519", cred.signature.startswith("ed25519:"),
          cred.signature[:20])
    check("подпись — 64 байта",
          len(bytes.fromhex(cred.signature.split(":", 1)[1])) == 64)
    check("публичный ключ issuer уехал в письме",
          cred.public_key == KOLYA_PAIR.public, cred.public_key)
    check("отпечаток ключа считается из публичного ключа — его может посчитать любой",
          cred.key_id == public_key_id(KOLYA_PAIR.public) == KOLYA_PAIR.key_id, cred.key_id)
    check("ПРИВАТНОГО ключа в письме нет",
          KOLYA_PAIR.private not in cred.to_json())
    check("публичный ключ покрыт подписью (входит в подписываемое тело)",
          "public_key" in cred.signed_body())

    # ── главное утверждение этапа ──────────────────────────────────────────
    ok, reasons = verify(cred, ledgers, public_key=KOLYA_PAIR.public)
    check("письмо проверено ОДНИМ ПУБЛИЧНЫМ КЛЮЧОМ, без секрета issuer",
          ok, "; ".join(reasons))
    v = examine(cred, ledgers, public_key=KOLYA_PAIR.public)
    check("уровень проверки назван публичным", v.level == LEVEL_PUBLIC and v.public, v.level)
    check("в вердикте отдельно сказано, что работа доказана цепями", v.work_proven)
    check("вердикт объясняется человеку одной строкой",
          "годно" in v.explain() and "публично" in v.explain(), v.explain())

    # Тот же ключ работает в любой кодировке: паспорт может хранить base64.
    import base64
    b64 = base64.b64encode(bytes.fromhex(KOLYA_PAIR.public)).decode()
    ok, _ = verify(cred, ledgers, public_key=b64)
    check("публичный ключ принимается и в base64 (паспорт хранит как хочет)", ok)

    # ── проверка посторонним процессом: ни секретов, ни общей памяти ───────
    out = third_party(cred, ledgers, KOLYA_PAIR.public)
    check("посторонний процесс проверил письмо по журналам и публичному ключу",
          out["ok"] and out["level"] == LEVEL_PUBLIC, str(out))
    check("ему для этого хватило паспортного ключа и двух журналов", out["work"])

    # ── без ключа: целостность проверена, личность — нет ──────────────────
    v = examine(cred, ledgers)
    check("без предъявленного ключа уровень честно понижен до declared",
          v.level == LEVEL_DECLARED, v.level)
    check("и такое письмо НЕ считается проверенным", not v.ok)
    check("причина названа прямо: ключ взят из самого свидетельства",
          has(v.reasons, "взят из самого свидетельства"), "; ".join(v.reasons))
    check("при этом подпись с ключом из письма действительно сходится",
          cred.self_consistent())

    # ── подделка «со своей парой ключей» — то, чего не ловит сама подпись ──
    # Посторонний видел честное письмо (а значит, и хэши-привязки), завёл свою
    # пару ключей, вписал себя issuer-ом настоящей работы и подписал. Его
    # подпись СХОДИТСЯ с его же публичным ключом — и именно поэтому уровень
    # declared нельзя считать проверкой.
    forged = sign(replace(cred, issuer="person:stranger", rating=5,
                          note="блестяще, рекомендую"), STRANGER_PAIR)
    check("подделыватель со своей парой ключей получает внутренне согласное письмо",
          forged.self_consistent())
    v = examine(forged, ledgers)
    check("но цепи отвергают его и без всякого ключа", not v.ok)
    check("причина — он не сторона обязательства",
          has(v.reasons, "не является стороной обязательства")
          or has(v.reasons, "нет хэша-привязки"), "; ".join(v.reasons))

    # Тот же трюк, но issuer оставлен настоящий: цепи такое письмо пропускают,
    # и отвергает его ровно паспортный ключ — то есть асимметричная подпись.
    impostor = sign(replace(cred, rating=5, note="я сам себе заказчик"), STRANGER_PAIR)
    ok, reasons = work_proven(impostor, ledgers)
    check("письмо с подменённым только текстом цепи пропускают", ok, "; ".join(reasons))
    v = examine(impostor, ledgers)
    check("без паспортного ключа подделка выглядит «подписанной»",
          v.level == LEVEL_DECLARED, v.level)
    v = examine(impostor, ledgers, public_key=KOLYA_PAIR.public)
    check("с паспортным ключом issuer подделка отвергнута", not v.ok)
    check("причина — подписано не тем ключом, который issuer опубликовал",
          has(v.reasons, "не тот, которым подписано"), "; ".join(v.reasons))
    check("уровень при этом не «публично проверено»", v.level == LEVEL_NONE, v.level)

    # ── правка текста ломает подпись ──────────────────────────────────────
    for changed, what in ((replace(cred, rating=1), "оценки"),
                          (replace(cred, note="переписано"), "отзыва"),
                          (replace(cred, issued_at="2000-01-01T00:00:00Z"), "даты"),
                          (replace(cred, public_key=PETRA_PAIR.public), "ключа в письме")):
        ok, reasons = verify(changed, ledgers, public_key=KOLYA_PAIR.public)
        check(f"правка {what} ломает проверку", not ok, "; ".join(reasons))

    ok, reasons = verify(cred, ledgers, public_key=PETRA_PAIR.public)
    check("чужой публичный ключ письмо не подтверждает",
          not ok and has(reasons, "не тот, которым подписано"), "; ".join(reasons))
    ok, reasons = verify(cred, ledgers, public_key="это не ключ")
    check("мусор вместо ключа отвергнут с внятной причиной",
          not ok and has(reasons, "не читается"), "; ".join(reasons))

    # Испорченный ключ В САМОМ письме — данные от того, кто мог их подделать.
    # Проверка обязана ответить «негодно», а не упасть с исключением.
    ok, reasons = verify(replace(cred, public_key="мусор"), ledgers,
                         public_key=KOLYA_PAIR.public)
    check("нечитаемый публичный ключ внутри письма отвергнут без исключения",
          not ok and has(reasons, "в самом свидетельстве не читается"),
          "; ".join(reasons))
    ok, reasons = verify(replace(cred, public_key="мусор"), ledgers)
    check("то же письмо без предъявленного ключа тоже отвергнуто",
          not ok and has(reasons, "не читается"), "; ".join(reasons))

    # ── паспорт: откуда проверяющий берёт ключ ────────────────────────────
    block = KOLYA_PAIR.passport_block("person:kolya")
    check("паспортный блок содержит публичный ключ, алгоритм и отпечаток",
          block["public_key"] == KOLYA_PAIR.public and block["alg"] == ALG_ED25519
          and block["key_id"] == KOLYA_PAIR.key_id, str(block))
    check("приватного ключа в паспортном блоке нет",
          KOLYA_PAIR.private not in canonical(block))
    check("паспорт переносим как JSON", json.loads(canonical(block))["profile"] == "person:kolya")
    check("приватный ключ не печатается в repr пары ключей",
          KOLYA_PAIR.private not in repr(KOLYA_PAIR), repr(KOLYA_PAIR))
    restored = new_issuer_key(bytes.fromhex(KOLYA_PAIR.private))
    check("пара ключей восстанавливается из seed — паспорт не надо хранить дважды",
          restored.public == KOLYA_PAIR.public and restored.key_id == KOLYA_PAIR.key_id)
    # Ed25519 детерминирован, поэтому пара, собранная из двух сохранённых строк
    # (как её хранил бы стенд), обязана дать БИТ В БИТ ту же подпись.
    stored = SigningKey(private=KOLYA_PAIR.private, public=KOLYA_PAIR.public)
    check("пара ключей из сохранённых строк подписывает то же самое",
          sign(cred, stored).signature == cred.signature)
    check("разные issuer-ы различимы по отпечатку клейма",
          KOLYA_PAIR.key_id != PETRA_PAIR.key_id != STRANGER_PAIR.key_id)

    # ── переносимость файлом ──────────────────────────────────────────────
    back = Credential.from_json(cred.to_json())
    check("письмо с Ed25519 выдерживает перенос через JSON без потерь", back == cred)
    ok, _ = verify(back, ledgers, public_key=KOLYA_PAIR.public)
    check("перенесённое письмо проверяется так же", ok)

    return {"ed": cred, "forged": forged, "impostor": impostor}


# ────────────────────────────────────────────────────────────────────────────
# 8. Совместимость: унаследованные hmac-письма и разные уровни доверия
# ────────────────────────────────────────────────────────────────────────────


def test_compatibility(env: dict, creds: dict) -> None:
    print("\nСовместимость с ранее выданными письмами (alg=hmac-sha256):")
    ledgers, cred1 = env["ledgers"], creds["cred1"]

    check("унаследованное письмо так и объявляет свой алгоритм",
          cred1.alg == ALG_HMAC, cred1.alg)
    check("в его подписываемом теле поля public_key НЕТ — иначе сломались бы все старые",
          "public_key" not in cred1.signed_body())
    check("и в переносимой форме его тоже нет", "public_key" not in cred1.to_dict())

    v = examine(cred1, ledgers, key=KOLYA_KEY)
    check("старое письмо по-прежнему проверяется предъявленным секретом", v.ok,
          "; ".join(v.reasons))
    check("уровень назван «проверено с секретом», а не публичным",
          v.level == LEVEL_SECRET and not v.public, v.level)

    # Письмо, собранное по старому формату ВРУЧНУЮ (см. legacy_hmac_letter):
    # так проверяется не «мы умеем читать то, что сами написали», а формат.
    raw = legacy_hmac_letter(cred1, KOLYA_KEY)
    old = Credential.from_json(raw)
    check("письмо старого формата читается новой реализацией",
          old.commitment_id == cred1.commitment_id and old.alg == ALG_HMAC)
    check("его key_id сошёлся с отпечатком секрета", old.key_id == key_id(KOLYA_KEY))
    v = examine(old, ledgers, key=KOLYA_KEY)
    check("подпись, посчитанная в тесте по первоисточнику, принята модулем", v.ok,
          "; ".join(v.reasons))
    check("и такое письмо тоже не считается публично проверяемым", not v.public)

    ok, reasons = verify(old, ledgers, public_key=KOLYA_PAIR.public)
    check("публичным ключом симметричное письмо проверить нельзя — и так и сказано",
          not ok and has(reasons, "публичным ключом проверяется только"), "; ".join(reasons))
    ok, reasons = verify(cred1, ledgers, key=KOLYA_PAIR)
    check("пара Ed25519 не подходит к симметричной подписи — причина названа",
          not ok and has(reasons, "такой ключ к этой подписи не подходит"),
          "; ".join(reasons))

    unknown = replace(cred1, alg="rsa-pkcs1")
    ok, reasons = verify(unknown, ledgers, key=KOLYA_KEY)
    check("неизвестный алгоритм подписи отвергнут",
          not ok and has(reasons, "неизвестный алгоритм"), "; ".join(reasons))

    # Симметричное письмо, в которое дописали публичный ключ: HMAC от этого не
    # рвётся (поле не входит в тело подписи), и именно поэтому такое письмо
    # должно быть названо негодным, а не тихо проверено «как раньше».
    dressed = replace(cred1, public_key=KOLYA_PAIR.public)
    ok, reasons = verify(dressed, ledgers, key=KOLYA_KEY)
    check("симметричное письмо с дописанным публичным ключом отвергнуто",
          not ok and has(reasons, "подписью не покрыто"), "; ".join(reasons))
    check("а его HMAC-подпись при этом по-прежнему сходится — поле не в теле",
          dressed.signed_by(KOLYA_KEY))


def test_levels_in_portfolio(env: dict, creds: dict, ed_creds: dict) -> None:
    print("\nПортфолио: переносимое отдельно от проверяемого-с-секретом:")
    ledgers = env["ledgers"]
    ed_cred = ed_creds["ed"]           # ed25519, работа w1, issuer kolya
    hmac_cred = creds["cred2"]         # hmac, работа w2, issuer petra
    forged = ed_creds["impostor"]      # ed25519 чужим ключом от имени kolya

    port = Portfolio("person:marina")
    for c in (ed_cred, hmac_cred, forged):
        port.add(c)

    # То, что знает проверяющий: паспортный ключ kolya и старый секрет petra.
    # Один словарь на обе схемы — какую применить, говорит `alg` самого письма.
    known = {"person:kolya": KOLYA_PAIR.public, "person:petra": PETRA_KEY}
    good, bad = port.verifiable(ledgers, known)
    check("оба настоящих письма проверены, хотя подписаны разными схемами",
          len(good) == 2, str([(c.issuer, c.alg) for c in good]))
    check("подделка отвергнута", len(bad) == 1 and bad[0][0].note == forged.note,
          str([(c.issuer, rs) for c, rs in bad]))

    pub_good, pub_bad = port.publicly_verifiable(ledgers, {"person:kolya": KOLYA_PAIR.public})
    check("публично проверяемым оказалось только письмо с Ed25519",
          len(pub_good) == 1 and pub_good[0].alg == ALG_ED25519,
          str([c.alg for c in pub_good]))
    reasons_hmac = next(rs for c, rs in pub_bad if c.alg == ALG_HMAC)
    check("унаследованное письмо названо непереносимым, а не поддельным",
          has(reasons_hmac, "симметричная схема"), "; ".join(reasons_hmac))

    s = port.summary(ledgers, known)
    check("в сводке посчитаны уровни проверки",
          s["levels"] == {LEVEL_PUBLIC: 1, LEVEL_SECRET: 1}, str(s["levels"]))
    check("публично проверяемых — одно", s["publicly_verifiable"] == 1,
          str(s["publicly_verifiable"]))
    check("папка целиком НЕ помечена переносимой: в ней есть симметричное письмо",
          s["portable"] is False)
    check("в сводке видно, какими схемами подписаны учтённые письма",
          s["algorithms"] == sorted([ALG_ED25519, ALG_HMAC]), str(s["algorithms"]))
    check("клейма учтённых писем перечислены отпечатками",
          s["key_ids"] == sorted([ed_cred.key_id, hmac_cred.key_id]), str(s["key_ids"]))
    check("обе работы учтены по обязательствам", s["works"] == 2, str(s["works"]))

    # Папка только из Ed25519-писем переносима целиком — и это ровно то, чего
    # не умела симметричная схема: репутация уходит вместе с исполнителем.
    second = issue(env["w2"]["commitment"], ledgers, "person:petra", "person:marina", 4,
                   "одна доработка", key=PETRA_PAIR, work_ref=env["w2"]["work_ref"],
                   service=SERVICE, verb="contract.sign")
    portable = Portfolio("person:marina", [ed_cred, second])
    passports = {"person:kolya": KOLYA_PAIR.public, "person:petra": PETRA_PAIR.public}
    s2 = portable.summary(ledgers, passports)
    check("папка из одних Ed25519-писем проверяется целиком без секретов",
          s2["publicly_verifiable"] == 2 and s2["portable"] is True, str(s2["levels"]))
    check("и средняя оценка в ней считается по тем же правилам",
          s2["average_rating"] == 4.5, str(s2["average_rating"]))

    # Та же папка, перенесённая файлом и проверенная посторонним процессом.
    restored = Portfolio.from_json(portable.to_json())
    check("папка с Ed25519 выдерживает перенос через JSON",
          len(restored) == 2 and all(c.alg == ALG_ED25519 for c in restored))
    out = third_party(restored.credentials[1], ledgers, PETRA_PAIR.public)
    check("перенесённое письмо проверил посторонний процесс по паспорту petra",
          out["ok"] and out["level"] == LEVEL_PUBLIC, str(out))
    check("ни один приватный ключ в переносимую папку не попал",
          KOLYA_PAIR.private not in portable.to_json()
          and PETRA_PAIR.private not in portable.to_json())


# ────────────────────────────────────────────────────────────────────────────

def start_guild(tmp: Path, attempts: int = 4):
    """Поднять свой цех и убедиться, что отвечает ИМЕННО ОН.

    Подбора свободного порта недостаточно: между проверкой и bind порт может
    занять кто угодно — в том числе второй прогон этого же набора. Тогда наш
    сервис умирает с «адрес занят», а HTTP по этому адресу продолжает отвечать,
    и тест уходит измерять ЧУЖОЙ цех, отчитываясь зелёным. Это та самая ошибка,
    из-за которой здесь вообще отказались от фиксированных портов, и одного
    подбора она не лечит.

    Поэтому после того, как адрес ответил, проверяется, что НАШ процесс жив.
    Если он умер — отвечает не он, порт признаётся негодным, и берётся
    следующий. `stderr` сервиса уходит в файл, а не в /dev/null: сервис,
    который не поднялся, обязан объяснить причину.
    """
    for _ in range(attempts):
        port = pick_port()
        log = tmp / f"guild-{port}.log"
        handle = log.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "act.services.freelance.server",
             "--port", str(port), "--db", str(tmp / f"guild-{port}.db"), "--reset"],
            cwd=str(ROOT), stdout=handle, stderr=handle,
        )
        up = wait_up(f"http://127.0.0.1:{port}/api/health")
        time.sleep(0.3)  # дать нашему процессу упасть, если адрес уже занят
        if up and proc.poll() is None:
            return port, proc, handle, log
        tail = log.read_text(encoding="utf-8", errors="replace")[-200:]
        print(f"    порт :{port} не подошёл (ответил {up}, код выхода {proc.poll()}): "
              f"{tail.strip() or 'без сообщений'} — берём следующий")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        handle.close()
    return None


def main() -> int:
    global BASE

    # База цеха и журналы живут в одном временном каталоге прогона, а не по
    # постоянному пути в /tmp. Постоянный путь делал два одновременных прогона
    # невозможными ровно так же, как это делал фиксированный порт: второй
    # сбрасывал базу первому и ронял его на половине сценария.
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        started = start_guild(tmp)
        if started is None:
            print("✗ свой сервис цеха поднять не удалось")
            return 1
        port, proc, handle, log = started
        BASE = f"http://127.0.0.1:{port}"
        try:
            print(f"Сервис цеха поднят на :{port}")

            reg = Registry().load_dir(ROOT / "act/manifests").rebind(SERVICE, BASE)
            env = test_real_work(reg, tmp)
            if not env:
                print("✗ без настоящей работы остальные проверки не имеют смысла")
                return 1
            creds = test_issue(env)
            test_verify(env, creds)
            test_tampered_ledger(env, creds, tmp)
            test_portable(env, creds)
            test_portfolio(env, creds)
            ed_creds = test_asymmetric(env)
            test_compatibility(env, creds)
            test_levels_in_portfolio(env, creds, ed_creds)
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            handle.close()

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
