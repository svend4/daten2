"""Губернатор: допуск действия до его исполнения (SPEC-NPP-ACT.md §5).

Идея взята из twin-governor в daten2 (гейт действий через прогон на двойнике),
но обобщена с магазина на любой Actionable-сервис и дополнена тем, чего там
не хватало: бюджетом, идемпотентностью и сроком жизни удержаний.

Принцип: исполнитель не вызывает ничего тяжелее чтения, не получив `admit`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .ledger import Ledger
from .manifest import Capability, Manifest

ADMIT, BLOCK, ESCALATE = "admit", "block", "escalate"


@dataclass
class Budget:
    """Бюджет профиля. Деньги списываются только по факту исполнения."""

    limit: float
    currency: str = "EUR"
    spent: float = 0.0

    @property
    def remaining(self) -> float:
        return round(self.limit - self.spent, 2)

    def charge(self, amount: float) -> None:
        self.spent = round(self.spent + amount, 2)


@dataclass
class Decision:
    verdict: str
    reason: str
    verb: str
    service: str
    alternative: dict[str, Any] | None = None
    checks: list[str] = field(default_factory=list)

    @property
    def admitted(self) -> bool:
        return self.verdict == ADMIT

    def __str__(self) -> str:
        mark = {"admit": "✓", "block": "✗", "escalate": "?"}[self.verdict]
        return f"{mark} {self.verdict.upper()} {self.service}:{self.verb} — {self.reason}"


class Governor:
    """Решает, допустимо ли действие. Не исполняет его."""

    def __init__(
        self,
        registry,
        ledger: Ledger,
        budget: Budget,
        escalate_fraction: float = 0.5,
        confirmations: set[str] | None = None,
        schedule_guard=None,
    ):
        self.registry = registry
        self.ledger = ledger
        self.budget = budget
        self.escalate_fraction = escalate_fraction
        #: ключи уже полученных подтверждений человека/второй стороны
        self.confirmations: set[str] = confirmations or set()
        #: Предикат H8 (schedule_guard.ScheduleGuard) — необязателен намеренно.
        #: Губернатор без него обязан вести себя ровно как прежде: время
        #: обязательства знает не протокол, а владелец расписания, и навязывать
        #: проверку тому, кто расписания не объявил, означало бы отказывать по
        #: основанию, которого он не заявлял.
        #: Тип не объявлен и класс не импортируется сознательно: иначе гейт
        #: потянул бы за собой карту времени при каждом импорте. Губернатору
        #: достаточно трёх методов — check / reason / alternative.
        self.schedule_guard = schedule_guard

    # ---------- вспомогательное ----------

    def confirm(self, key: str) -> None:
        """Зафиксировать полученное подтверждение (от человека или второй стороны)."""
        self.confirmations.add(key)

    @staticmethod
    def _when_defect(service: str, verb_id: str, raw: Any) -> str | None:
        """Причина, почему объявленный `when` негоден, или None, если он годен.

        Валидатор берётся тот же, что у карты обязательств и предиката H8
        (`calendar.normalize_when`): два валидатора однажды разойдутся, и гейт
        пропустит то, что карта не сможет нарисовать, или наоборот.

        Импорт ленивый, а не в шапке: шапка модуля сознательно не тянет карту
        времени при каждом импорте гейта. Вызов идёт только тогда, когда `when`
        объявлен.

        `ValueError` ловится наряду с `WhenError`: `WhenError` — подкласс
        `ValueError`, но `normalize_when` на `duration_min: NaN` (его принимает
        `json.loads` шлюза) может бросить голый `ValueError` из `int(nan)`.
        Такое значение должно стать отказом, а не ответом 500.
        """
        from .calendar import normalize_when

        try:
            normalize_when(raw, where=f"{service}:{verb_id} when")
        except (ValueError, OverflowError, TypeError) as e:
            return f"негодное время обязательства (§6.1): {e}"
        return None

    def _estimate(self, cap: Capability, payload: dict[str, Any]) -> float | None:
        """Во сколько обойдётся глагол: объявленная цена либо потолок из входа."""
        declared = cap.declared_money()
        if declared is not None:
            return declared
        cap_limit = payload.get("max_money")
        return float(cap_limit) if cap_limit is not None else None

    # ---------- главный вход ----------

    def evaluate(
        self,
        service: str,
        verb_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        hold: dict[str, Any] | None = None,
    ) -> Decision:
        """Решение о допуске. Негодные ДАННЫЕ намерения — это решение `block`.

        Негодное объявление времени (§6.1) возвращается как `block` с причиной,
        называющей поле, а не исключением: отказ должен попасть в журнал, и
        исполнитель записывает его как `decision`. Исключение здесь означало бы
        intent без решения в цепи.

        Ошибкой программиста считается другое: `Agent.commit_two_party` бросает
        `WhenError` ДО HTTP и до согласий, когда клиент сам передал негодный блок.
        Такой вызов не был намерением, которое стоит журналировать как отказ,
        и его видит сам клиент, а не аудит.
        """
        payload = payload or {}
        checks: list[str] = []

        def block(reason: str, alt: dict[str, Any] | None = None) -> Decision:
            return Decision(BLOCK, reason, verb_id, service, alt, checks)

        def escalate(reason: str) -> Decision:
            return Decision(ESCALATE, reason, verb_id, service, None, checks)

        # --- H1: сервис известен ---
        manifest: Manifest | None = self.registry.manifest(service)
        if manifest is None:
            return block(f"сервис '{service}' отсутствует в реестре")
        checks.append("H1 сервис известен")

        # --- H2: глагол объявлен ---
        cap = manifest.verb(verb_id)
        if cap is None:
            return block(f"глагол '{verb_id}' не объявлен в манифесте сервиса '{service}'")
        checks.append("H2 глагол объявлен")

        # --- W0: объявленное время годно (§6.1) ---
        # Негодный `when` — штатный отказ губернатора, а не исключение. Раньше
        # WhenError вылетал отсюда наружу: исполнитель уже записал intent, decision
        # не записывался, и в хэш-цепи оставалось намерение без решения. Отказ,
        # которого нет в журнале, для аудита хуже открытого отказа.
        # Проверка стоит здесь, до H8: предикат расписания уже должен получать
        # годное время. Проверяем только объявленный блок: отсутствие `when`
        # допустимо (§6.1 — SHOULD). Для валидного блока журнал не меняется:
        # пройденная проверка не добавляет метку в `checks`.
        if payload.get("when") is not None:
            defect = self._when_defect(service, verb_id, payload["when"])
            if defect is not None:
                return block(defect)

        # Чтение не меняет мир — проходит без дальнейших проверок.
        if cap.effect == "read":
            checks.append("effect=read — гейт не требуется")
            return Decision(ADMIT, "чтение не меняет состояние", verb_id, service, None, checks)

        # --- H4: необратимое ОБЯЗАТЕЛЬСТВО без участия человека ---
        # Ограничение именно обязательствами существенно: отпускание удержания
        # (slot.release) тоже «необратимо» — отменить отмену нельзя, — но оно
        # лишь возвращает мир в прежнее состояние и человека не требует.
        # Предикат, применённый ко всем эффектам, блокировал бы откат — то есть
        # делал бы систему опаснее, запрещая ей убирать за собой.
        if cap.is_committing and not cap.reversible and cap.consent == "none":
            return block(
                "необратимое обязательство без участия человека",
                self._safer(manifest, cap),
            )
        checks.append("H4 необратимость согласована с consent")

        # --- H5: идемпотентность для обязательств ---
        if cap.is_committing:
            if cap.idempotency_slot() is None:
                return block(f"глагол '{verb_id}' создаёт обязательство без ключа идемпотентности")
            if not idempotency_key:
                return block(
                    "не передан ключ идемпотентности, объявленный манифестом "
                    f"({cap.idempotency})"
                )
            # --- H6: повтор ---
            seen = self.ledger.find_idempotency(idempotency_key)
            if seen is not None:
                return block(
                    f"повтор: ключ идемпотентности уже исполнен в записи #{seen.seq}"
                )
            checks.append("H5/H6 идемпотентность объявлена, ключ свежий")

        # --- H7: удержание не просрочено ---
        if hold is not None:
            expires = hold.get("expires_at")
            if expires:
                deadline = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                if deadline <= datetime.now(timezone.utc):
                    return block(
                        "удержание истекло — обязательство нельзя оформить на просроченный резерв",
                        {"verb": hold.get("verb", ""), "note": "повторить удержание"},
                    )
            checks.append("H7 удержание действительно")

        # --- H3: бюджет ---
        estimate = self._estimate(cap, payload)
        if estimate is not None:
            if estimate > self.budget.remaining:
                return block(
                    f"превышение бюджета: нужно {estimate:.2f} {self.budget.currency}, "
                    f"остаток {self.budget.remaining:.2f}",
                    self._cheaper(cap, payload),
                )
            checks.append(f"H3 бюджет выдерживает ({estimate:.2f} ≤ {self.budget.remaining:.2f})")

        # --- H8: конфликт расписания (§5.1.8) ---
        # Только для обязательств: удержание обратимо и само истекает, поэтому
        # запрещать попытку занять время было бы запретом на разведку — агент
        # должен иметь право подержать слот, увидеть конфликт и отпустить его.
        # Арифметика неисполнимости живёт в schedule_guard/calendar: губернатор
        # лишь спрашивает и, если ответ непустой, отказывает их же словами.
        if cap.is_committing and self.schedule_guard is not None:
            conflicts = self.schedule_guard.check(service, verb_id, payload, manifest)
            if conflicts:
                return block(
                    self.schedule_guard.reason(conflicts),
                    self.schedule_guard.alternative(
                        service, verb_id, payload, manifest, conflicts),
                )
            checks.append("H8 расписание вмещает обязательство")

        # --- S2: переменная цена без потолка ---
        if cap.money_is_variable and estimate is None:
            return escalate(
                "цена станет известна только из ответа, а потолок max_money не задан"
            )

        # --- S3: требуется согласие ---
        if cap.consent in ("confirm", "two_party"):
            key = f"{service}:{verb_id}:{idempotency_key or ''}"
            if key not in self.confirmations:
                who = "владельца профиля" if cap.consent == "confirm" else "обеих сторон"
                return escalate(f"требуется подтверждение {who} (consent={cap.consent})")
            checks.append(f"S3 подтверждение получено ({cap.consent})")

        # --- S1: дорого относительно остатка ---
        if estimate is not None and self.budget.remaining > 0:
            if estimate > self.budget.remaining * self.escalate_fraction:
                return escalate(
                    f"сумма {estimate:.2f} превышает {int(self.escalate_fraction * 100)}% "
                    f"остатка бюджета ({self.budget.remaining:.2f})"
                )

        # --- S4: первое взаимодействие с сервисом ---
        known = any(
            r.payload.get("service") == service
            for r in self.ledger.by_kind("execution")
        )
        if not known and cap.severity >= 2:
            return escalate(f"первое обязывающее взаимодействие с сервисом '{service}'")
        checks.append("S4 сервис уже встречался в журнале" if known else "S4 чтение/резерв — допустимо")

        return Decision(ADMIT, "все предикаты пройдены", verb_id, service, None, checks)

    # ---------- безопасные альтернативы (§5.3) ----------

    def _safer(self, manifest: Manifest, cap: Capability) -> dict[str, Any] | None:
        """Заменить обязательство парным обратимым удержанием, если оно есть."""
        for other in manifest:
            if other.effect == "reserve" and other.id.split(".")[0] == cap.id.split(".")[0]:
                return {
                    "verb": other.id,
                    "note": f"сначала обратимое удержание '{other.id}', затем подтверждение",
                }
        return None

    def _cheaper(self, cap: Capability, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Понизить количество так, чтобы уложиться в остаток бюджета."""
        unit = cap.declared_money()
        qty = payload.get("quantity")
        if unit and unit > 0 and isinstance(qty, int) and qty > 1:
            affordable = int(self.budget.remaining // unit)
            if affordable >= 1:
                return {"verb": cap.id, "quantity": affordable,
                        "note": f"уложиться в бюджет: {affordable} вместо {qty}"}
        return None
