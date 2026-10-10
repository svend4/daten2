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

ОТКУДА БЕРЁТСЯ ВРЕМЯ ЗАПИСИ (после этапа 18). Спецификация объявила блок
`when` в §6.1, и агент его теперь действительно пишет. Поэтому источников два,
и порядок между ними не симметричен:

  1. `payload["when"] = {starts_at, duration_min, place, role}` — ОБЪЯВЛЕННОЕ
     время. Основной путь: поле, а не строка;
  2. разбор `subject` («приём 2026-10-12 09:00») — ДЕГРАДАЦИЯ для записей,
     сделанных до этапа 18, и только для них.

Второй путь оставлен не из вежливости к прошлому: журнал append-only, записи
без `when` в нём останутся навсегда, и карта, которая перестанет их видеть,
будет врать о прошлом владельца сильнее, чем неточная длительность.

ПОЧЕМУ ЗДЕСЬ ПРОВЕРКА `when` МЯГКАЯ, А В `schedule_guard` — ЖЁСТКАЯ. Разница
не в аккуратности, а в том, что ещё можно изменить. `schedule_guard` смотрит на
НАМЕРЕНИЕ: битый `when` там — повод отказать до действия, пока отказ ничего не
стоит. Карта смотрит на УЖЕ ЗАПИСАННОЕ: отвергать прошлое поздно, а упавшая
карта не показывает и исправных обязательств. Поэтому `normalize_when()`
(строгая, бросает `WhenError`) вызывается на входе агента, а `build_timeline()`
на непонятном `when` тихо откатывается к `subject` и к значениям по умолчанию.

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
# Объявленное время обязательства: блок `when` (§6.1)
# ────────────────────────────────────────────────────────────────────────────


#
# ТЕКСТ ДЛЯ СПЕЦИФИКАЦИИ (§6.1, уточнение к объявлению блока `when`)
#
#     Блок `when` **MUST** содержать `starts_at` — отметку времени ISO-8601 с
#     часами и минутами. Дата без времени суток **MUST** отвергаться: полночь,
#     подставленная вместо неуказанного часа, — догадка реализации, выданная за
#     объявление стороны. Отметка, из которой время приходится извлекать как
#     подстроку (например «приём 2026-10-12 09:00»), **MUST** отвергаться:
#     это `subject`, а не поле.
#     `duration_min`, если объявлена, **MUST** быть целым числом минут больше
#     нуля; потребитель **SHOULD** отвергать длительность, превышающую
#     разумный предел (эталонная реализация — 31 сутки), потому что такое
#     значение почти всегда означает секунды или часы, подставленные вместо
#     минут. Если `duration_min` не объявлена, потребитель **MUST** применить
#     своё объявленное значение по умолчанию и **MUST NOT** выводить
#     длительность из `cost.time_s` глагола (§4.3).
#     Отметку времени потребитель **MUST** сохранять в записи такой, какой её
#     объявила сторона, вместе с часовым поясом, если он указан: запись —
#     доказательство, и переписанное в ней время перестаёт им быть.
#     Незнакомые ключи блока потребитель **MUST** сохранять: реализация,
#     вычищающая непонятное, уничтожает объявление следующей версии протокола.
#     Проверка блока **MUST** быть строгой на входе (намерение можно
#     отвергнуть до действия) и **SHOULD** быть терпимой при чтении журнала
#     (отвергать уже записанное поздно, а упавшая карта не показывает и
#     исправных обязательств).
#


class WhenError(ValueError):
    """Блок `when` объявлен, но не описывает исполнимого времени.

    Отдельный класс, а не общий ValueError, потому что это единственная ошибка
    во всём модуле, которую видит ЧЕЛОВЕК, оформляющий обязательство: он обязан
    из текста понять, какое поле поправить, не открывая исходник.
    """


#: Потолок длительности одного обязательства — 31 сутки.
#: Это не политика, а сеть для ошибки в единицах: `duration_min=1800`, где
#: имелись в виду секунды, иначе занял бы на карте тридцать часов и устроил
#: владельцу конфликт на каждом следующем дне.
MAX_DURATION_MIN = 31 * 24 * 60


def _strict_moment(value: Any) -> datetime | None:
    """Разбор отметки времени БЕЗ поиска даты внутри произвольной строки.

    Отличие от `_naive` принципиальное и ради одной защиты: `_naive` умеет
    выуживать «2026-10-12 09:00» из любой фразы, и это правильно для
    человекочитаемого `subject`. Но `when.starts_at` — ПОЛЕ, и если в него
    попала фраза, из которой дату пришлось выковыривать регуляркой, значит
    сторона объявила не время, а текст. Такое надо отвергнуть, пока
    обязательство ещё не взято, а не молча принять с угаданным часом.

    Дата без времени тоже отвергается: «2026-10-12» превратилось бы в полночь,
    то есть в догадку, выданную за объявление.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if ":" not in text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@dataclass(frozen=True)
class When:
    """Объявленное время обязательства — то, что §6.1 требует положить в запись.

    Три поля спецификации плюс `role`: дорожка на карте («семья», «работа»),
    которую `Entry` уже умеет читать и которая не выводится ни из чего другого.

    `starts_at` хранится СТРОКОЙ, а не `datetime`, и это не лень. Запись журнала
    — доказательство: в ней обязано остаться ровно то, что объявила сторона,
    вместе с зоной, если сторона её указала. Приведение к наивному времени —
    дело карты, и оно случается в одном месте проекта (`_naive`).
    """

    starts_at: str
    duration_min: int = DEFAULT_DURATION_MIN
    place: str = ""
    role: str = ""

    @property
    def start(self) -> datetime:
        """Наивное время начала — то же, что увидит карта."""
        moment = _naive(self.starts_at)
        if moment is None:  # pragma: no cover — конструктор это уже проверил
            raise WhenError(f"when.starts_at: не разобрать {self.starts_at!r}")
        return moment

    def to_dict(self) -> dict[str, Any]:
        """JSON-вид для записи `commitment`. Пустые поля не пишутся.

        Пустое `place` в записи выглядело бы как объявление «места нет», тогда
        как на самом деле его просто не передали; отсутствие ключа честнее.
        """
        out: dict[str, Any] = {"starts_at": self.starts_at,
                               "duration_min": int(self.duration_min)}
        if self.place:
            out["place"] = self.place
        if self.role:
            out["role"] = self.role
        return out

    @staticmethod
    def of(value: "When | Mapping[str, Any]") -> "When":
        """Привести объявление к `When`, проверив его. Иначе — `WhenError`."""
        block = normalize_when(value)
        if block is None:
            raise WhenError("when не объявлен")
        return When(
            starts_at=str(block["starts_at"]),
            duration_min=int(block.get("duration_min", DEFAULT_DURATION_MIN)),
            place=str(block.get("place", "")),
            role=str(block.get("role", "")),
        )

    @staticmethod
    def from_slot(
        slot: Mapping[str, Any],
        *,
        place: str = "",
        duration_min: int | None = None,
        role: str = "",
    ) -> "When":
        """Собрать `when` из слота, который отдал сервис (`day` + `time`).

        Это тот самый случай, ради которого §6.1 и писался: заведение УЖЕ знает
        день и час слота и отдаёт их в каталоге. Клиенту остаётся не угадать
        время, а переписать объявленное — и положить его в запись полем.

        Порядок источников внутри слота: `when` (если сервис уже отдаёт блок
        целиком — так и надо) → `starts_at` → `day` + `time`.
        """
        if isinstance(slot.get("when"), Mapping):
            base = When.of(slot["when"])
            return When(
                starts_at=base.starts_at,
                duration_min=int(duration_min or base.duration_min),
                place=place or base.place,
                role=role or base.role,
            )

        starts = slot.get("starts_at")
        if not starts:
            day, time_of_day = slot.get("day"), slot.get("time")
            if not isinstance(day, str) or not isinstance(time_of_day, str):
                raise WhenError(
                    "слот не содержит времени: нужны либо 'when', либо 'starts_at', "
                    f"либо пара 'day'+'time', получено {sorted(slot)}"
                )
            starts = f"{day.strip()}T{time_of_day.strip()}"

        declared = duration_min if duration_min is not None else slot.get("duration_min")
        return When.of({
            "starts_at": starts,
            "duration_min": declared if declared is not None else DEFAULT_DURATION_MIN,
            "place": place or str(slot.get("place") or ""),
            "role": role,
        })


def normalize_when(
    value: "When | Mapping[str, Any] | None",
    *,
    where: str = "when",
) -> dict[str, Any] | None:
    """Проверить блок `when` и вернуть его JSON-вид (или None, если его нет).

    Проверка СТРОГАЯ и бросает `WhenError` с текстом, называющим поле: блок
    попадает в хэш-цепь, а запись в цепи правке не подлежит. Отвергнуть
    кривое объявление можно только до того, как оно записано; потом остаётся
    лишь объяснять, почему гейт видит не тот час.

    Неизвестные ключи СОХРАНЯЮТСЯ как есть. Следующая версия протокола может
    добавить к блоку, например, часовой пояс места, и реализация, вычистившая
    незнакомое, тихо уничтожила бы объявление, которого не понимает.
    """
    if value is None:
        return None
    if isinstance(value, When):
        raw: dict[str, Any] = value.to_dict()
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise WhenError(
            f"{where}: ожидается объект {{starts_at, duration_min, place}} "
            f"или When, получено {type(value).__name__}"
        )

    if raw.get("starts_at") in (None, ""):
        raise WhenError(
            f"{where}.starts_at обязателен: обязательство во времени без времени "
            f"объявить нельзя (получено {sorted(raw) or 'пустой блок'})"
        )
    moment = _strict_moment(raw["starts_at"])
    if moment is None:
        raise WhenError(
            f"{where}.starts_at: {raw['starts_at']!r} — не отметка времени ISO-8601 "
            f"с часами и минутами (например «2026-10-12T09:00» или "
            f"«2026-10-12T09:00:00Z»)"
        )
    # Отметку НЕ переписываем: в записи остаётся объявление стороны вместе с
    # зоной. `datetime` сериализуем сами — иначе запись не попадёт в JSON.
    starts_at = (moment.isoformat(timespec="seconds")
                 if isinstance(raw["starts_at"], datetime) else str(raw["starts_at"]).strip())

    out: dict[str, Any] = {k: v for k, v in raw.items()
                           if k not in ("starts_at", "duration_min", "place", "role")}
    out["starts_at"] = starts_at

    if "duration_min" in raw and raw["duration_min"] is not None:
        minutes = raw["duration_min"]
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
            raise WhenError(
                f"{where}.duration_min: ожидается целое число минут, получено "
                f"{minutes!r} ({type(minutes).__name__}) — длительность, пришедшая "
                f"не числом, означает, что сторона не решила, в чём она измеряется"
            )
        if float(minutes) != int(minutes):
            raise WhenError(f"{where}.duration_min: минуты целые, получено {minutes!r}")
        minutes = int(minutes)
        if minutes <= 0:
            raise WhenError(
                f"{where}.duration_min: {minutes} — обязательство не может занимать "
                f"ноль минут или ехать назад во времени"
            )
        if minutes > MAX_DURATION_MIN:
            raise WhenError(
                f"{where}.duration_min: {minutes} минут — больше 31 суток; "
                f"похоже на секунды или часы, подставленные вместо минут"
            )
        out["duration_min"] = minutes

    for key in ("place", "role"):
        if key in raw and raw[key] is not None:
            if not isinstance(raw[key], str):
                raise WhenError(
                    f"{where}.{key}: ожидается строка, получено "
                    f"{raw[key]!r} ({type(raw[key]).__name__})"
                )
            text = raw[key].strip()
            if text:
                out[key] = text
    return out


def _record_duration(
    when: Mapping[str, Any],
    payload: Mapping[str, Any],
    default: int,
) -> int:
    """Длительность УЖЕ ЗАПИСАННОГО обязательства — мягко, без исключений.

    Сюда приходят записи журнала, в том числе сделанные до этапа 18 и чужими
    реализациями. Непонятное число не повод уронить карту: карта обязана
    нарисоваться и показать то, что разобралось. Поэтому негодное значение
    молча заменяется значением по умолчанию — ровно так же, как если бы
    длительности не было вовсе.
    """
    for candidate in (when.get("duration_min"), payload.get("duration_min")):
        if candidate is None or isinstance(candidate, bool):
            continue
        try:
            minutes = int(candidate)
        except (TypeError, ValueError):
            continue
        if 0 < minutes <= MAX_DURATION_MIN:
            return minutes
    return int(default)


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

    @classmethod
    def from_when(
        cls,
        party: str,
        when: "When | Mapping[str, Any]",
        *,
        subject: str = "",
        service: str = "",
        verb: str = "",
        money: float = 0.0,
        default_place: str = "",
        default_duration_min: int = DEFAULT_DURATION_MIN,
    ) -> "Entry":
        """Кандидат, собранный из ОБЪЯВЛЕННОГО времени (§6.1), а не из догадок.

        Отдельный конструктор нужен затем, чтобы у блока `when` был ровно один
        способ стать отрезком на карте. Пока такого способа не было, каждый
        потребитель читал поля блока сам — и первая же реализация, забывшая про
        `role`, рисовала обязательство на чужой дорожке, не нарушив при этом
        ничего формально.
        """
        block = When.of(when)
        return cls.proposed(
            party=party,
            subject=subject or verb or block.place,
            starts_at=block.start,
            duration_min=block.duration_min or default_duration_min,
            place=block.place or default_place,
            role=block.role,
            service=service,
            verb=verb,
            money=money,
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

            # Порядок источников: объявленное `when` (§6.1) → плоское
            # `starts_at` → разбор `subject`. Третий путь — для записей,
            # сделанных до этапа 18: они останутся в журнале навсегда, и
            # перестать их видеть значило бы врать о прошлом владельца.
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
                duration_min=_record_duration(when, p, default_duration_min),
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
