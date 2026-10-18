"""Исполнитель: единственное место, где глагол превращается в HTTP-вызов.

Инвариант, ради которого модуль существует: исполнитель MUST NOT вызывать
ничего тяжелее чтения без решения губернатора. Проверка стоит внутри, а не
в вызывающем коде, — чтобы её нельзя было обойти по невнимательности.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .calendar import WhenError
from .governor import BLOCK, Decision, Governor
from .ledger import Ledger
from .manifest import Capability, Manifest


class ExecutionError(RuntimeError):
    """Вызов не состоялся или сервис ответил ошибкой."""


@dataclass
class Result:
    ok: bool
    status: int
    body: Any
    verb: str
    service: str
    idempotency_key: str | None = None


class Executor:
    """Исполняет допущенные глаголы и записывает всё, что произошло, в журнал."""

    def __init__(self, registry, governor: Governor, ledger: Ledger, timeout: float = 10.0):
        self.registry = registry
        self.governor = governor
        self.ledger = ledger
        self.timeout = timeout

    # ---------- HTTP ----------

    def _call(self, manifest: Manifest, cap: Capability,
              payload: dict[str, Any], idempotency_key: str | None) -> Result:
        binding = cap.binding
        path = binding["path"]
        body: dict[str, Any] = dict(payload)

        # Подстановка path-параметров вида /api/holds/{hold_id}
        for key in list(body):
            token = "{" + key + "}"
            if token in path:
                path = path.replace(token, str(body.pop(key)))

        url = manifest.base_url + path
        method = binding["method"]
        headers = {"Accept": "application/json"}
        data: bytes | None = None

        slot = cap.idempotency_slot()
        if slot and idempotency_key:
            kind, name = slot
            if kind == "header":
                headers[name] = idempotency_key
            else:
                body[name] = idempotency_key

        if method in ("POST", "PUT", "PATCH"):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif body:
            url += "?" + urllib.parse.urlencode(body)

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else None
                return Result(True, resp.status, parsed, cap.id, manifest.service, idempotency_key)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"error": raw[:200]}
            return Result(False, e.code, parsed, cap.id, manifest.service, idempotency_key)
        except (urllib.error.URLError, OSError) as e:
            raise ExecutionError(f"{manifest.service}:{cap.id} — сервис недоступен: {e}") from e

    # ---------- главный вход ----------

    def perform(
        self,
        service: str,
        verb_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        hold: dict[str, Any] | None = None,
    ) -> tuple[Decision, Result | None]:
        """Намерение → решение губернатора → (если допущено) исполнение → исход.

        Возвращает решение всегда; результат — только если действие было допущено.
        В журнал попадают все четыре стадии, включая отказ.
        """
        payload = payload or {}

        self.ledger.append("intent", {
            "service": service, "verb": verb_id,
            "payload": _redact(payload), "idempotency_key": idempotency_key,
        })

        try:
            decision = self.governor.evaluate(service, verb_id, payload, idempotency_key, hold)
        except WhenError as e:
            # Страховка границы. Губернатор сам отвергает негодный `when` (W0), но
            # предикат H8 или чужой schedule_guard может бросить WhenError. Если
            # исключение долетит сюда, цепь останется с intent без decision — ровно
            # тот дефект, ради которого W0 существует. Поэтому отказ становится
            # решением `block` и записывается в журнал, а не уходит наружу.
            decision = Decision(
                BLOCK, f"негодное время обязательства (§6.1): {e}",
                verb_id, service, None, [])

        self.ledger.append("decision", {
            "service": service, "verb": verb_id,
            "verdict": decision.verdict, "reason": decision.reason,
            "alternative": decision.alternative, "checks": decision.checks,
        })

        if not decision.admitted:
            return decision, None

        manifest = self.registry.manifest(service)
        cap = manifest.verb(verb_id)

        result = self._call(manifest, cap, payload, idempotency_key)

        self.ledger.append("execution", {
            "service": service, "verb": verb_id,
            "status": result.status, "ok": result.ok,
            "idempotency_key": idempotency_key,
        })

        # Деньги списываются по факту: объявленная цена либо фактическая из ответа.
        charged = 0.0
        if result.ok:
            actual = None
            if isinstance(result.body, dict):
                for key in ("total", "total_amount", "amount", "price"):
                    if key in result.body:
                        actual = float(result.body[key])
                        break
            declared = cap.declared_money()
            charged = actual if actual is not None else (declared or 0.0)
            if charged:
                self.governor.budget.charge(charged)

        self.ledger.append("outcome", {
            "service": service, "verb": verb_id,
            "ok": result.ok, "charged": charged,
            "budget_remaining": self.governor.budget.remaining,
            "response": _redact(result.body) if isinstance(result.body, dict) else result.body,
        })

        return decision, result


def _redact(obj: Any) -> Any:
    """Убрать из журнала то, что не должно в нём лежать (§10.2)."""
    if not isinstance(obj, dict):
        return obj
    secret = {"phone", "email", "password", "token", "card", "address"}
    return {k: ("<скрыто>" if k.lower() in secret else v) for k, v in obj.items()}
