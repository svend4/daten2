"""Профили возможностей уровней: выбор уровня по требованию задачи.

Зачем этот модуль существует
────────────────────────────
Семь уровней daten2 держат ОДИН контракт из четырёх глаголов — и в этом вся
идея: уровень можно подменить, не меняя агента. Но взаимозаменяемость верна
только для ядра. Выше ядра уровни не равны: один не проверяет склад, другой
рассыпается при шести одновременных заказах, третий вообще не реализует
`order.get`, четвёртый тащит за собой шесть контейнеров.

Пока эти различия живут в голове у человека, роутер выбирает «любой из
эквивалентных» и получает тот, который не умеет нужного. Поэтому:

    ЯДРО КОНТРАКТА ОБЩЕЕ (взаимозаменяемость сохраняется),
    СВЕРХУ — ОБЪЯВЛЕННЫЙ ПРОФИЛЬ ВОЗМОЖНОСТЕЙ каждого уровня.

Тогда выбор делается не «любой», а «тот, чей профиль покрывает требование».
Свой гаечный ключ под свой размер — при одной и той же резьбе.

Главное решение: НАЙДЕННЫЕ АУДИТОМ ДЕФЕКТЫ — ЧАСТЬ МАНИФЕСТА.
Уровень, который не умеет конкурентные заказы, обязан это объявить машинно
читаемым полем, а не оставить в чужом отчёте. Профиль, который умалчивает о
дефекте, молча проигрывает конкурсу: требование «нужна конкурентность»
отсеивает именно того, кто сознался.

Важная граница (SPEC-NPP-ACT.md §10.1): профиль — ЗАЯВЛЕНИЕ, а не
доказательство. Этот модуль умеет только читать заявления и сопоставлять их с
требованием. Проверять заявления обязан потребитель; как это делается — видно
в `act/tests/test_profile.py`, где каждое поле семи профилей сверяется с
настоящими исходниками уровней, а не с мнением этого модуля о них.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import parse_manifest

#: Вес развёртывания по возрастанию. Порядок — смысловой: сравнение весов
#: имеет значение «не тяжелее, чем», поэтому список, а не множество.
WEIGHTS = ("minimal", "light", "medium", "heavy")

#: Хранилища, различимые на уровне профиля. Разница не косметическая:
#: от неё зависит, нужен ли уровню внешний демон.
STORAGES = ("sqlite", "postgres")

#: Объявляемые возможности поверх ядра. Закрытый список: опечатка в имени
#: возможности обязана быть ошибкой, а не молча выполненным требованием.
FEATURES = (
    "has_admin",        # рабочая админка (L3)
    "decimal_money",    # деньги в Decimal, а не в float (L3, L6)
    "event_bus",        # события уходят в брокер (L7)
    "offline_capable",  # контракт отвечает без внешних демонов и без сборки фронтенда
    "status_machine",   # статусная машина заказа (L3)
    "spa_frontend",     # витрина — отдельное SPA-приложение
)

#: Как получено утверждение о конкурентности. Отличать измеренное от
#: предположенного необходимо: «не измеряли» — не то же самое, что «выдержит».
CONCURRENCY_EVIDENCE = ("measured", "by_design", "not_measured")


class ProfileError(ValueError):
    """Профиль уровня или требование нарушают форму."""


@dataclass(frozen=True)
class Defect:
    """Один объявленный дефект уровня.

    `evidence` — не пересказ дефекта, а указание на место в исходниках, по
    которому утверждение можно перепроверить. Без этого поля блок дефектов
    был бы самооценкой.
    """

    code: str
    severity: str
    detail: str
    evidence: str = ""


@dataclass(frozen=True)
class LevelProfile:
    """Разобранный блок `level_profile` одного уровня.

    Поля ядра (глаголы, их эффекты и согласия) здесь намеренно отсутствуют:
    они одинаковы у всех семи уровней и живут в `Manifest`. Здесь — только то,
    чем уровни РАЗЛИЧАЮТСЯ.
    """

    service: str
    level: int
    title: str
    base_url: str
    stack: str
    language: str
    storage: str
    weight: str
    runtime_units: int
    transactional: bool
    stock_checked: bool
    concurrency_safe: bool
    concurrency_evidence: str
    conformance_passed: int
    conformance_total: int
    missing_verbs: frozenset[str]
    features: frozenset[str]
    declared_verbs: frozenset[str]
    defects: tuple[Defect, ...] = ()
    audit: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = ""

    # ---------- производные свойства ----------

    @property
    def weight_rank(self) -> int:
        return WEIGHTS.index(self.weight)

    @property
    def conformance_ratio(self) -> float:
        return self.conformance_passed / self.conformance_total

    @property
    def fully_conformant(self) -> bool:
        return self.conformance_passed == self.conformance_total

    @property
    def effective_verbs(self) -> frozenset[str]:
        """Глаголы, которые уровень действительно даёт.

        Манифест объявляет ядро целиком — иначе уровень выпал бы из
        взаимозаменяемости. `missing_verbs` — признание, что один из глаголов
        ядра на этом уровне не реализован. Вычитание и есть честный ответ.
        """
        return self.declared_verbs - self.missing_verbs

    def has(self, feature: str) -> bool:
        if feature not in FEATURES:
            raise ProfileError(f"неизвестная возможность '{feature}'")
        return feature in self.features

    def provides(self, verb_id: str) -> bool:
        return verb_id in self.effective_verbs

    def defect(self, code: str) -> Defect | None:
        for d in self.defects:
            if d.code == code:
                return d
        return None

    def describe(self) -> str:
        """Одна строка для таблицы сравнения — то, что увидит человек."""
        flags = ",".join(sorted(self.features)) or "—"
        return (
            f"L{self.level} {self.service:<19} {self.weight:<8} "
            f"{self.storage:<9} {self.conformance_passed:>2}/{self.conformance_total} "
            f"tx={'да' if self.transactional else 'нет':<3} "
            f"склад={'да' if self.stock_checked else 'нет':<3} "
            f"конкур={'да' if self.concurrency_safe else 'нет':<3} {flags}"
        )


@dataclass(frozen=True)
class Requirement:
    """Чего требует задача от уровня.

    Все поля необязательны: пустое требование означает «подойдёт любой», и
    тогда выбор решается весом — в этом смысл `rank`. Имена полей
    проверяются при создании: требование с опечаткой («needs_stok_check»)
    было бы требованием, которое всегда выполнено, то есть худшим из багов.
    """

    verbs: tuple[str, ...] = ()
    needs_transaction: bool = False
    needs_stock_check: bool = False
    needs_concurrency: bool = False
    needs_full_conformance: bool = False
    max_weight: str | None = None
    max_runtime_units: int | None = None
    storage: str | None = None
    features: tuple[str, ...] = ()
    label: str = ""

    def __post_init__(self) -> None:
        if self.max_weight is not None and self.max_weight not in WEIGHTS:
            raise ProfileError(f"max_weight должен быть одним из {list(WEIGHTS)}")
        if self.storage is not None and self.storage not in STORAGES:
            raise ProfileError(f"storage должен быть одним из {list(STORAGES)}")
        for f in self.features:
            if f not in FEATURES:
                raise ProfileError(f"неизвестная возможность '{f}'; допустимы {list(FEATURES)}")
        if self.max_runtime_units is not None and self.max_runtime_units < 1:
            raise ProfileError("max_runtime_units — не меньше одной единицы развёртывания")

    @property
    def is_empty(self) -> bool:
        return self == Requirement(label=self.label)

    def human(self) -> str:
        if self.label:
            return self.label
        parts: list[str] = []
        if self.verbs:
            parts.append("глаголы: " + ", ".join(self.verbs))
        if self.needs_transaction:
            parts.append("транзакция с откатом")
        if self.needs_stock_check:
            parts.append("проверка склада")
        if self.needs_concurrency:
            parts.append("параллельные заказы")
        if self.needs_full_conformance:
            parts.append("полное соответствие контракту")
        if self.max_weight:
            parts.append(f"вес не тяжелее '{self.max_weight}'")
        if self.max_runtime_units:
            parts.append(f"не более {self.max_runtime_units} единиц развёртывания")
        if self.storage:
            parts.append(f"хранилище '{self.storage}'")
        if self.features:
            parts.append("возможности: " + ", ".join(self.features))
        return "; ".join(parts) if parts else "без требований"


# ────────────────────────────────────────────────────────────────────────────
# Сопоставление
# ────────────────────────────────────────────────────────────────────────────

def covers(profile: LevelProfile, requirement: Requirement) -> tuple[bool, list[str]]:
    """Покрывает ли профиль требование → (да/нет, причины несоответствия).

    Причины возвращаются ВСЕ, а не первая найденная: человеку, выбирающему
    уровень, важно знать полную цену отказа, иначе он будет снимать требования
    по одному и каждый раз получать новый отказ.
    """
    reasons: list[str] = []

    for verb in requirement.verbs:
        if verb in profile.missing_verbs:
            reasons.append(f"глагол '{verb}' объявлен как нереализованный (missing_verbs)")
        elif verb not in profile.declared_verbs:
            reasons.append(f"глагол '{verb}' не объявлен в манифесте уровня")

    if requirement.needs_transaction and not profile.transactional:
        reasons.append("нет транзакции с откатом: сбой на середине оставит половину заказа")

    if requirement.needs_stock_check and not profile.stock_checked:
        reasons.append("остаток на складе не проверяется: заказ пройдёт при нулевом наличии")

    if requirement.needs_concurrency and not profile.concurrency_safe:
        reasons.append("не выдерживает параллельные заказы")

    if requirement.needs_full_conformance and not profile.fully_conformant:
        reasons.append(
            f"соответствие контракту {profile.conformance_passed}/{profile.conformance_total}, "
            f"требуется полное"
        )

    if requirement.max_weight is not None:
        limit = WEIGHTS.index(requirement.max_weight)
        if profile.weight_rank > limit:
            reasons.append(
                f"вес развёртывания '{profile.weight}' тяжелее допустимого "
                f"'{requirement.max_weight}'"
            )

    if requirement.max_runtime_units is not None and profile.runtime_units > requirement.max_runtime_units:
        reasons.append(
            f"развёртывание из {profile.runtime_units} единиц, "
            f"допустимо не более {requirement.max_runtime_units}"
        )

    if requirement.storage is not None and profile.storage != requirement.storage:
        reasons.append(f"хранилище '{profile.storage}', требуется '{requirement.storage}'")

    for feature in requirement.features:
        if feature not in profile.features:
            reasons.append(f"нет объявленной возможности '{feature}'")

    return (not reasons), reasons


def rank_report(
    profiles: "dict[str, LevelProfile] | list[LevelProfile]",
    requirement: Requirement,
) -> tuple[list[LevelProfile], dict[str, list[str]]]:
    """(подходящие по возрастанию цены, {сервис: причины отказа}).

    Критерий сортировки подходящих, в порядке применения:
      1. вес развёртывания — самый лёгкий первым: платить шестью контейнерами
         за задачу, которую решает один файл, незачем;
      2. при равном весе — выше соответствие контракту: из двух одинаково
         дешёвых берём тот, который меньше удивит клиента;
      3. при равном и этом — младший номер уровня, чтобы порядок был
         детерминированным и воспроизводимым в тестах.
    """
    items = list(profiles.values()) if isinstance(profiles, dict) else list(profiles)

    fitting: list[LevelProfile] = []
    rejected: dict[str, list[str]] = {}
    for prof in items:
        ok, reasons = covers(prof, requirement)
        if ok:
            fitting.append(prof)
        else:
            rejected[prof.service] = reasons

    fitting.sort(key=lambda p: (p.weight_rank, -p.conformance_ratio, p.level))
    return fitting, rejected


def rank(
    profiles: "dict[str, LevelProfile] | list[LevelProfile]",
    requirement: Requirement,
) -> list[LevelProfile]:
    """Подходящие уровни, лучший первым. Непригодные не возвращаются вовсе."""
    return rank_report(profiles, requirement)[0]


def best(
    profiles: "dict[str, LevelProfile] | list[LevelProfile]",
    requirement: Requirement,
) -> LevelProfile | None:
    """Победитель или None, если требование невыполнимо ни одним уровнем."""
    fitting = rank(profiles, requirement)
    return fitting[0] if fitting else None


# ────────────────────────────────────────────────────────────────────────────
# Загрузка
# ────────────────────────────────────────────────────────────────────────────

def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ProfileError(message)


def parse_level_profile(raw: dict[str, Any]) -> LevelProfile:
    """Разобрать манифест уровня целиком: ядро через штатный валидатор, профиль здесь.

    Ядро проверяется `parse_manifest` намеренно: профиль не вправе
    существовать без действующего манифеста. Уровень, объявивший богатый
    профиль поверх невалидного ядра, выпадает из взаимозаменяемости, а значит
    его профиль не имеет смысла.
    """
    manifest = parse_manifest(raw)

    _require("level_profile" in raw, f"{manifest.service}: отсутствует блок 'level_profile'")
    p = raw["level_profile"]
    _require(isinstance(p, dict), f"{manifest.service}: 'level_profile' должен быть объектом")

    where = manifest.service
    for key in (
        "level", "stack", "language", "storage", "weight", "runtime_units",
        "transactional", "stock_checked", "concurrency_safe",
        "contract_conformance", "missing_verbs", "features",
    ):
        _require(key in p, f"{where}: level_profile.{key} обязателен")

    _require(isinstance(p["level"], int) and 1 <= p["level"] <= 7,
             f"{where}: level — целое от 1 до 7")
    _require(p["storage"] in STORAGES, f"{where}: storage должен быть одним из {list(STORAGES)}")
    _require(p["weight"] in WEIGHTS, f"{where}: weight должен быть одним из {list(WEIGHTS)}")
    _require(isinstance(p["runtime_units"], int) and p["runtime_units"] >= 1,
             f"{where}: runtime_units — целое не меньше 1")
    for key in ("transactional", "stock_checked", "concurrency_safe"):
        _require(isinstance(p[key], bool), f"{where}: level_profile.{key} — boolean")

    evidence = p.get("concurrency_evidence", "not_measured")
    _require(evidence in CONCURRENCY_EVIDENCE,
             f"{where}: concurrency_evidence должен быть одним из {list(CONCURRENCY_EVIDENCE)}")

    conf = p["contract_conformance"]
    _require(isinstance(conf, dict) and {"passed", "total"} <= set(conf),
             f"{where}: contract_conformance = {{passed, total}}")
    passed, total = int(conf["passed"]), int(conf["total"])
    _require(total > 0 and 0 <= passed <= total,
             f"{where}: contract_conformance — 0 ≤ passed ≤ total, total > 0")

    missing = p["missing_verbs"]
    _require(isinstance(missing, list), f"{where}: missing_verbs — список")
    declared = frozenset(manifest.capabilities)
    for verb in missing:
        # Признаваться можно только в том, что объявлено: «missing_verbs» с
        # чужим глаголом — не признание, а шум.
        _require(verb in declared,
                 f"{where}: missing_verbs содержит '{verb}', которого нет в capabilities")

    feats = p["features"]
    _require(isinstance(feats, dict), f"{where}: features — объект имя→boolean")
    for name, value in feats.items():
        _require(name in FEATURES, f"{where}: неизвестная возможность '{name}'")
        _require(isinstance(value, bool), f"{where}: features.{name} — boolean")

    defects = tuple(
        Defect(
            code=str(d["code"]),
            severity=str(d.get("severity", "info")),
            detail=str(d.get("detail", "")),
            evidence=str(d.get("evidence", "")),
        )
        for d in p.get("defects", [])
    )

    # Дефект без объявленного ограничения — реклама, а не признание.
    # Проверяем самое дорогое соответствие: если уровень признал дефект
    # конкурентности, флаг concurrency_safe обязан быть снят.
    for d in defects:
        if "concurren" in d.code or "handle" in d.code:
            _require(
                not p["concurrency_safe"],
                f"{where}: дефект '{d.code}' объявлен, но concurrency_safe=true",
            )

    return LevelProfile(
        service=manifest.service,
        level=p["level"],
        title=manifest.title,
        base_url=manifest.base_url,
        stack=str(p["stack"]),
        language=str(p["language"]),
        storage=p["storage"],
        weight=p["weight"],
        runtime_units=p["runtime_units"],
        transactional=p["transactional"],
        stock_checked=p["stock_checked"],
        concurrency_safe=p["concurrency_safe"],
        concurrency_evidence=evidence,
        conformance_passed=passed,
        conformance_total=total,
        missing_verbs=frozenset(missing),
        features=frozenset(name for name, value in feats.items() if value),
        declared_verbs=declared,
        defects=defects,
        audit=dict(p.get("audit", {})),
        disclaimer=str(p.get("disclaimer", "")),
    )


def load_level_profile(path: str | Path) -> LevelProfile:
    return parse_level_profile(json.loads(Path(path).read_text(encoding="utf-8")))


def load_level_profiles(directory: str | Path) -> dict[str, LevelProfile]:
    """Все профили уровней из каталога → {service: LevelProfile}."""
    out: dict[str, LevelProfile] = {}
    for path in sorted(Path(directory).glob("*.act.json")):
        prof = load_level_profile(path)
        if prof.service in out:
            raise ProfileError(f"сервис '{prof.service}' объявлен дважды в {directory}")
        out[prof.service] = prof
    if not out:
        raise ProfileError(f"в каталоге {directory} нет манифестов *.act.json")
    return out


# ────────────────────────────────────────────────────────────────────────────
# Человекочитаемый вывод: «какой ключ под какой размер»
# ────────────────────────────────────────────────────────────────────────────

def comparison_table(profiles: dict[str, LevelProfile]) -> str:
    rows = sorted(profiles.values(), key=lambda p: p.level)
    return "\n".join(p.describe() for p in rows)


def explain(profiles: dict[str, LevelProfile], requirement: Requirement) -> str:
    """Отчёт о выборе: кто подошёл, кто нет и почему именно."""
    fitting, rejected = rank_report(profiles, requirement)
    lines = [f"Требование: {requirement.human()}"]
    if fitting:
        lines.append("Подходят (лучший первым):")
        for i, p in enumerate(fitting, 1):
            lines.append(f"  {i}. L{p.level} {p.service} — вес {p.weight}, "
                         f"контракт {p.conformance_passed}/{p.conformance_total}")
    else:
        lines.append("Не подходит ни один уровень.")
    if rejected:
        lines.append("Отклонены:")
        for svc in sorted(rejected):
            lines.append(f"  · {svc}: " + "; ".join(rejected[svc]))
    return "\n".join(lines)


if __name__ == "__main__":  # удобный ручной просмотр, не часть API
    here = Path(__file__).resolve().parents[1] / "manifests" / "levels"
    profs = load_level_profiles(here)
    print(comparison_table(profs))
    print()
    print(explain(profs, Requirement(needs_concurrency=True, needs_full_conformance=True,
                                     label="надёжный приём заказов под нагрузкой")))
