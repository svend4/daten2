"""Агент профиля и протокол двустороннего обязательства (SPEC-NPP-ACT.md §7).

Это то, ради чего расширение существует: действие, в котором участвуют два
независимых профиля, и оба несут ответственность, которую можно предъявить.

Протокол из четырёх шагов, где первые два обратимы:

    offer   — инициатор объявляет намерение
    hold    — принимающая сторона удерживает ресурс на срок
    accept  — обе стороны подтверждают
    commit  — обязательство фиксируется в ОБОИХ журналах с общим идентификатором

Если accept не наступил до истечения удержания, инициатор обязан вызвать
обратный глагол: ресурс не должен залипать из-за несостоявшейся сделки.

ВРЕМЯ ОБЯЗАТЕЛЬСТВА В ЗАПИСИ (§6.1, этап 18)

ТЕКСТ ДЛЯ СПЕЦИФИКАЦИИ (§7, дополнение к описанию шага `commit`)

    Инициатор шага `commit`, если обязательство относится к событию во
    времени, **MUST** передать блок `when` (§6.1) и **MUST** записать его
    побайтово одинаковым в записи `commitment` ОБЕИХ сторон. Расхождение
    блоков `when` у сторон одного обязательства означает, что стороны
    подписались на разное время, и обязательством такая пара записей не
    является.
    Блок `when` **MUST** быть проверен ДО шага 3 (`accept`): отметка времени
    разбирается как ISO-8601 с часами и минутами, `duration_min` — целое число
    минут больше нуля. Негодный блок **MUST** приводить к отказу раньше, чем
    выдано хотя бы одно согласие, потому что запись в хэш-цепи правке уже не
    подлежит, а согласие, выданное на невнятное время, отозвать нечем.
    Реализация **MUST NOT** достраивать `when` из своих представлений о
    длительности или месте: блок, который никто не объявлял, в журнале
    выглядит как доказательство того, чего не происходило (ср. §5.1.8).
    Реализация **SHOULD** собирать `when` из ответа сервиса: заведение уже
    знает день и час слота, и переписать объявленное надёжнее, чем угадать.

ПОЧЕМУ БЛОК ПИШЕТСЯ ОДИН И ТОТ ЖЕ ОБЕИМ СТОРОНАМ

Тело записи `body` формируется однажды и кладётся в оба журнала без изменений.
Это и даёт смысл сверке: хэши записей сторон вычисляются от одного и того же
канонического JSON, поэтому совпадение `when` у двух сторон проверяется не
доверием, а арифметикой. Если бы каждая сторона собирала свой блок, у клиники
и клиента могли бы законно разойтись часы — и предъявить было бы нечего.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .calendar import When, WhenError, normalize_when
from .executor import Executor, Result
from .governor import Decision
from .ledger import Ledger


def new_key(prefix: str = "idem") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def commitment_id(parties: list[str], subject: str) -> str:
    """Детерминированный публичный идентификатор обязательства."""
    seed = "|".join(sorted(parties)) + "|" + subject
    return "cmt_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


@dataclass
class Hold:
    """Обратимое удержание ресурса."""

    service: str
    verb: str
    hold_id: str
    expires_at: str
    reverse_verb: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        deadline = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return deadline <= datetime.now(timezone.utc)

    def as_gate_input(self) -> dict[str, Any]:
        return {"expires_at": self.expires_at, "verb": self.verb, "hold_id": self.hold_id}


@dataclass
class Commitment:
    """Зафиксированное двустороннее обязательство."""

    id: str
    parties: list[str]
    subject: str
    hashes: dict[str, str]
    #: Объявленное время обязательства (§6.1) или None, если обязательство
    #: не относится к событию во времени. Хранится ровно тем словарём, который
    #: ушёл в записи обеих сторон, — чтобы вызывающий сверял не свои ожидания,
    #: а то, что действительно записано.
    when: dict[str, Any] | None = None

    def verified_by(self, ledgers: dict[str, Ledger]) -> bool:
        """Обе стороны записали одно и то же — и обе цепи целы."""
        for party, expected in self.hashes.items():
            led = ledgers.get(party)
            if led is None:
                return False
            led.verify()
            if not any(r.hash == expected for r in led):
                return False
        return True

    def records_in(self, ledgers: dict[str, Ledger]) -> dict[str, Any]:
        """Записи сторон по их хэшам: {сторона: Record}. Пропущенные — отсутствуют."""
        found: dict[str, Any] = {}
        for party, expected in self.hashes.items():
            led = ledgers.get(party)
            if led is None:
                continue
            for rec in led:
                if rec.hash == expected:
                    found[party] = rec
                    break
        return found

    def when_agrees(self, ledgers: dict[str, Ledger]) -> bool:
        """Объявленное время одинаково у ВСЕХ сторон — проверено по журналам.

        Отдельный метод, а не следствие `verified_by`: хэш записи считается от
        `{seq, ts, kind, payload, prev}`, и у двух сторон он разный даже при
        одинаковом payload — порядковые номера и предыдущие хэши у них свои.
        Значит из совпадения хэшей с ожидаемыми равенство блоков `when` НЕ
        вытекает, и проверяющему приходится открыть обе записи и сравнить.
        """
        records = self.records_in(ledgers)
        if len(records) != len(self.hashes):
            return False
        blocks = [rec.payload.get("when") for rec in records.values()]
        return all(block == blocks[0] for block in blocks)


class Agent:
    """Агент одного профиля: действует от его имени под гейтом губернатора."""

    def __init__(self, profile: str, executor: Executor):
        self.profile = profile
        self.executor = executor
        self.ledger = executor.ledger
        self.governor = executor.governor

    # ---------- простые действия ----------

    def read(self, service: str, verb: str, payload: dict[str, Any] | None = None) -> Result | None:
        _, res = self.executor.perform(service, verb, payload)
        return res

    def act(
        self,
        service: str,
        verb: str,
        payload: dict[str, Any] | None = None,
        key: str | None = None,
        hold: Hold | None = None,
    ) -> tuple[Decision, Result | None]:
        return self.executor.perform(
            service, verb, payload,
            idempotency_key=key,
            hold=hold.as_gate_input() if hold else None,
        )

    # ---------- шаг 2: удержание ----------

    def hold(self, service: str, verb: str, payload: dict[str, Any]) -> tuple[Decision, Hold | None]:
        """Взять обратимое удержание. Обязателен эффект `reserve` с объявленным сроком."""
        manifest = self.executor.registry.manifest(service)
        cap = manifest.verb(verb) if manifest else None
        if cap is None or cap.effect != "reserve":
            decision, _ = self.executor.perform(service, verb, payload)
            return decision, None

        decision, result = self.executor.perform(service, verb, payload, idempotency_key=new_key("hold"))
        if not decision.admitted or result is None or not result.ok:
            return decision, None

        body = result.body or {}
        expires = body.get("expires_at") or (
            datetime.now(timezone.utc) + timedelta(seconds=cap.expires_s or 60)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

        return decision, Hold(
            service=service,
            verb=verb,
            hold_id=str(body.get("hold_id") or body.get("id") or ""),
            expires_at=expires,
            reverse_verb=cap.reverse or "",
            payload=payload,
        )

    def release(self, hold: Hold) -> tuple[Decision, Result | None]:
        """Отпустить удержание — обязательный шаг при несостоявшейся сделке."""
        return self.executor.perform(
            hold.service, hold.reverse_verb, {"hold_id": hold.hold_id},
            idempotency_key=new_key("rel"),
        )

    # ---------- шаги 3-4: согласие и фиксация ----------

    def accept(self, service: str, verb: str, key: str) -> None:
        """Зафиксировать согласие этой стороны на конкретное действие."""
        self.governor.confirm(f"{service}:{verb}:{key}")

    # ---------- время обязательства (§6.1) ----------

    def when_from_response(
        self,
        service: str,
        *sources: Mapping[str, Any] | None,
        duration_min: int | None = None,
        place: str = "",
        role: str = "",
    ) -> When:
        """Собрать `when` из того, что сказал СЕРВИС, а не из ожиданий клиента.

        Источники просматриваются в переданном порядке, и первый, из которого
        время собирается, выигрывает. Передавать их следует от самого позднего
        к самому раннему: ответ брони, потом ответ удержания, потом слот из
        каталога. Логика в том, что поздний ответ знает о сделке больше: если
        заведение передвинуло слот между чтением каталога и подтверждением,
        правду скажет именно он.

        Место по умолчанию берётся из `title` манифеста («Клиника «Норд»»), а не
        из идентификатора сервиса: на карте обязательств это место читает
        человек, и `venue-clinic-nord` ему ничего не говорит.

        Бросает `WhenError`, если времени нет ни в одном источнике. Это
        сознательно: молча вернуть `None` значило бы оформить обязательство без
        `when` там, где клиент его затребовал, и вернуть предикат H8 к разбору
        строк, думая, что всё в порядке.
        """
        manifest = self.executor.registry.manifest(service)
        fallback_place = place or (manifest.title if manifest is not None else "") or service

        problems: list[str] = []
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            try:
                return When.from_slot(source, place=fallback_place,
                                      duration_min=duration_min, role=role)
            except WhenError as e:
                problems.append(str(e))
        raise WhenError(
            f"{service}: ни один из {len(sources)} источников не содержит времени "
            f"обязательства — {'; '.join(problems) or 'источники пусты'}"
        )

    def commit_two_party(
        self,
        service: str,
        verb: str,
        payload: dict[str, Any],
        counterparty: "Agent",
        hold: Hold | None = None,
        subject: str = "",
        when: "When | Mapping[str, Any] | None" = None,
    ) -> tuple[Decision, Commitment | None]:
        """Шаги 3–4 протокола: согласие обеих сторон, затем запись в оба журнала.

        Возвращает обязательство, только если оно действительно записано у обеих
        сторон. Односторонняя запись обязательством не считается.

        `when` (§6.1) необязателен, и обратная совместимость здесь не вежливость,
        а требование: обязательства бывают и вне времени (списание, подписка,
        передача права), и заставлять их объявлять час значило бы заставлять
        выдумывать. Без `when` тело записи СОВПАДАЕТ побайтово с тем, что писали
        до этапа 18, — ключ не добавляется даже пустым, потому что `{"when": {}}`
        в хэш-цепи выглядит как объявление «времени нет», а не как «не
        объявляли».

        Проверка `when` идёт ПЕРВОЙ строкой, до выдачи согласий и до любого
        HTTP-вызова: см. абзац для §7 в шапке модуля.

        Блок принимается двумя путями — параметром `when` и полем `payload`
        (манифест заведения объявляет `when` во входе `booking.create`), — и
        проверенный блок ВОЗВРАЩАЕТСЯ В НАМЕРЕНИЕ. Это главный инвариант этапа:
        предикат H8 читает `payload["when"]`, и если бы параметр обходил
        намерение, гейт проверял бы одно время, а в журнал ложилось бы другое —
        расхождение, которое ничем не обнаруживается, потому что обе записи по
        отдельности выглядят правильными.
        """
        payload = dict(payload or {})
        from_payload = payload.get("when")
        when_block = normalize_when(
            when if when is not None else from_payload, where=f"{service}:{verb} when")
        if when is not None and from_payload is not None:
            other = normalize_when(from_payload, where=f"{service}:{verb} payload.when")
            if other != when_block:
                raise WhenError(
                    f"{service}:{verb}: время объявлено дважды и по-разному — "
                    f"параметром {when_block} и в намерении {other}; "
                    f"какое из них станет обязательством, решать не реализации"
                )
        if when_block is not None:
            payload = {**payload, "when": when_block}

        key = new_key("cmt")

        # Шаг 3 — согласие обеих сторон на ровно это действие с ровно этим ключом.
        self.accept(service, verb, key)
        counterparty.accept(service, verb, key)

        # Шаг 4 — исполнение под гейтом.
        decision, result = self.act(service, verb, payload, key=key, hold=hold)
        if not decision.admitted or result is None or not result.ok:
            # Сделка не состоялась: удержание обязано быть отпущено.
            if hold is not None:
                self.release(hold)
            return decision, None

        parties = [self.profile, counterparty.profile]
        cid = commitment_id(parties, subject or f"{service}:{verb}:{key}")

        body = {"commitment_id": cid, "parties": parties, "subject": subject,
                "service": service, "verb": verb}
        if when_block is not None:
            body["when"] = when_block

        # Один и тот же объект `body` — в оба журнала. Копий не делаем намеренно:
        # две копии однажды разойдутся на одно поле, и обязательство перестанет
        # быть обязательством, не перестав выглядеть им.
        mine = self.ledger.append("commitment", body)
        theirs = counterparty.ledger.append("commitment", body)

        return decision, Commitment(
            id=cid,
            parties=parties,
            subject=subject,
            hashes={self.profile: mine.hash, counterparty.profile: theirs.hash},
            when=when_block,
        )
