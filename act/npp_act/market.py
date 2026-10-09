"""Переговоры двух агентов и превращение сделки в обязательство (NPP-Act §7).

ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ
----------------------------
Межпрофильное взаимодействие — «мой агент договаривается с агентом заведения» —
упирается в один вопрос: чем кончается разговор. Прототип agent-market в daten2
доводил торг до цены и останавливался на этом: результатом был объект `deal` в
памяти процесса. Такая сделка никого ни к чему не обязывает — её нельзя
предъявить, нельзя исполнить и нельзя оспорить. Прототип a2a-settlement умел
обратное — считать деньги, — но не умел договариваться.

Здесь обе ветки посажены на NPP-Act, и порядок шагов получается ровно такой,
какой требует §4.2: СНАЧАЛА ОБРАТИМОЕ, ПОТОМ ОБЯЗАТЕЛЬСТВО.

    1. торг            — ничего не меняет в мире (effect=read по сути)
    2. удержание денег — обратимо: reserve в книге расчётов
    3. обязательство   — Agent.commit_two_party: запись в ОБА журнала
    4. выплата         — необратима и только после события (приёмки)

Если шаг 3 не состоялся, шаг 2 обязан быть отпущен: деньги не должны залипать
из-за несостоявшейся сделки — ровно как удержание слота в §7.

ПОЧЕМУ ТОРГ ДЕТЕРМИНИРОВАННЫЙ
-----------------------------
Ни одного random. Не из вкусовщины: переговоры агентов — это решение, которое
придётся объяснять человеку и, возможно, предъявлять как доказательство
добросовестности. Протокол, дающий разный исход на одних входах, объяснить
нельзя. Поэтому уступка здесь — функция номера раунда, а выбор конкретного
предложения — детерминированный перебор сетки с устойчивым порядком сравнения.

ПОЧЕМУ ТРИ ИЗМЕРЕНИЯ, А НЕ ОДНА ЦЕНА
------------------------------------
Торг по одной цене — игра с нулевой суммой: уступка одного есть ровно потеря
одного. Как только измерений больше одного (цена, срок, качество) и стороны
ценят их по-разному, появляется обмен уступками: отдать то, что мне дешево, за
то, что мне дорого. Поэтому каждая сторона уступает по собственной функции
полезности, а конкретное предложение выбирает ближайшее к последнему
предложению противной стороны — это и есть обмен, а не просто сдвиг цены.

РЕЗЕРВНАЯ ЦЕНА — ЖЁСТКАЯ. Полезность за резервом отрицательна, и предложение за
резервом неприемлемо, сколько бы ни было выгодно по другим измерениям. Без
этого «переговоры» всегда сходились бы, что означало бы лишь одно: агент
согласится на что угодно. Поэтому непересекающиеся резервные цены обязаны
давать расхождение, и это проверяется тестом.

Зависимостей нет: стандартная библиотека. Двустороннее обязательство не
дублируется — берётся Agent.commit_two_party из act.npp_act.agent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .agent import Agent, Commitment, Hold
from .governor import Decision
from .settlement import Book, Leg, Settlement, SettlementError, money, split_with_fee

BUYER, SELLER = "buyer", "seller"

#: Сколько точек брать по цене при переборе сетки предложений. Девять — это
#: шаг в 12.5% диапазона: достаточно мелко, чтобы уступка была видна, и
#: достаточно крупно, чтобы перебор оставался обозримым для человека.
PRICE_STEPS = 9
#: Предел перебора по целочисленным измерениям (срок, качество).
INT_STEPS = 12


# ───────────────────────────── предложение ─────────────────────────────

@dataclass(frozen=True)
class Offer:
    """Предложение по трём измерениям.

    `price_cents` — цена в целых центах (как во всём расчётном слое).
    `term` — срок/объём в целых единицах (для цеха это часы недели).
    `quality` — уровень качества или требуемой репутации, целое.
    """

    price_cents: int
    term: int
    quality: int

    @property
    def price(self) -> float:
        return money(self.price_cents)

    def key(self) -> tuple[int, int, int]:
        return (self.price_cents, self.term, self.quality)

    def __str__(self) -> str:
        return f"{self.price:.2f} EUR / {self.term} ед. / качество {self.quality}"


@dataclass
class Preference:
    """Что сторона считает хорошим и где её предел.

    Для каждого измерения заданы две точки: `*_best` — идеал, `*_reserve` —
    резерв, за которым сделка неприемлема. Направление измерения кодируется
    самим порядком этих точек: у заказчика цена best ниже reserve, у
    исполнителя — выше. Поэтому одна и та же формула полезности работает для
    обеих сторон, и ни одна из них не описана в коде «особым случаем».
    """

    price_best: int
    price_reserve: int
    term_best: int
    term_reserve: int
    quality_best: int
    quality_reserve: int
    w_price: float = 0.6
    w_term: float = 0.25
    w_quality: float = 0.15
    #: Порог полезности, ниже которого сторона не подписывает. 0.0 означает
    #: «готов на худшее приемлемое по всем измерениям, но не хуже».
    reserve_utility: float = 0.0

    def __post_init__(self) -> None:
        total = self.w_price + self.w_term + self.w_quality
        if total <= 0:
            raise ValueError("веса измерений должны быть положительны")
        # Нормируем веса: иначе полезности двух сторон несравнимы между собой,
        # и «уступил больше» перестаёт что-либо значить.
        self.w_price /= total
        self.w_term /= total
        self.w_quality /= total
        for best, res, name in (
            (self.price_best, self.price_reserve, "цена"),
            (self.term_best, self.term_reserve, "срок"),
            (self.quality_best, self.quality_reserve, "качество"),
        ):
            if best == res:
                raise ValueError(f"измерение '{name}': идеал и резерв совпали — торговаться нечем")

    # ---------- полезность ----------

    @staticmethod
    def _u(x: float, best: float, reserve: float) -> float:
        """1.0 в идеале, 0.0 на резерве, отрицательно за резервом."""
        return (reserve - x) / (reserve - best)

    def parts(self, offer: Offer) -> tuple[float, float, float]:
        return (
            self._u(offer.price_cents, self.price_best, self.price_reserve),
            self._u(offer.term, self.term_best, self.term_reserve),
            self._u(offer.quality, self.quality_best, self.quality_reserve),
        )

    def utility(self, offer: Offer) -> float:
        up, ut, uq = self.parts(offer)
        return self.w_price * up + self.w_term * ut + self.w_quality * uq

    def within_reserve(self, offer: Offer) -> bool:
        """Все измерения не за резервом. Жёсткое условие, не компенсируемое."""
        return all(u >= -1e-9 for u in self.parts(offer))

    def acceptable(self, offer: Offer) -> bool:
        return self.within_reserve(offer) and self.utility(offer) >= self.reserve_utility - 1e-9

    @property
    def ideal(self) -> Offer:
        return Offer(self.price_best, self.term_best, self.quality_best)

    @property
    def last_resort(self) -> Offer:
        """Худшее приемлемое: уступка по всем измерениям сразу."""
        return Offer(self.price_reserve, self.term_reserve, self.quality_reserve)

    # ---------- сетка предложений ----------

    def grid(self) -> list[Offer]:
        prices = _span(self.price_best, self.price_reserve, PRICE_STEPS)
        terms = _span(self.term_best, self.term_reserve, INT_STEPS)
        quals = _span(self.quality_best, self.quality_reserve, INT_STEPS)
        return [Offer(p, t, q) for p in prices for t in terms for q in quals]


def _span(best: int, reserve: int, steps: int) -> list[int]:
    """Целые точки от идеала к резерву включительно, без повторов."""
    lo, hi = min(best, reserve), max(best, reserve)
    count = min(steps, hi - lo + 1)
    if count <= 1:
        return [best]
    vals = sorted({lo + round(i * (hi - lo) / (count - 1)) for i in range(count)})
    return vals if best <= reserve else list(reversed(vals))


# ───────────────────────────── сторона ─────────────────────────────

@dataclass
class Party:
    """Сторона переговоров: имя профиля, предпочтения и манера уступать.

    `beta` — показатель уступчивости. 1.0 — уступать равномерно, меньше 1 —
    уступить почти всё сразу, больше 1 — держаться до последнего раунда.
    Это тактика, а не предпочтение: на то, что сторона в итоге подпишет,
    она не влияет — предел задаёт только резерв.
    """

    profile: str
    role: str
    pref: Preference
    beta: float = 1.0
    _grid: list[Offer] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.role not in (BUYER, SELLER):
            raise ValueError(f"роль должна быть '{BUYER}' или '{SELLER}', а не {self.role!r}")
        self._grid = self.pref.grid()

    def target(self, round_no: int, rounds: int) -> float:
        """Полезность, ниже которой сторона в этом раунде не предлагает.

        В первом раунде это идеал (1.0), в последнем — резерв. Монотонное
        снижение и есть уступка; она объявлена заранее и не зависит от того,
        что делает противная сторона, — поэтому торг нельзя затянуть, вынуждая
        к уступке молчанием.
        """
        if rounds <= 1:
            return self.pref.reserve_utility
        t = min(max((round_no - 1) / (rounds - 1), 0.0), 1.0)
        top = 1.0
        return top - (top - self.pref.reserve_utility) * (t ** self.beta)

    def propose(self, round_no: int, rounds: int, opponent: Offer | None) -> Offer:
        """Выбрать предложение: не ниже целевой полезности, максимально близкое
        к последнему предложению противной стороны.

        Второе условие — тот самый обмен уступками: среди равноценных для меня
        вариантов выбирается тот, который ближе к желаемому для соседа. Чужие
        веса при этом неизвестны и не угадываются — используется расстояние в
        МОИХ нормированных координатах, то есть честная мера «насколько я
        сдвинулся в его сторону».
        """
        goal = self.target(round_no, rounds)
        fit = [o for o in self._grid if self.pref.utility(o) >= goal - 1e-9]
        if not fit:  # вырожденный случай: держимся идеала
            fit = [self.pref.ideal]
        if opponent is None:
            return max(fit, key=lambda o: (self.pref.utility(o), -o.price_cents))
        return min(fit, key=lambda o: (round(self._distance(o, opponent), 9),
                                       -round(self.pref.utility(o), 9), o.key()))

    def _distance(self, a: Offer, b: Offer) -> float:
        pa, ta, qa = self.pref.parts(a)
        pb, tb, qb = self.pref.parts(b)
        return abs(pa - pb) + abs(ta - tb) + abs(qa - qb)


# ───────────────────────────── протокол торга ─────────────────────────────

@dataclass
class Move:
    """Ход в переговорах. Стенограмма целиком пишется в журнал инициатора."""

    round: int
    profile: str
    kind: str  # open | counter | accept | reject
    offer: Offer | None
    utility: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"round": self.round, "profile": self.profile, "kind": self.kind,
                "offer": None if self.offer is None else
                         {"price": self.offer.price, "term": self.offer.term,
                          "quality": self.offer.quality},
                "utility": round(self.utility, 4), "note": self.note}


@dataclass
class Deal:
    """Сделка: согласованное предложение и кто именно его принял."""

    offer: Offer
    round: int
    accepted_by: str
    utilities: dict[str, float]

    @property
    def price_cents(self) -> int:
        return self.offer.price_cents

    def fingerprint(self, parties: Sequence[str], subject: str = "") -> str:
        """Детерминированный отпечаток сделки — основа ключей идемпотентности.

        Один и тот же торг обязан давать один и тот же ключ: иначе повторный
        прогон после обрыва сети создал бы второе обязательство на ту же сделку.
        """
        seed = "|".join(sorted(parties)) + "|" + subject + "|" + repr(self.offer.key())
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


@dataclass
class Outcome:
    """Исход переговоров: сделка либо расхождение, и полная стенограмма."""

    deal: Deal | None
    moves: list[Move]
    rounds: int
    reason: str = ""

    @property
    def agreed(self) -> bool:
        return self.deal is not None

    def transcript(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.moves]


def negotiate(buyer: Party, seller: Party, rounds: int = 8) -> Outcome:
    """Провести торг. Детерминированно: одни входы — один исход.

    Порядок хода имеет значение и выбран сознательно: открывает продавец (он
    единственный знает свою цену — ровно как в цехе, где цены нет до оценки),
    отвечает покупатель. Принять чужое предложение сторона вправе только если
    оно не хуже её собственной цели этого раунда: иначе «уступчивость» означала
    бы согласие на что угодно в первом же раунде.
    """
    if buyer.role != BUYER or seller.role != SELLER:
        raise ValueError("ожидаются одна сторона-покупатель и одна сторона-продавец")

    moves: list[Move] = []
    ask = seller.propose(1, rounds, None)
    moves.append(Move(0, seller.profile, "open", ask, seller.pref.utility(ask),
                      "открывающее предложение"))
    bid: Offer | None = None

    for r in range(1, rounds + 1):
        # --- покупатель: принять или ответить ---
        u_buy = buyer.pref.utility(ask)
        if buyer.pref.acceptable(ask) and u_buy >= buyer.target(r, rounds) - 1e-9:
            moves.append(Move(r, buyer.profile, "accept", ask, u_buy, "принято покупателем"))
            return Outcome(
                Deal(ask, r, buyer.profile,
                     {buyer.profile: u_buy, seller.profile: seller.pref.utility(ask)}),
                moves, r)
        bid = buyer.propose(r, rounds, ask)
        moves.append(Move(r, buyer.profile, "counter", bid, buyer.pref.utility(bid),
                          "встречное предложение"))

        # --- продавец: принять или ответить ---
        u_sell = seller.pref.utility(bid)
        if seller.pref.acceptable(bid) and u_sell >= seller.target(r, rounds) - 1e-9:
            moves.append(Move(r, seller.profile, "accept", bid, u_sell, "принято продавцом"))
            return Outcome(
                Deal(bid, r, seller.profile,
                     {buyer.profile: buyer.pref.utility(bid), seller.profile: u_sell}),
                moves, r)
        ask = seller.propose(r + 1, rounds, bid)
        moves.append(Move(r, seller.profile, "counter", ask, seller.pref.utility(ask),
                          "встречное предложение"))

    reason = _why_diverged(buyer, seller)
    moves.append(Move(rounds, seller.profile, "reject", seller.pref.last_resort,
                      seller.pref.reserve_utility, reason))
    return Outcome(None, moves, rounds, reason)


def _why_diverged(buyer: Party, seller: Party) -> str:
    """Назвать измерение, на котором резервы не пересеклись.

    Агент, вернувший «не договорились», бесполезен: человеку нужно знать, на
    чём именно разошлись, чтобы решить, менять ли свой предел.
    """
    gaps = []
    if buyer.pref.price_reserve < seller.pref.price_reserve:
        gaps.append(f"цена: предел заказчика {money(buyer.pref.price_reserve)} ниже "
                    f"предела исполнителя {money(seller.pref.price_reserve)}")
    if not _overlap(buyer.pref.term_best, buyer.pref.term_reserve,
                    seller.pref.term_best, seller.pref.term_reserve):
        gaps.append("срок: допустимые диапазоны не пересекаются")
    if not _overlap(buyer.pref.quality_best, buyer.pref.quality_reserve,
                    seller.pref.quality_best, seller.pref.quality_reserve):
        gaps.append("качество: допустимые диапазоны не пересекаются")
    if not gaps:
        return "раунды исчерпаны: уступок не хватило, хотя пределы пересекаются"
    return "расхождение — " + "; ".join(gaps)


def _overlap(a1: int, a2: int, b1: int, b2: int) -> bool:
    lo_a, hi_a = min(a1, a2), max(a1, a2)
    lo_b, hi_b = min(b1, b2), max(b1, b2)
    return lo_a <= hi_b and lo_b <= hi_a


# ───────────────────────────── сделка → обязательство ─────────────────────────────

@dataclass
class Concluded:
    """Чем кончилась сделка в мире, а не в памяти процесса."""

    deal: Deal | None
    decision: Decision | None = None
    commitment: Commitment | None = None
    settlement: Settlement | None = None
    escrow_id: str = ""
    settlement_id: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        """Сделка состоялась только если обязательство записано у обеих сторон."""
        return self.commitment is not None

    @property
    def paid(self) -> bool:
        return self.settlement is not None and self.settlement.ok


def conclude(
    outcome: Outcome | Deal,
    *,
    initiator: Agent,
    counterparty: Agent,
    service: str,
    verb: str,
    payload: dict[str, Any],
    book: Book | None = None,
    payer: str = "",
    payee: str = "",
    platform: str = "",
    fee_bps: int = 0,
    splits: Iterable[Leg | tuple] | None = None,
    subject: str = "",
    hold: Hold | None = None,
    capture: bool = False,
    attempt: str = "",
) -> Concluded:
    """Превратить сделку в обязательство и удержать деньги под него.

    Порядок шагов — главное, что здесь есть, и он не переставляется:

    1. Деньги удерживаются в книге расчётов (обратимо).
    2. Обязательство оформляется через Agent.commit_two_party — тот самый
       четырёхшаговый протокол §7, который уже реализован и не дублируется.
    3. Если обязательство не состоялось, удержание ОБЯЗАНО быть отпущено.

    По умолчанию выплаты здесь нет: деньги остаются удержанными до события,
    ради которого эскроу и существует (приёмка работы, поставка). Выплатить
    их — отдельный необратимый шаг: pay_out(). Для сделок, где обязательство и
    расчёт совпадают во времени («товар в руки»), есть capture=True.

    `attempt` — нонс осознанной ПОВТОРНОЙ попытки. Пустой нонс означает, что
    ключи выводятся из самой сделки, и тогда случайный повторный вызов не
    делает ничего. Новая попытка после провала — это решение человека или
    агента, и она обязана быть названа явно, а не получиться из ретрая.
    """
    deal = outcome.deal if isinstance(outcome, Outcome) else outcome
    if deal is None:
        reason = outcome.reason if isinstance(outcome, Outcome) else "сделки нет"
        return Concluded(None, reason=reason or "переговоры разошлись")

    parties = [initiator.profile, counterparty.profile]
    subject = subject or f"{service}:{verb}"
    fp = deal.fingerprint(parties, subject + ("|" + attempt if attempt else ""))
    escrow_id = f"esc_{fp}"
    settlement_id = f"stl_{fp}"

    # Идемпотентность по ключу сделки: тот же торг не оформляется дважды.
    # Проверяется именно удержание, а не расчёт: удержание возникает ПЕРВЫМ,
    # и только по нему видно, что эта сделка уже доходила до денег. Иначе
    # повторный вызов отпустил бы эскроу, которым обеспечено уже подписанное
    # обязательство, — то есть снял бы обеспечение с живого контракта.
    if book is not None:
        prior = book.escrows.get(escrow_id)
        if prior is not None:
            return Concluded(deal, None, None, book.settlements.get(settlement_id),
                             escrow_id, settlement_id,
                             f"сделка с этим ключом уже оформлена (эскроу '{prior.state}') — "
                             "повтор не исполнен")

    # --- шаг 1: обратимое удержание денег ---
    if book is not None:
        if not payer:
            raise SettlementError("не указан счёт плательщика, а книга расчётов передана")
        book.reserve(payer, deal.price_cents, escrow_id, ref=subject)

    # --- шаг 2: двустороннее обязательство (§7), существующей реализацией ---
    decision, commitment = initiator.commit_two_party(
        service, verb, payload, counterparty=counterparty, hold=hold, subject=subject,
    )

    # --- шаг 3: сделка не состоялась → деньги не залипают ---
    if commitment is None:
        if book is not None:
            book.release(escrow_id)
        return Concluded(deal, decision, None, None, escrow_id, settlement_id,
                         f"обязательство не оформлено: {decision.reason}")

    # Стенограмма торга — часть доказательства: по ней видно, что цена не
    # выдумана агентом, а получена уступками, и где был предел каждой стороны.
    if isinstance(outcome, Outcome):
        initiator.ledger.append("outcome", {
            "kind": "negotiation", "commitment_id": commitment.id,
            "parties": parties, "rounds": outcome.rounds,
            "agreed": {"price": deal.offer.price, "term": deal.offer.term,
                       "quality": deal.offer.quality},
            "accepted_by": deal.accepted_by, "transcript": outcome.transcript(),
        })

    settlement = None
    if book is not None and capture:
        settlement = pay_out(book, escrow_id, payer=payer, payee=payee, platform=platform,
                             fee_bps=fee_bps, splits=splits, settlement_id=settlement_id)

    return Concluded(deal, decision, commitment, settlement, escrow_id, settlement_id,
                     "обязательство записано в оба журнала")


def pay_out(
    book: Book,
    escrow_id: str,
    *,
    payer: str,
    payee: str = "",
    platform: str = "",
    fee_bps: int = 0,
    splits: Iterable[Leg | tuple] | None = None,
    settlement_id: str | None = None,
) -> Settlement:
    """Необратимая выплата удержанного — сагой, одним ключом, один раз.

    Плечей больше одного именно здесь: исполнителю и комиссия платформе. Пока
    выплата идёт одним переводом, «забыть» комиссию невозможно только на словах;
    сага же либо проводит оба плеча, либо не проводит ни одного.
    """
    esc = book.escrows.get(escrow_id)
    if esc is None:
        raise SettlementError(f"эскроу '{escrow_id}' не найден")
    legs = list(splits) if splits is not None else split_with_fee(
        payer, payee, platform or payee, esc.cents, fee_bps)
    return book.capture(escrow_id, legs, settlement_id=settlement_id)


def refund(book: Book, escrow_id: str) -> None:
    """Отпустить удержание: деньги остаются у заказчика и снова доступны.

    Это обратный глагол к шагу 1 и единственно правильный конец сделки, которая
    не доехала до приёмки. Отсутствие такого шага — та же болезнь, что залипший
    слот в §7: ресурс занят несостоявшейся сделкой.
    """
    book.release(escrow_id)


# ───────────────────────────── готовые роли ─────────────────────────────

def client_party(profile: str, *, max_price_cents: int, want_price_cents: int,
                 max_term: int, want_term: int,
                 min_quality: int = 3, want_quality: int = 5,
                 beta: float = 1.0) -> Party:
    """Заказчик: хочет дешевле, короче и качественнее; предел — по всем трём."""
    return Party(profile, BUYER, Preference(
        price_best=want_price_cents, price_reserve=max_price_cents,
        term_best=want_term, term_reserve=max_term,
        quality_best=want_quality, quality_reserve=min_quality,
        w_price=0.6, w_term=0.25, w_quality=0.15,
    ), beta=beta)


def contractor_party(profile: str, *, min_price_cents: int, want_price_cents: int,
                     min_term: int, want_term: int,
                     max_quality: int = 4, want_quality: int = 2,
                     beta: float = 1.0) -> Party:
    """Исполнитель: хочет дороже, свободнее по сроку и не обещать лишнего."""
    return Party(profile, SELLER, Preference(
        price_best=want_price_cents, price_reserve=min_price_cents,
        term_best=want_term, term_reserve=min_term,
        quality_best=want_quality, quality_reserve=max_quality,
        w_price=0.6, w_term=0.25, w_quality=0.15,
    ), beta=beta)
