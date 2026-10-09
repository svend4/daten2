"""Карта обязательств во времени и обнаружение «невозможных фигур» (поверх §6–§7).

Журнал отвечает на вопрос «что я сделал». Он не отвечает на вопрос, который
задаёт человек, живущий между домом, работой, магазином и садиком:
**можно ли вообще исполнить всё, на что я уже подписался.**

Обязательство (`kind="commitment"`) занимает не только деньги, но и ЧАС В ДНЕ.
Деньги губернатор считает — время до сих пор не считал никто. Отсюда модуль:
он разворачивает хэш-цепь в линию времени и ищет расписания, которые физически
неисполнимы. Такое расписание и есть «невозможная фигура»: каждое обязательство
по отдельности законно, а вместе они требуют быть в двух местах одновременно.

Три вида неисполнимости, которые видны из одних только записей:

    overlap   — два обязательства пересекаются по времени;
    travel    — промежутка между ними не хватает на дорогу;
    capacity  — за сутки набрано больше часов, чем в сутках есть.

ГЛАВНОЕ СЛЕДСТВИЕ ДЛЯ ПРОТОКОЛА. Конфликт обнаруживается ДО исполнения, значит
он — естественный кандидат в жёсткие предикаты губернатора (§5.1). Карта здесь
не иллюстрация: `would_conflict()` принимает ещё НЕ исполненное обязательство и
отвечает, что именно сломается. То есть у губернатора появляется основание
сказать `block` не из-за денег и не из-за необратимости, а потому что в
расписании владельца для этого действия нет места. Ровно так же, как отсутствие
ключа идемпотентности — отказ до вызова, а не ошибка после.

ЧЕСТНАЯ ОГОВОРКА О ФОРМАТЕ. NPP-Act 1.0 не объявляет у записи `commitment`
временны́х полей: §7 требует `commitment_id`, `parties` и хэши сторон. Поэтому
модуль берёт время двумя путями:

  1. из аннотации `payload["when"] = {starts_at, duration_min, place, role}`,
     если сторона её положила (предлагаемое расширение записи);
  2. иначе — разбором `subject`, куда агент уже пишет «приём 2026-10-12 09:00».

Второй путь работает на существующих журналах без их переписывания и именно он
показывает, чего формату не хватает: время сделки лежит в человекочитаемой
строке, а не в поле. Это аргумент за добавление `when` в §7, а не повод
подделать записи задним числом.

Время здесь НАИВНОЕ (без зоны) и намеренно: расписание человека живёт в местном
времени заведения, а смешивать aware и naive в одной шкале — верный способ
получить «невозможную фигуру» на пустом месте. Аннотация с зоной приводится к
UTC и теряет зону явно, одним местом в коде (`_naive`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from .ledger import Ledger

# виды конфликтов (строками — они уезжают в JSON и в HTML)
OVERLAP, TRAVEL, CAPACITY = "overlap", "travel", "capacity"
CONFLICT_KINDS = (OVERLAP, TRAVEL, CAPACITY)

#: Сколько длится обязательство, если длительность нигде не объявлена.
#: Час — не истина, а допущение; поэтому оно параметр, а не константа в коде.
DEFAULT_DURATION_MIN = 60

#: Дневная ёмкость человека по умолчанию. Не 24: спать, есть и ехать тоже надо.
DEFAULT_CAPACITY_HOURS = 10.0

#: «2026-10-12 09:00» или «2026-10-12T09:00» внутри произвольной строки subject.
_IN_SUBJECT = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})")


def _naive(value: Any) -> datetime | None:
    """Привести отметку времени к наивному datetime или вернуть None.

    Единственное место, где теряется зона: aware-время сначала переводится в UTC,
    и только потом обнуляется tzinfo. Иначе карта рисовалась бы в двух шкалах.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            m = _IN_SUBJECT.search(text)
            if not m:
                return None
            day, hhmm = m.groups()
            hour, minute = hhmm.split(":")
            return datetime.fromisoformat(f"{day}T{int(hour):02d}:{minute}")
    else:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _plural(n: int, one: str, few: str, many: str) -> str:
    """«1 запись», «4 записи», «5 записей».

    Мелочь, но объяснение конфликта читает человек, а не парсер: текст с
    «4 записей» выдаёт машину, которой всё равно, и ей перестают верить.
    """
    tail = n % 100
    if 11 <= tail <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _from_subject(subject: str) -> datetime | None:
    """Вытащить время сделки из человекочитаемого `subject`.

    Это сознательный компромисс: формат 1.0 не хранит время обязательства в
    поле, но агент уже кладёт его в строку предмета сделки. Разбор строки честнее
    выдумывания времени и прямо указывает, какого поля не хватает протоколу.
    """
    m = _IN_SUBJECT.search(subject or "")
    if not m:
        return None
    day, hhmm = m.groups()
    hour, minute = hhmm.split(":")
    try:
        return datetime.fromisoformat(f"{day}T{int(hour):02d}:{minute}")
    except ValueError:
        return None


# ────────────────────────────────────────────────────────────────────────────
# Обязательство как занятый отрезок времени
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Entry:
    """Одно обязательство, развёрнутое в отрезок времени.

    Поля `ledger_path` и `seq` держатся не для красоты: конфликт обязан быть
    ПРЕДЪЯВЛЯЕМЫМ. Имея их, проверяющий открывает журнал, находит строку и
    убеждается, что карта не придумала обязательство, которого никто не брал.
    """

    party: str
    commitment_id: str
    subject: str
    starts_at: datetime
    duration_min: int
    place: str
    role: str = ""
    service: str = ""
    verb: str = ""
    money: float = 0.0
    currency: str = "EUR"
    seq: int = -1
    ledger_path: str = ""

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.duration_min)

    @property
    def day(self) -> date:
        return self.starts_at.date()

    @property
    def track(self) -> str:
        """Дорожка на карте: роль, если объявлена, иначе место."""
        return self.role or self.place

    @property
    def ref(self) -> str:
        """Короткая ссылка на доказательство: «person:anna#7»."""
        return f"{self.party}#{self.seq}" if self.seq >= 0 else self.party

    @property
    def label(self) -> str:
        return self.subject or f"{self.service}:{self.verb}" or self.commitment_id

    def span(self) -> str:
        return f"{self.starts_at:%H:%M}–{self.ends_at:%H:%M}"

    @classmethod
    def proposed(
        cls,
        party: str,
        subject: str,
        starts_at: str | datetime,
        duration_min: int = DEFAULT_DURATION_MIN,
        place: str = "",
        role: str = "",
        service: str = "",
        verb: str = "",
        money: float = 0.0,
    ) -> "Entry":
        """Ещё не исполненное обязательство — вход для предиката губернатора.

        Такой записи в журнале нет и не должно быть: губернатор спрашивает
        «что сломается, если я это допущу», до того как что-либо произошло.
        """
        start = _naive(starts_at)
        if start is None:
            raise ValueError(f"не разобрать время начала: {starts_at!r}")
        return cls(
            party=party, commitment_id="(предложено)", subject=subject,
            starts_at=start, duration_min=int(duration_min),
            place=place or service or "—", role=role,
            service=service, verb=verb, money=float(money), seq=-1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "party": self.party,
            "commitment_id": self.commitment_id,
            "subject": self.subject,
            "label": self.label,
            "starts_at": self.starts_at.isoformat(timespec="minutes"),
            "ends_at": self.ends_at.isoformat(timespec="minutes"),
            "day": self.day.isoformat(),
            "duration_min": self.duration_min,
            "place": self.place,
            "role": self.role,
            "track": self.track,
            "service": self.service,
            "verb": self.verb,
            "money": self.money,
            "currency": self.currency,
            "seq": self.seq,
            "ref": self.ref,
            "ledger_path": self.ledger_path,
        }


# ────────────────────────────────────────────────────────────────────────────
# Матрица дороги
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class TravelMatrix:
    """Сколько минут нужно, чтобы попасть из одного места в другое.

    `default_between` по умолчанию 0, и это принципиально: карта НЕ ВПРАВЕ
    выдумывать конфликт из собственного незнания. Незаявленная пара мест
    считается «рядом», пока владелец не объявил иначе. Строгий режим
    («всё незнакомое — далеко») включается явно, одним числом.
    """

    minutes: dict[tuple[str, str], int] = field(default_factory=dict)
    default_between: int = 0

    @staticmethod
    def of(spec: "TravelMatrix | Mapping | None") -> "TravelMatrix":
        if spec is None:
            return TravelMatrix()
        if isinstance(spec, TravelMatrix):
            return spec
        return TravelMatrix({tuple(k): int(v) for k, v in dict(spec).items()})

    @staticmethod
    def parse(items: Iterable[str]) -> "TravelMatrix":
        """Разобрать записи вида «Дом>Садик=15» (для CLI)."""
        out: dict[tuple[str, str], int] = {}
        for raw in items:
            text = str(raw).strip()
            if not text:
                continue
            if "=" not in text or ">" not in text.split("=", 1)[0]:
                raise ValueError(f"ожидается «место>место=минуты», получено {raw!r}")
            pair, value = text.split("=", 1)
            a, b = (p.strip() for p in pair.split(">", 1))
            out[(a, b)] = int(value.strip())
        return TravelMatrix(out)

    def set(self, a: str, b: str, minutes: int) -> "TravelMatrix":
        self.minutes[(a, b)] = int(minutes)
        return self

    def between(self, a: str, b: str) -> int:
        """Дорога симметрична, пока не объявлено обратное (пробки — отдельная тема)."""
        if a == b:
            return 0
        if (a, b) in self.minutes:
            return self.minutes[(a, b)]
        if (b, a) in self.minutes:
            return self.minutes[(b, a)]
        return self.default_between

    def declared(self, a: str, b: str) -> bool:
        """Объявлена ли эта пара явно — чтобы объяснение не врало об источнике."""
        return a == b or (a, b) in self.minutes or (b, a) in self.minutes


# ────────────────────────────────────────────────────────────────────────────
# Конфликт
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Conflict:
    """Неисполнимость, найденная в расписании одной стороны."""

    kind: str
    party: str
    entries: tuple[Entry, ...]
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def day(self) -> date:
        return self.entries[0].day

    @property
    def refs(self) -> list[str]:
        return [e.ref for e in self.entries]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "party": self.party,
            "day": self.day.isoformat(),
            "message": self.message,
            "explain": explain(self),
            "detail": self.detail,
            "refs": self.refs,
            "entries": [e.to_dict() for e in self.entries],
        }


def explain(conflict: Conflict) -> str:
    """Человекочитаемое объяснение с ссылками на записи журнала.

    Объяснение обязано быть предъявляемым: не «конфликт обнаружен», а что с чем,
    почему неисполнимо и в каких строках чьих журналов это записано.
    """
    mark = {OVERLAP: "⨯", TRAVEL: "→", CAPACITY: "∑"}.get(conflict.kind, "!")
    refs = ", ".join(conflict.refs)
    return f"{mark} [{conflict.party}] {conflict.message} (записи: {refs})"


# ────────────────────────────────────────────────────────────────────────────
# Сборка линии времени из настоящих журналов
# ────────────────────────────────────────────────────────────────────────────


def _linked_outcome(records: Sequence[Any], upto: int, service: str, verb: str) -> dict[str, Any]:
    """Найти исход, к которому относится обязательство.

    Исполнитель пишет стадии в порядке intent → decision → execution → outcome,
    а запись `commitment` ложится после них. Поэтому связанный исход — последний
    успешный `outcome` того же сервиса и глагола ПЕРЕД обязательством. Оттуда
    берутся настоящие деньги (`charged`), а не объявленная в манифесте цена.
    """
    best: dict[str, Any] = {}
    for rec in records:
        if rec.seq >= upto:
            break
        if rec.kind != "outcome":
            continue
        p = rec.payload
        if p.get("service") == service and p.get("verb") == verb and p.get("ok"):
            best = p
    return best


def build_timeline(
    ledgers: Mapping[str, Ledger],
    *,
    place_of: Mapping[str, str] | None = None,
    role_of: Mapping[str, str] | None = None,
    default_duration_min: int = DEFAULT_DURATION_MIN,
    verify: bool = True,
) -> list[Entry]:
    """Развернуть журналы сторон в линию времени.

    Ключ словаря — профиль стороны (`person:anna`), он же становится владельцем
    обязательства. Это важнее, чем кажется: конфликты считаются ВНУТРИ одной
    стороны. Приём Анны не мешает приёму Бориса, зато клиника, записавшая двоих
    на один час к одному специалисту, получит конфликт у себя — и правильно.

    `verify=True` по умолчанию: карта, построенная по разорванной цепи, не имеет
    доказательной силы, поэтому проверка сцепления идёт до чтения записей.
    """
    places = dict(place_of or {})
    roles = dict(role_of or {})
    timeline: list[Entry] = []

    for party, led in ledgers.items():
        if verify:
            led.verify()
        records = list(led)
        seen: set[str] = set()

        for rec in records:
            if rec.kind != "commitment":
                continue
            p = rec.payload
            when = p.get("when") if isinstance(p.get("when"), dict) else {}

            service = str(p.get("service") or when.get("service") or "")
            verb = str(p.get("verb") or "")
            subject = str(p.get("subject") or "")

            starts = _naive(when.get("starts_at") or p.get("starts_at")) or _from_subject(subject)
            if starts is None:
                # Обязательство без распознаваемого времени на карту не попадает:
                # лучше честный пропуск, чем отрезок, поставленный наугад.
                continue

            cid = str(p.get("commitment_id") or f"{party}#{rec.seq}")
            if cid in seen:
                continue  # одно обязательство — один отрезок у стороны
            seen.add(cid)

            out = _linked_outcome(records, rec.seq, service, verb)
            response = out.get("response") if isinstance(out.get("response"), dict) else {}

            money = when.get("money", p.get("money"))
            if money is None:
                money = out.get("charged") or 0.0

            timeline.append(Entry(
                party=party,
                commitment_id=cid,
                subject=subject,
                starts_at=starts,
                duration_min=int(when.get("duration_min") or p.get("duration_min")
                                 or default_duration_min),
                place=str(when.get("place") or p.get("place") or places.get(service)
                          or service or "—"),
                role=str(when.get("role") or p.get("role") or roles.get(service) or ""),
                service=service,
                verb=verb,
                money=float(money),
                currency=str(response.get("currency") or when.get("currency") or "EUR"),
                seq=rec.seq,
                ledger_path=str(led.path),
            ))

    timeline.sort(key=lambda e: (e.starts_at, e.party, e.place))
    return timeline


def load_timeline(
    paths: Mapping[str, str],
    **kwargs: Any,
) -> list[Entry]:
    """То же, но по путям к файлам журналов: {профиль: путь к .jsonl}."""
    return build_timeline({party: Ledger(path, owner=party) for party, path in paths.items()},
                          **kwargs)


# ────────────────────────────────────────────────────────────────────────────
# Обнаружение неисполнимости
# ────────────────────────────────────────────────────────────────────────────


def _overlap_minutes(a: Entry, b: Entry) -> int:
    start = max(a.starts_at, b.starts_at)
    end = min(a.ends_at, b.ends_at)
    return max(0, int((end - start).total_seconds() // 60))


def _pair_conflict(a: Entry, b: Entry, travel: TravelMatrix) -> Conflict | None:
    """Проверить одну упорядоченную во времени пару обязательств.

    Порядок проверок не произволен: пересечение сильнее недостижимости. Если
    отрезки наложились, сообщать ещё и о дороге бессмысленно — человек и так уже
    должен быть в двух местах сразу, а два сообщения об одной беде только
    маскируют остальные.
    """
    over = _overlap_minutes(a, b)
    if over > 0:
        where = (f"в разных местах — «{a.place}» и «{b.place}»"
                 if a.place != b.place else f"в одном месте «{a.place}»")
        return Conflict(
            kind=OVERLAP, party=a.party, entries=(a, b),
            message=(f"«{a.label}» ({a.place}, {a.span()}) и «{b.label}» "
                     f"({b.place}, {b.span()}) пересекаются на {over} мин {where}: "
                     f"исполнить оба обязательства нельзя"),
            detail={"overlap_min": over, "places": [a.place, b.place]},
        )

    need = travel.between(a.place, b.place)
    if need <= 0:
        return None
    gap = int((b.starts_at - a.ends_at).total_seconds() // 60)
    if gap >= need:
        return None
    source = "по объявленной матрице" if travel.declared(a.place, b.place) else "по умолчанию"
    return Conflict(
        kind=TRAVEL, party=a.party, entries=(a, b),
        message=(f"«{a.label}» заканчивается в {a.ends_at:%H:%M} в «{a.place}», "
                 f"а «{b.label}» начинается в {b.starts_at:%H:%M} в «{b.place}»; "
                 f"дорога занимает {need} мин ({source}), в запасе {gap} мин — "
                 f"опоздание на {need - gap} мин"),
        detail={"gap_min": gap, "need_min": need, "late_min": need - gap,
                "from": a.place, "to": b.place},
    )


def detect_conflicts(
    timeline: Sequence[Entry],
    *,
    travel: "TravelMatrix | Mapping | None" = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
) -> list[Conflict]:
    """Найти всё, что в этом расписании физически неисполнимо.

    Проверка идёт по каждой стороне отдельно и целиком до исполнения: именно
    поэтому результат годится губернатору как предикат, а не только человеку
    как картинка.
    """
    matrix = TravelMatrix.of(travel)
    conflicts: list[Conflict] = []

    by_party: dict[str, list[Entry]] = {}
    for e in timeline:
        by_party.setdefault(e.party, []).append(e)

    for party, entries in sorted(by_party.items()):
        ordered = sorted(entries, key=lambda e: (e.starts_at, e.ends_at, e.place))

        # Пары. Перебор полный, а не только соседний: обязательство длиной в день
        # накрывает не только следующее за ним. Записей на карте человека единицы,
        # поэтому квадрат здесь дешевле неверного ответа.
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                if b.starts_at >= a.ends_at and matrix.between(a.place, b.place) <= 0:
                    continue  # дальше по времени — тем более не конфликт
                found = _pair_conflict(a, b, matrix)
                if found is not None:
                    conflicts.append(found)

        # Дневная ёмкость. Это не «много дел», а арифметическая невозможность:
        # сумма занятых часов больше, чем владелец объявил посильным за сутки.
        limit_min = capacity_hours * 60
        by_day: dict[date, list[Entry]] = {}
        for e in ordered:
            by_day.setdefault(e.day, []).append(e)
        for day, same_day in sorted(by_day.items()):
            busy = sum(e.duration_min for e in same_day)
            if busy > limit_min:
                conflicts.append(Conflict(
                    kind=CAPACITY, party=party, entries=tuple(same_day),
                    message=(f"{day:%Y-%m-%d}: обязательств на {busy / 60:.1f} ч "
                             f"при дневной ёмкости {capacity_hours:.1f} ч "
                             f"(превышение {(busy - limit_min) / 60:.1f} ч, "
                             f"{len(same_day)} "
                             f"{_plural(len(same_day), 'запись', 'записи', 'записей')})"
                             f" — день не вмещает взятого"),
                    detail={"busy_min": busy, "limit_min": limit_min,
                            "over_min": busy - limit_min, "count": len(same_day)},
                ))

    conflicts.sort(key=lambda c: (c.entries[0].starts_at, c.party, c.kind))
    return conflicts


def would_conflict(
    timeline: Sequence[Entry],
    candidate: Entry,
    *,
    travel: "TravelMatrix | Mapping | None" = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
) -> list[Conflict]:
    """Что сломается, если допустить ЕЩЁ НЕ взятое обязательство.

    Это и есть форма, в которой карта превращается в предикат губернатора:
    на вход — предлагаемое действие, на выход — перечень неисполнимостей, каждая
    с объяснением. Пустой список значит «в расписании место есть».
    """
    # Вычитаем то, что было неисполнимо и без нового обязательства: губернатор
    # не вправе отказывать за грехи, которые владелец уже совершил раньше.
    before = detect_conflicts(timeline, travel=travel, capacity_hours=capacity_hours)
    before_keys = {(c.kind, c.party, tuple(c.refs), c.message) for c in before}

    after = detect_conflicts([*timeline, candidate], travel=travel,
                             capacity_hours=capacity_hours)
    return [c for c in after
            if (c.kind, c.party, tuple(c.refs), c.message) not in before_keys
            and any(e is candidate for e in c.entries)]


def governor_predicate(
    timeline: Sequence[Entry],
    *,
    travel: "TravelMatrix | Mapping | None" = None,
    capacity_hours: float = DEFAULT_CAPACITY_HOURS,
) -> Callable[[Entry], list[Conflict]]:
    """Замкнуть карту в предикат: Entry → список причин для `block`.

    Губернатору не нужен весь модуль — ему нужна функция одного аргумента,
    которую можно позвать в §5.1 рядом с бюджетом и идемпотентностью.
    """
    def predicate(candidate: Entry) -> list[Conflict]:
        return would_conflict(timeline, candidate, travel=travel,
                              capacity_hours=capacity_hours)
    return predicate


# ────────────────────────────────────────────────────────────────────────────
# Сводка для CLI и визуализации
# ────────────────────────────────────────────────────────────────────────────


def summary(timeline: Sequence[Entry], conflicts: Sequence[Conflict]) -> dict[str, Any]:
    """Короткая сводка: сколько взято, на сколько часов, сколько неисполнимого."""
    counts = {k: 0 for k in CONFLICT_KINDS}
    for c in conflicts:
        counts[c.kind] = counts.get(c.kind, 0) + 1
    days = sorted({e.day.isoformat() for e in timeline})
    return {
        "entries": len(timeline),
        "parties": sorted({e.party for e in timeline}),
        "tracks": sorted({e.track for e in timeline}),
        "days": days,
        "busy_hours": round(sum(e.duration_min for e in timeline) / 60, 2),
        "money": round(sum(e.money for e in timeline), 2),
        "conflicts": len(conflicts),
        "by_kind": counts,
        "feasible": not conflicts,
    }


def to_payload(timeline: Sequence[Entry], conflicts: Sequence[Conflict]) -> dict[str, Any]:
    """Данные для встраивания в HTML или выдачи в stdout одним объектом."""
    refs_in_conflict: dict[str, list[str]] = {}
    for c in conflicts:
        for e in c.entries:
            refs_in_conflict.setdefault(e.ref, []).append(c.kind)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary(timeline, conflicts),
        "entries": [e.to_dict() for e in timeline],
        "conflicts": [c.to_dict() for c in conflicts],
        "conflict_refs": {k: sorted(set(v)) for k, v in refs_in_conflict.items()},
    }
