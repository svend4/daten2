"""Расчётный слой NPP-Act: двойная запись, эскроу и saga-клиринг.

ПОЧЕМУ ЭТОТ СЛОЙ ОТДЕЛЁН ОТ ГУБЕРНАТОРА И ЖУРНАЛА
--------------------------------------------------
Губернатор решает, ВПРАВЕ ли агент двинуть деньги. Журнал фиксирует, ЧТО он
решил и что из этого вышло. Но ни тот, ни другой не считают деньги: журнал
хранит намерения и исходы, а не остатки. Пока расчёта нет, «деньги двинулись»
остаётся словом в ответе чужого сервиса — предъявить его нельзя.

Расчёт здесь устроен на трёх правилах, и каждое взято из конкретного провала,
найденного при аудите daten2 и прототипов:

1. ДВОЙНАЯ ЗАПИСЬ. Каждая проводка — две ноги: у кого списали и кому
   зачислили. Сумма ног равна нулю, поэтому МАССА ДЕНЕГ СОХРАНЯЕТСЯ. Это
   инвариант, а не пожелание: verify_invariants() сверяет сумму всех остатков
   с суммой явных эмиссий и возвращает нарушение, если они расходятся.
   Односторонняя запись «начислить исполнителю» в принципе не выразима этим
   API — её нельзя сделать по невнимательности.

2. ЦЕЛЫЕ ЦЕНТЫ. Из семи уровней daten2 только L6 держал деньги в Decimal,
   L6 же ловил перепродажу; остальные считали во float или держали цену
   строкой. Расхождение в один цент в эскроу — это либо неоплаченная работа,
   либо недоплаченный человек, и округлять его нельзя. Поэтому здесь все
   суммы — целые центы, а любое сравнение сумм — сравнение целых.

3. ПРЕРВАННЫЙ РАСЧЁТ ОБЯЗАН БЫТЬ ВИДЕН. L7 при недоступном брокере терял
   событие молча. Здесь сага пишет в журнал начало, каждую применённую ногу и
   конец. Если процесс умер посередине, при загрузке такой расчёт получает
   состояние `interrupted`, verify_invariants() называет его нарушением, а
   recover() компенсирует применённые ноги. Потерять его нельзя: журнал на
   диске, и в нём остался незакрытый расчёт.

ЭСКРОУ: удержание (`reserve`) обратимо — деньги остаются на счёте владельца,
но становятся недоступны. Выплата (`capture`) необратима и возможна один раз.
Это та же пара «reserve → commit» из §4.2 спецификации, только для денег:
сначала обратимый шаг, потом обязательство.

САГА: несколько плеч исполняются по порядку, потому что промежуточный счёт
(эскроу, транзит, комиссия платформы) должен стать доступен следующему плечу.
Если любое плечо не проходит, уже исполненные откатываются обратными
проводками в обратном порядке — эффект строго «всё или ничего». Компенсация
пишется в журнал как новые проводки, а не затирает прежние: append-only
журнал, который умеет стирать, доказательством не является.

Зависимостей нет: стандартная библиотека и record_hash из ledger.py —
хэш-цепь у расчётов та же, что у решений, и переиспользуется, а не копируется.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .ledger import GENESIS, record_hash

#: Состояния расчёта. `interrupted` не возникает при нормальной работе: его
#: ставит загрузчик, обнаружив начатую и незакрытую сагу.
PENDING, SETTLED, ABORTED, INTERRUPTED = "pending", "settled", "aborted", "interrupted"

#: Состояния эскроу. Из `held` есть два выхода и ни одного обратно.
HELD, RELEASED, CAPTURED = "held", "released", "captured"

EVENTS = (
    "account.open", "money.issue",
    "transfer",
    "escrow.reserve", "escrow.release", "escrow.capture",
    "saga.begin", "saga.end", "saga.recover",
)


class SettlementError(RuntimeError):
    """Расчёт невозможен по причине, которая является ошибкой вызывающего.

    Отличие от прерванной саги существенно. Нехватка средств или
    неподтверждённая поставка — нормальный исход расчёта: сага откатывается и
    возвращает состояние `aborted`. А несходящиеся плечи, неизвестный счёт или
    вторая выплата одного эскроу — это дефект вызывающего кода, и он обязан
    упасть, а не вернуть «что-то разумное».
    """


# ───────────────────────────── деньги ─────────────────────────────

def to_cents(value: Any) -> int:
    """Евро (число или строка) → целые центы.

    Через float проходим только здесь, в единственной точке, и сразу
    округляем. Дальше по системе ходят целые.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value * 100
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError) as e:
        raise SettlementError(f"не сумма: {value!r}") from e


def money(cents: int) -> float:
    """Центы → евро для показа человеку. Внутрь расчёта не возвращается."""
    return round(cents / 100, 2)


# ───────────────────────────── сущности ─────────────────────────────

@dataclass
class Account:
    """Счёт стороны.

    `held` — часть остатка, удержанная эскроу: она лежит на счёте, но
    распоряжаться ею владелец не может. Разделение нужно, чтобы удержание было
    обратимым без движения денег: отпустить удержание дешевле и честнее, чем
    перевести деньги туда и обратно.
    """

    id: str
    balance: int = 0
    held: int = 0
    kind: str = "party"
    allow_negative: bool = False

    @property
    def available(self) -> int:
        return self.balance - self.held


@dataclass(frozen=True)
class Leg:
    """Одно плечо расчёта: откуда, куда, сколько центов."""

    src: str
    dst: str
    cents: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "cents": self.cents, "note": self.note}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Leg":
        return Leg(d["src"], d["dst"], int(d["cents"]), d.get("note", ""))

    def inverse(self) -> "Leg":
        return Leg(self.dst, self.src, self.cents, f"компенсация: {self.note}" if self.note else "компенсация")


@dataclass
class Escrow:
    """Удержание денег до наступления события (приёмки работы, поставки)."""

    id: str
    owner: str
    cents: int
    state: str = HELD
    ref: str = ""

    @property
    def active(self) -> bool:
        return self.state == HELD


@dataclass
class Settlement:
    """Результат саги. Хранится по ключу: повтор не исполняется второй раз."""

    id: str
    legs: list[Leg]
    state: str = PENDING
    reason: str = ""
    applied: list[Leg] = field(default_factory=list)
    escrow_id: str = ""
    reverses: str = ""
    reversed_by: str = ""

    @property
    def ok(self) -> bool:
        return self.state == SETTLED

    @property
    def total(self) -> int:
        return sum(l.cents for l in self.legs)


# ───────────────────────────── книга ─────────────────────────────

class Book:
    """Книга счетов с персистентным журналом проводок.

    Состояние не хранится «где-то в памяти»: единственный источник истины —
    файл журнала, а поля объекта суть его свёртка. Поэтому reload() обязан
    давать те же остатки, а verify_invariants() это проверяет отдельной
    проверкой — заново свернув журнал и сравнив с памятью.

    >>> b = Book("/tmp/demo-book.jsonl")                      # doctest: +SKIP
    >>> _ = b.open("person:anna", initial_cents=50_00)        # doctest: +SKIP
    >>> b.verify_invariants()                                  # doctest: +SKIP
    []
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.accounts: dict[str, Account] = {}
        self.escrows: dict[str, Escrow] = {}
        self.settlements: dict[str, Settlement] = {}
        self.issued: int = 0
        self._seq: int = 0
        self._head: str = GENESIS
        self._events: list[dict[str, Any]] = []
        if self.path.exists():
            self._load()

    # ---------- журнал ----------

    def _append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if kind not in EVENTS:
            raise SettlementError(f"неизвестное событие расчёта: {kind!r}")
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        h = record_hash(self._seq, ts, kind, payload, self._head)
        rec = {"seq": self._seq, "ts": ts, "kind": kind, "payload": payload,
               "prev": self._head, "hash": h}
        # Сначала на диск с fsync, потом в память — как в ledger.py: при сбое
        # между этими строками журнал не соврёт, а перечитается целиком.
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._events.append(rec)
        self._seq += 1
        self._head = h
        return rec

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                self._events.append(json.loads(line))
        self._apply_all(self._events, into=self)
        if self._events:
            self._seq = self._events[-1]["seq"] + 1
            self._head = self._events[-1]["hash"]
        # Начатая и незакрытая сага — это оборванный расчёт, а не «ничего не
        # было». Назвать его своим именем обязан именно загрузчик: в памяти
        # процесса, который умер, этого знания больше нет.
        for s in self.settlements.values():
            if s.state == PENDING:
                s.state = INTERRUPTED
                s.reason = "процесс прерван между началом и концом расчёта"

    # ---------- свёртка журнала ----------

    @staticmethod
    def _apply_all(events: Iterable[dict[str, Any]], into: "Book | _Shadow") -> None:
        """Свернуть события в состояние. Одна функция и для загрузки, и для сверки."""
        for rec in events:
            kind, p = rec["kind"], rec["payload"]

            if kind == "account.open":
                into.accounts[p["id"]] = Account(
                    p["id"], int(p.get("initial", 0)), 0,
                    p.get("kind", "party"), bool(p.get("allow_negative", False)),
                )
                into.issued += int(p.get("initial", 0))

            elif kind == "money.issue":
                into.accounts[p["account"]].balance += int(p["cents"])
                into.issued += int(p["cents"])

            elif kind == "transfer":
                into.accounts[p["src"]].balance -= int(p["cents"])
                into.accounts[p["dst"]].balance += int(p["cents"])

            elif kind == "escrow.reserve":
                into.escrows[p["escrow_id"]] = Escrow(
                    p["escrow_id"], p["owner"], int(p["cents"]), HELD, p.get("ref", ""))
                into.accounts[p["owner"]].held += int(p["cents"])

            elif kind == "escrow.release":
                esc = into.escrows[p["escrow_id"]]
                esc.state = RELEASED
                into.accounts[esc.owner].held -= esc.cents

            elif kind == "escrow.capture":
                esc = into.escrows[p["escrow_id"]]
                esc.state = CAPTURED
                into.accounts[esc.owner].held -= esc.cents

            elif kind == "saga.begin":
                into.settlements[p["id"]] = Settlement(
                    p["id"], [Leg.from_dict(x) for x in p["legs"]],
                    PENDING, "", [], p.get("escrow_id", ""), p.get("reverses", ""),
                )

            elif kind == "saga.end":
                s = into.settlements[p["id"]]
                s.state = p["state"]
                s.reason = p.get("reason", "")
                s.applied = [Leg.from_dict(x) for x in p.get("applied", [])]
                if p.get("reverses"):
                    src = into.settlements.get(p["reverses"])
                    if src is not None and p["state"] == SETTLED:
                        src.reversed_by = p["id"]

            elif kind == "saga.recover":
                s = into.settlements[p["id"]]
                s.state = ABORTED
                s.reason = p.get("reason", "компенсирован при восстановлении")
                s.applied = []

    # ---------- счета ----------

    def open(self, account_id: str, initial_cents: int = 0, *,
             kind: str = "party", allow_negative: bool = False) -> Account:
        """Открыть счёт. Начальный остаток — это ЭМИССИЯ, она учитывается в массе."""
        if account_id in self.accounts:
            raise SettlementError(f"счёт '{account_id}' уже открыт")
        if initial_cents < 0 and not allow_negative:
            raise SettlementError("отрицательный начальный остаток на обычном счёте")
        self._append("account.open", {"id": account_id, "initial": int(initial_cents),
                                      "kind": kind, "allow_negative": allow_negative})
        self._apply_all(self._events[-1:], into=self)
        return self.accounts[account_id]

    def issue(self, account_id: str, cents: int, reason: str = "") -> Account:
        """Ввести деньги в систему явной эмиссией.

        Без этого метода пополнить счёт было бы нечем, кроме перевода с другого
        счёта, — и любое «появление» денег выглядело бы как потеря массы.
        Эмиссия не прячется: она событие журнала и слагаемое инварианта.
        """
        acc = self._need(account_id)
        if cents <= 0:
            raise SettlementError("эмиссия должна быть положительной")
        self._append("money.issue", {"account": acc.id, "cents": int(cents), "reason": reason})
        self._apply_all(self._events[-1:], into=self)
        return acc

    def _need(self, account_id: str) -> Account:
        acc = self.accounts.get(account_id)
        if acc is None:
            raise SettlementError(f"счёт '{account_id}' не открыт")
        return acc

    def balance(self, account_id: str) -> int:
        return self._need(account_id).balance

    def available(self, account_id: str) -> int:
        return self._need(account_id).available

    def total_mass(self) -> int:
        return sum(a.balance for a in self.accounts.values())

    # ---------- одиночная проводка ----------

    def transfer(self, src: str, dst: str, cents: int, note: str = "", ref: str = "") -> None:
        """Двойная запись: списать у одного, зачислить другому. Иного пути нет."""
        a, b = self._need(src), self._need(dst)
        if cents <= 0:
            raise SettlementError("проводка должна быть положительной")
        if a.id == b.id:
            raise SettlementError("перевод на тот же счёт ничего не значит")
        if a.available < cents and not a.allow_negative:
            raise SettlementError(
                f"недостаточно доступных средств на '{a.id}': "
                f"{money(a.available)} < {money(cents)}")
        self._append("transfer", {"src": a.id, "dst": b.id, "cents": int(cents),
                                  "note": note, "ref": ref})
        self._apply_all(self._events[-1:], into=self)

    # ---------- эскроу ----------

    def reserve(self, owner: str, cents: int, escrow_id: str, ref: str = "") -> Escrow:
        """Удержать деньги на счёте владельца. Шаг обратимый (§4.2)."""
        acc = self._need(owner)
        if cents <= 0:
            raise SettlementError("удержание должно быть положительным")
        if escrow_id in self.escrows:
            # Идемпотентность удержания: повтор того же ключа не удерживает
            # вторую сумму. Иначе ретрай сети удваивал бы блокировку денег.
            esc = self.escrows[escrow_id]
            if esc.owner != owner or esc.cents != cents:
                raise SettlementError(f"эскроу '{escrow_id}' уже существует с другими условиями")
            if not esc.active:
                # Закрытый эскроу не оживляется повтором ключа. Ключ
                # идемпотентности защищает от двойного эффекта, а не выдаёт
                # право на второй: иначе один ключ двигал бы деньги дважды.
                raise SettlementError(
                    f"эскроу '{escrow_id}' уже закрыт (состояние '{esc.state}') — "
                    "повторное удержание по тому же ключу невозможно")
            return esc
        if acc.available < cents:
            raise SettlementError(
                f"нечего удерживать на '{owner}': доступно {money(acc.available)}, "
                f"нужно {money(cents)}")
        self._append("escrow.reserve", {"escrow_id": escrow_id, "owner": owner,
                                        "cents": int(cents), "ref": ref})
        self._apply_all(self._events[-1:], into=self)
        return self.escrows[escrow_id]

    def release(self, escrow_id: str) -> Escrow:
        """Отпустить удержание: деньги остаются у владельца и снова доступны."""
        esc = self.escrows.get(escrow_id)
        if esc is None:
            raise SettlementError(f"эскроу '{escrow_id}' не найден")
        if esc.state == RELEASED:
            return esc  # повторное отпускание ничего не меняет
        if esc.state == CAPTURED:
            raise SettlementError("эскроу уже выплачен — отпускать нечего")
        self._append("escrow.release", {"escrow_id": escrow_id})
        self._apply_all(self._events[-1:], into=self)
        return esc

    def capture(self, escrow_id: str, legs: Iterable[Leg | tuple],
                settlement_id: str | None = None) -> Settlement:
        """Выплатить удержанное: необратимый шаг, возможный РОВНО ОДИН раз.

        Плечи обязаны исходить со счёта владельца и в сумме равняться
        удержанию. Это проверяется ДО любого движения: выплата, не сошедшаяся
        с удержанием, означает либо недоплату исполнителю, либо потерю цента
        внутри платформы, и оба случая — дефект вызывающего, а не исход саги.
        """
        esc = self.escrows.get(escrow_id)
        if esc is None:
            raise SettlementError(f"эскроу '{escrow_id}' не найден")
        if esc.state == CAPTURED:
            raise SettlementError(f"эскроу '{escrow_id}' уже выплачен — вторая выплата невозможна")
        if esc.state == RELEASED:
            raise SettlementError(f"эскроу '{escrow_id}' отпущен — выплачивать нечего")

        norm = _legs(legs)
        if sum(l.cents for l in norm) != esc.cents:
            raise SettlementError(
                f"плечи выплаты не сходятся с удержанием: {money(sum(l.cents for l in norm))} "
                f"≠ {money(esc.cents)}")
        for l in norm:
            if l.src != esc.owner:
                raise SettlementError(
                    f"плечо выплаты идёт не со счёта владельца эскроу: {l.src} ≠ {esc.owner}")
            self._need(l.dst)

        sid = settlement_id or f"stl_{escrow_id}"
        done = self.settlements.get(sid)
        if done is not None and done.state in (SETTLED, ABORTED):
            return done

        # Снятие удержания и выплата — одно последствие, поэтому удержание
        # снимается здесь, а не внутри саги: деньги должны стать доступны
        # плечам, и в журнале порядок виден именно такой.
        self._append("escrow.capture", {"escrow_id": escrow_id, "settlement_id": sid})
        self._apply_all(self._events[-1:], into=self)
        return self.settle(sid, norm, escrow_id=escrow_id)

    # ---------- сага ----------

    def settle(self, settlement_id: str, legs: Iterable[Leg | tuple],
               deliver: bool = True, escrow_id: str = "") -> Settlement:
        """Клиринг нескольких плеч как сага: всё или ничего.

        Идемпотентность по ключу: повтор возвращает тот же результат, не
        исполняя второй раз. Ключ здесь — то же, чем для губернатора является
        Idempotency-Key: единственная защита от двойного эффекта при ретрае.
        """
        existing = self.settlements.get(settlement_id)
        if existing is not None and existing.state in (SETTLED, ABORTED):
            return existing
        if existing is not None and existing.state == INTERRUPTED:
            raise SettlementError(
                f"расчёт '{settlement_id}' прерван и не компенсирован — сначала recover()")

        norm = _legs(legs)
        self._append("saga.begin", {"id": settlement_id,
                                    "legs": [l.to_dict() for l in norm],
                                    "deliver": bool(deliver), "escrow_id": escrow_id})
        self._apply_all(self._events[-1:], into=self)
        rec = self.settlements[settlement_id]

        applied: list[Leg] = []
        failure = ""
        for leg in norm:
            if leg.src not in self.accounts:
                failure = f"нет счёта '{leg.src}'"
            elif leg.dst not in self.accounts:
                failure = f"нет счёта '{leg.dst}'"
            elif leg.cents <= 0:
                failure = f"плечо {leg.src}→{leg.dst} не положительно"
            elif leg.src == leg.dst:
                failure = f"плечо {leg.src}→{leg.dst} никуда не ведёт"
            elif (self.accounts[leg.src].available < leg.cents
                  and not self.accounts[leg.src].allow_negative):
                failure = (f"недостаточно средств на '{leg.src}': "
                           f"{money(self.accounts[leg.src].available)} < {money(leg.cents)}")
            if failure:
                break
            self.transfer(leg.src, leg.dst, leg.cents, leg.note, ref=settlement_id)
            applied.append(leg)

        if not failure and not deliver:
            # Поставка не подтверждена второй стороной: деньги не остаются у
            # получателя, иначе расчёт платил бы за то, чего не было.
            failure = "поставка не подтверждена"

        if failure:
            self._compensate(applied, settlement_id)
            self._append("saga.end", {"id": settlement_id, "state": ABORTED,
                                      "reason": failure, "applied": []})
            self._apply_all(self._events[-1:], into=self)
            return rec

        self._append("saga.end", {"id": settlement_id, "state": SETTLED, "reason": "",
                                  "applied": [l.to_dict() for l in applied],
                                  "reverses": rec.reverses})
        self._apply_all(self._events[-1:], into=self)
        return rec

    def _compensate(self, applied: list[Leg], settlement_id: str) -> None:
        """Откатить применённые плечи обратными проводками, в обратном порядке.

        Обратный порядок не косметика: плечи шли через промежуточные счёта, и
        только обратный обход гарантирует, что на каждом шаге есть что списать.
        """
        for leg in reversed(applied):
            inv = leg.inverse()
            self.transfer(inv.src, inv.dst, inv.cents, inv.note, ref=f"{settlement_id}:comp")

    def reverse(self, settlement_id: str, reverse_id: str | None = None) -> Settlement:
        """Реверс состоявшегося расчёта (спор, возврат).

        Возможен только если получатели ещё не распорядились деньгами: иначе
        сага откатится и вернёт `aborted`. Это честнее принудительного списания
        в минус — расчёт не вправе выдумывать деньги, которых уже нет.
        """
        src = self.settlements.get(settlement_id)
        if src is None or src.state != SETTLED:
            raise SettlementError(f"реверсировать нечего: расчёт '{settlement_id}' не состоялся")
        if src.reversed_by:
            return self.settlements[src.reversed_by]
        rid = reverse_id or f"rev_{settlement_id}"
        legs = [l.inverse() for l in reversed(src.legs)]
        self._append("saga.begin", {"id": rid, "legs": [l.to_dict() for l in legs],
                                    "deliver": True, "escrow_id": "", "reverses": settlement_id})
        self._apply_all(self._events[-1:], into=self)
        rec = self.settlements[rid]
        applied: list[Leg] = []
        failure = ""
        for leg in legs:
            if self.accounts[leg.src].available < leg.cents:
                failure = f"получатель '{leg.src}' уже распорядился средствами"
                break
            self.transfer(leg.src, leg.dst, leg.cents, leg.note, ref=rid)
            applied.append(leg)
        if failure:
            self._compensate(applied, rid)
            self._append("saga.end", {"id": rid, "state": ABORTED, "reason": failure,
                                      "applied": [], "reverses": settlement_id})
        else:
            self._append("saga.end", {"id": rid, "state": SETTLED, "reason": "",
                                      "applied": [l.to_dict() for l in applied],
                                      "reverses": settlement_id})
        self._apply_all(self._events[-1:], into=self)
        return rec

    # ---------- восстановление ----------

    def interrupted(self) -> list[Settlement]:
        return [s for s in self.settlements.values() if s.state == INTERRUPTED]

    def recover(self) -> list[str]:
        """Компенсировать расчёты, прерванные смертью процесса.

        Что именно успело примениться, известно не из памяти, а из журнала:
        проводки саги помечены её ключом в поле ref. Поэтому восстановление
        работает и в процессе, который ничего о прежнем запуске не знает.
        """
        healed: list[str] = []
        for s in self.interrupted():
            applied = [
                Leg(rec["payload"]["src"], rec["payload"]["dst"],
                    int(rec["payload"]["cents"]), rec["payload"].get("note", ""))
                for rec in self._events
                if rec["kind"] == "transfer" and rec["payload"].get("ref") == s.id
            ]
            self._compensate(applied, s.id)
            self._append("saga.recover", {
                "id": s.id, "compensated": [l.to_dict() for l in applied],
                "reason": "расчёт был прерван: применённые плечи откатаны",
            })
            self._apply_all(self._events[-1:], into=self)
            healed.append(s.id)
        return healed

    # ---------- проверка ----------

    def verify_invariants(self) -> list[str]:
        """Список нарушений. Пустой список означает, что всё сошлось.

        Возвращается список, а не bool: если расчёт разъехался, спрашивающему
        нужно знать ЧТО именно разъехалось, а не только что «что-то не так».
        """
        bad: list[str] = []

        # 1. Масса денег. Главный инвариант двойной записи.
        mass = self.total_mass()
        if mass != self.issued:
            bad.append(f"масса денег не сохранилась: сумма остатков {money(mass)} "
                       f"≠ эмиссия {money(self.issued)}")

        # 2-3. Остатки и удержания по каждому счёту.
        for acc in self.accounts.values():
            if acc.balance < 0 and not acc.allow_negative:
                bad.append(f"счёт '{acc.id}' ушёл в минус: {money(acc.balance)}")
            if acc.held < 0:
                bad.append(f"счёт '{acc.id}': отрицательное удержание {money(acc.held)}")
            if acc.held > acc.balance:
                bad.append(f"счёт '{acc.id}': удержано {money(acc.held)} "
                           f"больше остатка {money(acc.balance)}")

        # 4. Удержания счёта обязаны быть суммой его действующих эскроу.
        per_owner: dict[str, int] = {}
        for esc in self.escrows.values():
            if esc.active:
                per_owner[esc.owner] = per_owner.get(esc.owner, 0) + esc.cents
        for acc in self.accounts.values():
            expect = per_owner.get(acc.id, 0)
            if acc.held != expect:
                bad.append(f"счёт '{acc.id}': удержано {money(acc.held)}, "
                           f"а действующих эскроу на {money(expect)}")

        # 5. Незакрытые расчёты.
        for s in self.settlements.values():
            if s.state == INTERRUPTED:
                bad.append(f"расчёт '{s.id}' прерван и не компенсирован")
            elif s.state == PENDING:
                bad.append(f"расчёт '{s.id}' висит в состоянии pending")

        # 6. Цепь журнала.
        prev = GENESIS
        for i, rec in enumerate(self._events):
            if rec["seq"] != i:
                bad.append(f"журнал расчётов: нарушена нумерация на записи {i}")
                break
            if rec["prev"] != prev:
                bad.append(f"журнал расчётов: запись {i} не сцеплена с предыдущей")
                break
            if record_hash(rec["seq"], rec["ts"], rec["kind"], rec["payload"], rec["prev"]) != rec["hash"]:
                bad.append(f"журнал расчётов: запись {i} изменена (хэш не сходится)")
                break
            prev = rec["hash"]

        # 7. Память обязана быть ровно свёрткой журнала.
        shadow = _Shadow()
        try:
            self._apply_all(self._events, into=shadow)
        except Exception as e:  # noqa: BLE001 — журнал нечитаем сам по себе
            bad.append(f"журнал расчётов не сворачивается: {e}")
        else:
            for acc in self.accounts.values():
                mirror = shadow.accounts.get(acc.id)
                if mirror is None or mirror.balance != acc.balance or mirror.held != acc.held:
                    bad.append(f"счёт '{acc.id}': состояние в памяти расходится с журналом")
            if shadow.issued != self.issued:
                bad.append("эмиссия в памяти расходится с журналом")

        return bad

    def reload(self) -> "Book":
        """Перечитать с диска — доказательство персистентности, как у журнала."""
        return Book(self.path)

    # ---------- показ ----------

    def statement(self) -> list[dict[str, Any]]:
        """Выписка по счетам — то, что можно показать человеку."""
        return [
            {"account": a.id, "kind": a.kind, "balance": money(a.balance),
             "held": money(a.held), "available": money(a.available)}
            for a in sorted(self.accounts.values(), key=lambda x: x.id)
        ]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)


class _Shadow:
    """Пустая копия состояния для сверки свёртки журнала с памятью."""

    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}
        self.escrows: dict[str, Escrow] = {}
        self.settlements: dict[str, Settlement] = {}
        self.issued = 0


def _legs(legs: Iterable[Leg | tuple]) -> list[Leg]:
    out: list[Leg] = []
    for item in legs:
        if isinstance(item, Leg):
            out.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 3:
            out.append(Leg(item[0], item[1], int(item[2]),
                           item[3] if len(item) > 3 else ""))
        else:
            raise SettlementError(f"плечо задано непонятно: {item!r}")
    if not out:
        raise SettlementError("расчёт без плеч не является расчётом")
    return out


def split_with_fee(payer: str, payee: str, platform: str, cents: int,
                   fee_bps: int = 0) -> list[Leg]:
    """Разложить сумму на плечи «исполнителю» и «комиссия платформы».

    Комиссия считается целочисленно и вычитается, а не прибавляется: сумма
    плеч обязана в точности равняться удержанию, иначе выплата не сойдётся
    с эскроу. Остаток от деления достаётся исполнителю — потерянный цент
    должен оказаться у человека, а не у платформы.
    """
    if not 0 <= fee_bps <= 10_000:
        raise SettlementError("комиссия задаётся в базисных пунктах 0…10000")
    fee = cents * fee_bps // 10_000
    legs = [Leg(payer, payee, cents - fee, "выплата исполнителю")]
    if fee:
        legs.append(Leg(payer, platform, fee, f"комиссия платформы {fee_bps / 100:g}%"))
    return legs
