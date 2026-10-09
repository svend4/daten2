"""Манифест возможностей: загрузка и валидация (SPEC-NPP-ACT.md §3-4).

Валидатор написан вручную, без jsonschema — чтобы модуль не тянул зависимостей.
Проверяются именно те инварианты, на которых потом стоит губернатор:
без них решение о допуске действия принять нельзя.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EFFECTS = ["read", "reserve", "commit", "money", "destroy"]
CONSENTS = ["none", "notify", "confirm", "two_party"]
PROFILES = ["person", "vendor", "venue", "institution", "broker"]
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
IDEMPOTENCY_RE = re.compile(r"^(none|header:[-A-Za-z0-9]+|field:[a-z_]+)$")

#: Глаголы тяжелее `reserve` создают последствия, которые нельзя «просто отменить».
COMMITTING = {"commit", "money", "destroy"}


class ManifestError(ValueError):
    """Манифест нарушает спецификацию."""


@dataclass(frozen=True)
class Capability:
    """Один объявленный глагол — операция с описанными последствиями."""

    id: str
    title: str
    effect: str
    reversible: bool
    cost: dict[str, Any]
    consent: str
    binding: dict[str, str]
    reverse: str | None = None
    idempotency: str = "none"
    expires_s: float | None = None
    description: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> int:
        """Тяжесть эффекта: монотонна, 0 (read) … 4 (destroy)."""
        return EFFECTS.index(self.effect)

    @property
    def is_committing(self) -> bool:
        return self.effect in COMMITTING

    @property
    def money_is_variable(self) -> bool:
        return self.cost.get("money") == "variable"

    def declared_money(self) -> float | None:
        """Объявленная стоимость, или None если она становится известна только из ответа."""
        m = self.cost.get("money")
        return None if m == "variable" else float(m)

    def idempotency_slot(self) -> tuple[str, str] | None:
        """('header'|'field', имя) либо None, если идемпотентность не объявлена."""
        if self.idempotency == "none":
            return None
        kind, _, name = self.idempotency.partition(":")
        return kind, name


@dataclass(frozen=True)
class Manifest:
    """Манифест Actionable-сервиса."""

    service: str
    title: str
    base_url: str
    profile: str
    capabilities: dict[str, Capability]
    q6: str | None = None

    def verb(self, verb_id: str) -> Capability | None:
        return self.capabilities.get(verb_id)

    def __iter__(self):
        return iter(self.capabilities.values())


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ManifestError(message)


def _parse_capability(raw: dict[str, Any], service: str) -> Capability:
    where = f"{service}:{raw.get('id', '<без id>')}"

    for key in ("id", "title", "effect", "reversible", "cost", "consent", "binding"):
        _require(key in raw, f"{where}: отсутствует обязательное поле '{key}'")

    cap_id = raw["id"]
    _require(bool(ID_RE.match(cap_id)), f"{where}: id должен иметь вид 'предмет.действие'")
    _require(raw["effect"] in EFFECTS, f"{where}: effect должен быть одним из {EFFECTS}")
    _require(raw["consent"] in CONSENTS, f"{where}: consent должен быть одним из {CONSENTS}")
    _require(isinstance(raw["reversible"], bool), f"{where}: reversible должен быть boolean")

    cost = raw["cost"]
    _require(isinstance(cost, dict) and "money" in cost, f"{where}: cost.money обязателен")
    money = cost["money"]
    _require(
        money == "variable" or (isinstance(money, (int, float)) and money >= 0),
        f"{where}: cost.money — неотрицательное число или \"variable\"",
    )

    binding = raw["binding"]
    _require(binding.get("protocol") == "http", f"{where}: поддерживается только protocol=http")
    _require(binding.get("method") in METHODS, f"{where}: method должен быть одним из {METHODS}")
    _require(str(binding.get("path", "")).startswith("/"), f"{where}: path должен начинаться с '/'")

    idem = raw.get("idempotency", "none")
    _require(bool(IDEMPOTENCY_RE.match(idem)), f"{where}: некорректная форма idempotency")

    reversible = raw["reversible"]
    reverse = raw.get("reverse")

    # §4.2 — обратимость обязана быть исполнимой, а не декларативной.
    if reversible:
        _require(bool(reverse), f"{where}: reversible=true требует указания обратного глагола 'reverse'")
    else:
        _require(reverse is None, f"{where}: reverse указан при reversible=false")

    # §4.5 — обязательство без идемпотентности исполнить нельзя: повтор создаст второе.
    if raw["effect"] in COMMITTING:
        _require(
            idem != "none" or raw.get("accept_double_execution") is True,
            f"{where}: effect='{raw['effect']}' требует idempotency "
            f"(или явного accept_double_execution=true)",
        )

    # §5.1.4 — необратимое действие без участия человека запрещено на уровне манифеста,
    # чтобы такой глагол нельзя было даже объявить.
    if not reversible and raw["consent"] == "none" and raw["effect"] in COMMITTING:
        raise ManifestError(
            f"{where}: необратимый глагол с consent='none' недопустим — "
            f"укажите consent 'confirm'/'two_party' либо сделайте его обратимым"
        )

    if raw["effect"] == "reserve":
        _require(
            raw.get("expires_s") is not None,
            f"{where}: effect='reserve' требует expires_s — удержание обязано истекать",
        )

    return Capability(
        id=cap_id,
        title=raw["title"],
        effect=raw["effect"],
        reversible=reversible,
        cost=cost,
        consent=raw["consent"],
        binding=binding,
        reverse=reverse,
        idempotency=idem,
        expires_s=raw.get("expires_s"),
        description=raw.get("description", ""),
        input=raw.get("input", {}),
        output=raw.get("output", {}),
    )


def parse_manifest(raw: dict[str, Any]) -> Manifest:
    """Разобрать и проверить манифест. Бросает ManifestError при любом нарушении."""
    _require(raw.get("npp_act") == "1.0", "манифест: требуется npp_act='1.0'")
    for key in ("service", "base_url", "profile", "capabilities"):
        _require(key in raw, f"манифест: отсутствует обязательное поле '{key}'")

    service = raw["service"]
    _require(bool(SERVICE_RE.match(service)), "манифест: некорректный идентификатор service")
    _require(raw["profile"] in PROFILES, f"манифест: profile должен быть одним из {PROFILES}")
    _require(str(raw["base_url"]).startswith(("http://", "https://")), "манифест: base_url должен быть http(s)")
    _require(isinstance(raw["capabilities"], list) and raw["capabilities"],
             "манифест: capabilities должен быть непустым списком")

    q6 = raw.get("q6")
    if q6 is not None:
        _require(bool(re.match(r"^[01]{6}$", q6)), "манифест: q6 — ровно шесть бит")

    caps: dict[str, Capability] = {}
    for item in raw["capabilities"]:
        cap = _parse_capability(item, service)
        _require(cap.id not in caps, f"{service}: глагол '{cap.id}' объявлен дважды")
        caps[cap.id] = cap

    # Ссылки на обратные глаголы должны разрешаться внутри того же манифеста.
    for cap in caps.values():
        if cap.reverse is not None:
            _require(
                cap.reverse in caps,
                f"{service}:{cap.id}: обратный глагол '{cap.reverse}' не объявлен в манифесте",
            )

    return Manifest(
        service=service,
        title=raw.get("title", service),
        base_url=raw["base_url"].rstrip("/"),
        profile=raw["profile"],
        capabilities=caps,
        q6=q6,
    )


def load_manifest(path: str | Path) -> Manifest:
    """Загрузить манифест из файла."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_manifest(data)
