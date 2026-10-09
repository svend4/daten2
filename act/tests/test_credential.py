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

Запуск:  python3 -m act.tests.test_credential
"""

from __future__ import annotations

import json
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
    ALG_HMAC, RATING_MAX, Credential, CredentialError, Portfolio,
    issue, key_id, sign, verify, work_proven,
)

SERVICE = "freelance-guild"
BASE = ""  # подставляется в main()

#: Секреты «клейма мастера». В тесте они просто строки: асимметричной подписи
#: в stdlib нет, и модуль об этом ограничении говорит прямо (см. его docstring).
KOLYA_KEY = "secret-kolya-0001"
PETRA_KEY = "secret-petra-0002"
STRANGER_KEY = "secret-stranger-9999"

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

def main() -> int:
    db = Path(tempfile.gettempdir()) / "npp_credential_test.db"
    if db.exists():
        db.unlink()
    port = 8241
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

        reg = Registry().load_dir(ROOT / "act/manifests").rebind(SERVICE, BASE)
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            env = test_real_work(reg, tmp)
            if not env:
                print("✗ без настоящей работы остальные проверки не имеют смысла")
                return 1
            creds = test_issue(env)
            test_verify(env, creds)
            test_tampered_ledger(env, creds, tmp)
            test_portable(env, creds)
            test_portfolio(env, creds)
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
