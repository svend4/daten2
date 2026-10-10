"""Жёсткий предикат H8: конфликт расписания как основание для отказа (§5.1.8).

ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ

`calendar.py` умеет находить «невозможные фигуры» в расписании: обязательства,
которые по отдельности законны, а вместе требуют быть в двух местах сразу. Но
сам по себе он — ОТЧЁТ ПОСТФАКТУМ. Карта, нарисованная после того, как человек
подписался на невозможное, честна и бесполезна: отменить необратимую бронь она
не поможет.

Здесь контур замыкается. Губернатор уже отказывает, когда не хватает денег
(H3) или когда ключ идемпотентности уже сработал (H6). Не хватало отказа по
той причине, которая в жизни встречается чаще обеих: **в расписании владельца
для этого действия нет места**. Время — такой же исчерпаемый ресурс, как
деньги, только невозвратный: непроданный букет можно продать завтра,
непрожитый вторник — нельзя.

ТЕКСТ ДЛЯ СПЕЦИФИКАЦИИ (§5.1, восьмой жёсткий предикат)

    8. **Конфликт расписания.** `effect` ∈ {`commit`, `money`, `destroy`} и
       предлагаемое обязательство, будучи добавленным к уже взятым, делает
       расписание владельца физически неисполнимым (пересечение по времени,
       недостаточное время на дорогу, превышение дневной ёмкости — §calendar).
       Губернатор **MUST** проверять БУДУЩЕЕ состояние расписания, а не
       текущее: текущее бесконфликтно по построению, потому что каждое прошлое
       обязательство проходило тот же предикат. Конфликт создаёт именно новое
       обязательство, и вменять владельцу прежние неисполнимости губернатор
       **MUST NOT**.
       Время предлагаемого обязательства предикат **MUST** брать из блока
       `when` намерения (§6.1), если он объявлен, и **MUST NOT** при этом
       обращаться к другим источникам — ни к плоским полям намерения, ни к
       разбору человекочитаемой строки. Объявленный и негодный блок **MUST**
       приводить к отказу с объяснением, а не к переходу к следующему
       источнику: подмена испорченного объявления догадкой означает, что гейт
       проверил время, которого сторона не объявляла.
       Если блок `when` не объявлен, реализация **MAY** выводить время из
       прочих полей намерения (плоские `starts_at`, `day`+`time`, вложенный
       слот, разбор строки) — это деградация для записей и намерений,
       созданных до введения §6.1.
       Если время обязательства из намерения не выводится, предикат **MUST**
       воздержаться (считаться пройденным), а не достраивать время по
       умолчанию.
       При `block` губернатор **SHOULD** предложить ближайшее время, в которое
       расписание владельца свободно (§5.3), если оно выводимо в объявленном
       горизонте поиска.

ПОЧЕМУ МОЛЧАНИЕ БЕЗОПАСНЕЕ ДОГАДКИ

Предикат, который при отсутствии времени в намерении подставлял бы «сегодня»,
«полдень» или «сейчас», блокировал бы действия по времени, которое никто не
объявлял. Это хуже, чем пропустить конфликт, по трём причинам.

1. Отказ по выдуманному основанию неопровержим. Владелец не может показать,
   что время другое, — его нигде нет. Предъявить такое решение нельзя, а §5
   стоит на том, что каждое решение губернатора предъявляемо.
2. Ошибка второго рода (пропустили конфликт) чинится следующим шагом: карта
   §calendar покажет неисполнимость, и владелец отменит одно из обязательств.
   Ошибка первого рода (запретили исполнимое) не чинится ничем, кроме
   отключения предиката — а отключённый гейт не защищает уже ни от чего.
3. Выдуманное время портит сам журнал: решение `block` с временем, которого не
   было в намерении, выглядит в хэш-цепи как доказательство того, чего не
   происходило.

Поэтому `check()` на намерении без распознаваемого времени возвращает пустой
список, а не «на всякий случай» конфликт. Молчание предиката — это заявление
«данных нет», и оно честное; догадка была бы заявлением «я знаю», и оно ложное.

ОТКУДА БЕРЁТСЯ ГИПОТЕТИЧЕСКАЯ ЗАПИСЬ

Из намерения (`payload`) и из манифеста — ровно в этом порядке, потому что
манифест описывает ПОСЛЕДСТВИЕ глагола, а не обстоятельства конкретной сделки.

ПОРЯДОК ИСТОЧНИКОВ ВРЕМЕНИ (после этапа 18, нормативно для этой реализации):

    0. `payload["when"]` — ОБЪЯВЛЕННОЕ время (§6.1). Авторитетный источник:
       если блок есть, остальные четыре НЕ рассматриваются вовсе, даже когда
       они нашли бы время. Блок, объявленный и негодный, приводит к `WhenError`,
       а не к тихому переходу к следующему источнику.
    1. `payload["starts_at"]` — плоское поле намерения.
    2. `payload["day"]` + `payload["time"]` — в таком виде заведение отдаёт
       слот, и клиент часто переписывает их в намерение как есть.
    3. `payload["slot"]` — вложенный слот целиком.
    4. Разбор человекочитаемой строки (`subject`/`note`/`title`/…) — ДЕГРАДАЦИЯ.

    длительность `when.duration_min` → `payload["duration_min"]` → `duration_of`
                 из настроек владельца → `default_duration_min`
    место        `when.place` → `payload["place"]` → `place_of` по сервису →
                 `manifest.title` → сервис
    подпись      `payload["subject"]` → `cap.title`

ПОЧЕМУ ПОРЯДОК ИМЕННО ТАКОЙ, А НЕ «ЧТО НАЙДЁТСЯ»

До этапа 18 блок `when` никто не писал, и главным путём был пункт 4 — разбор
даты из фразы «приём 2026-10-12 09:00». Этот путь работает, но зависит от
ФОРМУЛИРОВКИ: стоит агенту написать «приём 12 октября в 9 утра», и предикат
перестаёт видеть время. Не ошибается — ПЕРЕСТАЁТ ВИДЕТЬ, то есть воздерживается
и пропускает конфликт молча, с зелёным решением в журнале. Молчание предиката
безопасно, когда времени действительно нет (см. ниже), и опасно, когда время
есть, а источник оказался хрупким: отказ не выдуман, но и защиты нет.

Поэтому пункт 0 добавлен не «ещё одним источником», а ГЛАВНЫМ, и остальные
пункты понижены до запасных. Отсюда же правило «если `when` есть, остальные не
смотрим»: деградация при наличии объявления означала бы, что битое поле
подменяется догадкой из строки, и гейт считает час, которого сторона не
объявляла. Лучше громкая `WhenError` до действия, чем тихое расхождение между
тем, на что сторона подписалась, и тем, что проверил гейт.

Асимметрия с `calendar.build_timeline` намеренна: карта читает УЖЕ ЗАПИСАННОЕ и
на непонятном `when` откатывается к `subject`, потому что отвергать прошлое
поздно, а здесь проверяется НАМЕРЕНИЕ, и отказ до действия ещё ничего не стоит.

Длительность НЕ берётся из манифеста намеренно, и это стоит записать как
замечание к §4.3: единственное временно́е поле глагола — `cost.time_s` — это
длительность HTTP-ВЫЗОВА (у `booking.create` она 0.3 с), а не длительность
обязательства, которое этот вызов создаёт. Принять одно за другое значило бы
считать, что приём у врача длится треть секунды.

Модуль НЕ меняет `calendar.py`: вся арифметика неисполнимости остаётся там,
здесь только превращение намерения в кандидата и вызов `would_conflict`. Так
проверяемо, что предикат и карта отвечают одно и то же: отказ губернатора
можно перепроверить той же картой, что рисуется человеку.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from .calendar import (
    DEFAULT_CAPACITY_HOURS,
    DEFAULT_DURATION_MIN,
    Conflict,
    Entry,
    TravelMatrix,
    # `_naive` берётся именно отсюда, несмотря на подчёркивание: это
    # ЕДИНСТВЕННОЕ место, где в проекте теряется часовой пояс. Свой разбор
    # времени здесь означал бы два парсера, которые однажды разойдутся, — и
    # тогда предикат и карта начнут говорить о разных часах.
    _naive,
    build_timeline,
    explain,
    # Строгая проверка объявленного `when` (§6.1) живёт в `calendar` вместе с
    # разбором времени: два валидатора однажды разойдутся, и тогда гейт и карта
    # начнут считать исполнимым разное.
    normalize_when,
    would_conflict,
)
from .ledger import Ledger
from .manifest import Manifest

#: Шаг перебора при поиске ближайшего свободного времени (§5.3).
#: Четверть часа — компромисс: мельче даёт предложения вида «14:07», которые
#: ни одно заведение не продаёт, крупнее — пропускает реально свободный час.
DEFAULT_SEARCH_STEP_MIN = 15

#: Горизонт поиска альтернативы. Двое суток: за их пределами «ближайшее время»
#: перестаёт быть ответом на вопрос владельца и становится другим планом.
DEFAULT_SEARCH_HORIZON_H = 48

#: Поля намерения, в которых агент уже сегодня пишет время по-человечески.
#: Порядок важен: `subject` — предмет сделки (§7), остальные менее надёжны.
_TEXT_FIELDS = ("subject", "note", "title", "description", "label")


def _join_day_time(day: Any, time_of_day: Any) -> datetime | None:
    """Склеить «2026-10-12» и «09:00» в наивное время начала.

    Именно в таком виде заведение отдаёт свободный слот (`slot.list` → `day`,
    `time`), поэтому агенту не нужно ничего переформатировать, чтобы предикат
    увидел время. Одного `day` без `time` НЕ достаточно: полночь была бы
    догадкой, а догадка здесь запрещена.
    """
    if not isinstance(day, str) or not isinstance(time_of_day, str):
        return None
    day, time_of_day = day.strip(), time_of_day.strip()
    if not day or not time_of_day:
        return None
    return _naive(f"{day} {time_of_day}")


class ScheduleGuard:
    """Предикат H8: отвечает, появится ли неисполнимость, ЕСЛИ действие состоится.

    Живёт рядом с губернатором одной стороны и смотрит в её собственный журнал:
    конфликты считаются ВНУТРИ стороны (§calendar.build_timeline). Приём Анны
    не мешает приёму Бориса, и губернатор Анны не вправе отказывать из-за
    чужого расписания.

    >>> guard = ScheduleGuard(led, capacity_hours=10.0)          # doctest: +SKIP
    >>> gov = Governor(registry, led, Budget(500), schedule_guard=guard)
    """

    def __init__(
        self,
        ledgers: "Ledger | Mapping[str, Ledger]",
        party: str | None = None,
        *,
        travel: "TravelMatrix | Mapping | None" = None,
        capacity_hours: float = DEFAULT_CAPACITY_HOURS,
        place_of: Mapping[str, str] | None = None,
        role_of: Mapping[str, str] | None = None,
        duration_of: Mapping[str, int] | None = None,
        default_duration_min: int = DEFAULT_DURATION_MIN,
        search_step_min: int = DEFAULT_SEARCH_STEP_MIN,
        search_horizon_h: float = DEFAULT_SEARCH_HORIZON_H,
        verify: bool = True,
    ):
        if isinstance(ledgers, Ledger):
            self.ledgers: dict[str, Ledger] = {party or ledgers.owner: ledgers}
            self.party = party or ledgers.owner
        else:
            self.ledgers = dict(ledgers)
            if party is None:
                if len(self.ledgers) != 1:
                    raise ValueError(
                        "при нескольких журналах нужно явно указать party: "
                        "кандидат обязан принадлежать одной стороне"
                    )
                party = next(iter(self.ledgers))
            self.party = party

        self.travel = TravelMatrix.of(travel)
        self.capacity_hours = float(capacity_hours)
        self.place_of = dict(place_of or {})
        self.role_of = dict(role_of or {})
        self.duration_of = dict(duration_of or {})
        self.default_duration_min = int(default_duration_min)
        self.search_step_min = max(1, int(search_step_min))
        self.search_horizon_h = float(search_horizon_h)
        self.verify = verify

    # ---------- уже взятое ----------

    def timeline(self) -> list[Entry]:
        """Развернуть журналы стороны в линию времени — КАЖДЫЙ раз заново.

        Кэша здесь нет сознательно: журнал дописывается тем же исполнителем,
        который спрашивает губернатора, и устаревшая карта допустила бы второе
        обязательство на тот час, который заняло первое, — ровно ту ошибку,
        ради которой предикат написан.
        """
        return build_timeline(
            self.ledgers,
            place_of=self.place_of,
            role_of=self.role_of,
            default_duration_min=self.default_duration_min,
            verify=self.verify,
        )

    # ---------- намерение → гипотетическое обязательство ----------

    def _declared(self, service: str, verb_id: str,
                  payload: Mapping[str, Any]) -> dict[str, Any] | None:
        """Объявленный блок `when` из намерения — проверенный, или None.

        Проверка строгая (`normalize_when` бросает `WhenError`): здесь ещё
        НАМЕРЕНИЕ, и отказ до действия ничего не стоит. См. шапку модуля о том,
        почему деградация к разбору строки при наличии объявления хуже отказа.
        """
        raw = payload.get("when")
        if raw is None:
            return None
        return normalize_when(raw, where=f"{service}:{verb_id} when")

    def _duration(self, service: str, verb_id: str, payload: Mapping[str, Any]) -> int:
        """Длительность, когда её НЕ объявили: намерение → настройки владельца.

        Объявленная длительность сюда не попадает: блок `when` проверен и
        подставляется прямо в кандидата. Этот метод отвечает на другой вопрос —
        сколько времени занять, если сторона объявила час начала, но не сказала,
        на сколько. Настройки владельца («приём в этой клинике — 30 минут») тут
        законный источник: это его собственное объявление, а не догадка гейта.
        """
        flat = payload.get("duration_min")
        if flat is not None:
            return int(flat)
        for key in (f"{service}:{verb_id}", verb_id, service):
            if key in self.duration_of:
                return int(self.duration_of[key])
        return self.default_duration_min

    def _starts_at(self, payload: Mapping[str, Any]) -> datetime | None:
        """Время начала из ЗАПАСНЫХ источников намерения — или None.

        Пункт 0 (объявленный `when`) здесь не рассматривается: если блок есть,
        вызывающий сюда не приходит. Ниже — четыре запасных пути, от явного к
        слабому. Ни один из них не достраивает отсутствующее: последний (разбор
        строки) опирается на то, что агент уже кладёт дату и час в предмет
        сделки, а не на то, что они «наверное, такие».
        """
        start = _naive(payload.get("starts_at"))
        if start is not None:
            return start

        start = _join_day_time(payload.get("day"), payload.get("time"))
        if start is not None:
            return start

        slot = payload.get("slot")
        if isinstance(slot, Mapping):
            start = (_naive(slot.get("starts_at"))
                     or _join_day_time(slot.get("day"), slot.get("time")))
            if start is not None:
                return start

        for field in _TEXT_FIELDS:
            text = payload.get(field)
            if isinstance(text, str) and text.strip():
                start = _naive(text)
                if start is not None:
                    return start
        return None

    def proposed(
        self,
        service: str,
        verb_id: str,
        payload: Mapping[str, Any] | None = None,
        manifest: Manifest | None = None,
    ) -> Entry | None:
        """Гипотетическая запись: такого обязательства ещё нет и может не быть.

        Возвращает None, если время не выводится. Это не ошибка и не сбой — это
        отказ предиката высказываться (см. шапку модуля). Бросает `WhenError`,
        если блок `when` объявлен и негоден: тут разница между «данных нет» и
        «данные испорчены», и вести себя одинаково в этих двух случаях нельзя.
        """
        payload = dict(payload or {})
        cap = manifest.verb(verb_id) if manifest is not None else None

        # Место и подпись считаются одинаково для обоих путей: объявленный блок
        # вправе не нести `place` (заведение и так известно по сервису), и тогда
        # подставляется та же цепочка запасных значений, что и без блока.
        place = str(
            payload.get("place") or self.place_of.get(service)
            # Название сервиса из манифеста — это и есть место в человеческом
            # смысле («Клиника «Норд»»), поэтому оно идёт раньше, чем
            # технический идентификатор сервиса.
            or (manifest.title if manifest is not None else "") or service or "—"
        )
        subject = str(
            payload.get("subject") or (cap.title if cap is not None else "") or verb_id
        )
        role = str(payload.get("role") or self.role_of.get(service) or "")

        # Пункт 0: объявленное время. Один конструктор (`Entry.from_when`) на
        # весь проект — иначе каждый потребитель читал бы поля блока сам, и
        # первый же, забывший про `role`, поставил бы отрезок на чужую дорожку.
        declared = self._declared(service, verb_id, payload)
        if declared is not None:
            block = dict(declared)
            block.setdefault("duration_min", self._duration(service, verb_id, payload))
            block.setdefault("role", role)
            return Entry.from_when(
                party=self.party, when=block, subject=subject,
                service=service, verb=verb_id, default_place=place,
            )

        start = self._starts_at(payload)
        if start is None:
            return None

        return Entry.proposed(
            party=self.party,
            subject=subject,
            starts_at=start,
            duration_min=self._duration(service, verb_id, payload),
            place=place,
            role=role,
            service=service,
            verb=verb_id,
        )

    # ---------- собственно предикат ----------

    def check(
        self,
        service: str,
        verb_id: str,
        payload: Mapping[str, Any] | None = None,
        manifest: Manifest | None = None,
    ) -> list[Conflict]:
        """Что сломается в расписании, если допустить это действие.

        Пустой список — «место есть» ИЛИ «время не объявлено»; губернатор в обоих
        случаях обязан вести себя одинаково, потому что оснований для отказа у
        него нет. Непустой — перечень неисполнимостей, каждая с объяснением и
        ссылками на строки журнала.
        """
        candidate = self.proposed(service, verb_id, payload, manifest)
        if candidate is None:
            return []
        return self.would_conflict(candidate)

    def would_conflict(self, candidate: Entry) -> list[Conflict]:
        """Проверка кандидата против БУДУЩЕГО состояния расписания.

        Вся арифметика — в `calendar.would_conflict`, включая вычитание тех
        неисполнимостей, которые существовали и без нового обязательства.
        Дублировать её здесь нельзя: тогда отказ губернатора и карта человека
        могли бы разойтись, и доверять нельзя было бы ни одному из них.
        """
        return would_conflict(
            self.timeline(), candidate,
            travel=self.travel, capacity_hours=self.capacity_hours,
        )

    def reason(self, conflicts: Sequence[Conflict]) -> str:
        """Причина отказа словами — из `calendar.explain`, а не своими.

        Объяснение обязано быть тем же текстом, который человек увидит на карте:
        два разных описания одного конфликта превращают журнал в пересказ.
        """
        if not conflicts:
            return "конфликт расписания не обнаружен"
        return ("конфликт расписания: обязательство физически неисполнимо — "
                + "; ".join(explain(c) for c in conflicts))

    # ---------- безопасная альтернатива (§5.3) ----------

    def nearest_free(
        self,
        service: str,
        verb_id: str,
        payload: Mapping[str, Any] | None = None,
        manifest: Manifest | None = None,
    ) -> datetime | None:
        """Ближайшее время, в которое расписание владельца свободно.

        Перебор вперёд от запрошенного времени с шагом `search_step_min` до
        горизонта. Назад не ищем: предложить время, которое уже прошло или
        которое ближе, чем просил владелец, — не помощь, а подмена намерения.

        Если в горизонте свободного времени нет, возвращается None. Это тот же
        принцип, что и в самом предикате: лучше не предложить ничего, чем
        предложить время, про которое ничего не известно.
        """
        candidate = self.proposed(service, verb_id, payload, manifest)
        if candidate is None:
            return None

        timeline = self.timeline()
        step = timedelta(minutes=self.search_step_min)
        limit = candidate.starts_at + timedelta(hours=self.search_horizon_h)

        moment = candidate.starts_at + step
        while moment <= limit:
            shifted = Entry.proposed(
                party=candidate.party, subject=candidate.subject, starts_at=moment,
                duration_min=candidate.duration_min, place=candidate.place,
                role=candidate.role, service=candidate.service, verb=candidate.verb,
            )
            if not would_conflict(timeline, shifted, travel=self.travel,
                                  capacity_hours=self.capacity_hours):
                return moment
            moment += step
        return None

    def alternative(
        self,
        service: str,
        verb_id: str,
        payload: Mapping[str, Any] | None = None,
        manifest: Manifest | None = None,
        conflicts: Sequence[Conflict] = (),
    ) -> dict[str, Any] | None:
        """Альтернатива для `Decision.alternative` — или None, если её нет.

        Оговорка в тексте не формальность: предикат знает расписание ВЛАДЕЛЬЦА и
        ничего не знает о часах работы заведения. Поэтому предложение звучит как
        «в расписании свободно», а не «запишитесь на это время»: свободен
        владелец, а продаёт время всё равно другая сторона.
        """
        free = self.nearest_free(service, verb_id, payload, manifest)
        if free is None:
            return None
        return {
            "verb": verb_id,
            "service": service,
            "starts_at": free.isoformat(timespec="minutes"),
            "note": (f"в расписании свободно с {free:%Y-%m-%d %H:%M} — "
                     f"предложить этот час второй стороне"),
        }
