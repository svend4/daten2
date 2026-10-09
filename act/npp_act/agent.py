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
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

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

    def commit_two_party(
        self,
        service: str,
        verb: str,
        payload: dict[str, Any],
        counterparty: "Agent",
        hold: Hold | None = None,
        subject: str = "",
    ) -> tuple[Decision, Commitment | None]:
        """Шаги 3–4 протокола: согласие обеих сторон, затем запись в оба журнала.

        Возвращает обязательство, только если оно действительно записано у обеих
        сторон. Односторонняя запись обязательством не считается.
        """
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

        mine = self.ledger.append("commitment", body)
        theirs = counterparty.ledger.append("commitment", body)

        return decision, Commitment(
            id=cid,
            parties=parties,
            subject=subject,
            hashes={self.profile: mine.hash, counterparty.profile: theirs.hash},
        )
