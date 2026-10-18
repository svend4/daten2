"""Профиль как ИЗМЕРЕНИЕ, а не как заявление (SPEC-NPP-ACT.md §10.1).

Зачем этот модуль существует
────────────────────────────
Этап 8 дал уровням `level_profile`: машинно читаемое объявление возможностей и
признанных дефектов. Это был шаг вперёд — но ровно половина пути. §10.1 говорит
прямо: **манифест — это заявление, а не доказательство**. Профиль пишет человек,
и ничто не мешает ему написать `stock_checked: true` в сервисе, который остаток
не читает ни одной строкой кода.

Пока профиль пишется руками, роутер верит на слово. Именно эту дыру и
демонстрирует `plugin-marketplace` из daten2: у него 14/14 зелёных проверок — и
при этом он отвергает все настоящие бэкенды. Причина не в небрежности, а в
устройстве: он сверяет сервис с ОБЪЯВЛЕНИЕМ и со своим же моком, написанным под
те же допущения. Такая проверка не может провалиться и поэтому ничего не
доказывает.

Этот модуль закрывает дыру с другой стороны: он не читает заявление, а
**трогает живой сервис** и собирает профиль из наблюдений. Пять проб:

    contract     — вызвать каждый объявленный глагол и сверить ФОРМУ ответа
                   с его же output-схемой → измеренное contract_conformance;
    stock        — заказать заведомо больше остатка; принятие = stock_checked:false
                   (именно эта проба поймала шесть уровней daten2 из семи);
    concurrency  — N одновременных обязательств; частичные отказы = не держит;
    idempotency  — один ключ дважды: повтор обязан вернуть ТО ЖЕ обязательство;
    latency      — p50/p95 на чтении.

Почему проба не идёт через губернатора
──────────────────────────────────────
Исполнитель (`executor.py`) обязан спрашивать губернатора — и правильно: он
действует ОТ ИМЕНИ ВЛАДЕЛЬЦА и обязан защищать его бюджет и необратимость.
Проба — другая роль. Её задача — **не верить сервису**, а для этого глагол
нужно именно вызвать: заявление о идемпотентности нельзя проверить, не послав
ключ дважды. Поэтому проба заменяет губернатора своим, более узким запретом:

  · `destroy` не пробуется НИКОГДА;
  · `money` — только по явному разрешению (`max_effect="money"`);
  · всё обратимое, что проба создала, она обязана вернуть (`cleanup`) —
    проба не вправе оставлять за собой мусор;
  · необратимый расход (бронь слота) честно перечисляется в `spent`, а не
    замалчивается: измерение commit-глагола стоит ресурса, и это нужно видеть.

Что проба НЕ умеет и почему это написано здесь, а не замолчано
──────────────────────────────────────────────────────────────
Чтобы вызвать глагол, нужны входные данные, а манифест объявляет только их
ТИПЫ. Выдумать `hold_id` нельзя — поэтому проба добывает значения из ответов
других глаголов (дешёвых — первыми, §4.2) и честно помечает `skipped` те
глаголы, для которых входа не нашлось. Пропущенный глагол не попадает ни в
`passed`, ни в `total`: считать его провалом значило бы обвинить сервис в
собственном незнании.

Единственная догадка об именах, которую проба себе позволяет: в списке ресурс
зовётся `id`, а во входе глагола — `<ресурс>_id`. Эта связка объявлена здесь
явно (`_lookup`), а не размазана по коду.

Массив во входе — отдельный случай, выясненный на живом уровне 1 daten2.
Пустой список, которым проба заполняла `items`, магазин законно отвергал
(`400 name/items required`), а проба записывала отказ ему в несоответствие
контракту: измеренные 2/3 против заявленных 22/22, то есть ЛОЖНОЕ обвинение в
приукрашивании. Неспособность пробы собрать вход не должна превращаться в
дефект сервиса. Поэтому форма позиции читается из самой спецификации
(`array of {product_id, quantity}` → `_element_keys`), а значения для её полей
добываются теми же правилами, что и для верхнего уровня: ручка — только
наблюдением, количество — по единственной предметной догадке модуля
(`QTY_KEYS`), остальное — заглушкой.

Три правила, которые не дают пробе отчитываться о том, чего она не проверяла
─────────────────────────────────────────────────────────────────────────────
  1. Склад «проверен» — только по отказу 4xx с JSON-сообщением о складе и без
     признаков сбоя (stock_verdict). 5xx и нечитаемое тело — «не проверено»:
     падение базы не является решением склада.
  2. 404 на путь с параметром — «маршрута нет» только по идентификатору, который
     сам сервис выдал под тем же именем; иначе — «не выяснено» (_route_verdict).
     Нерешённый маршрут не входит ни в пройденные, ни в проваленные.
  3. Заявление о контракте сравнивается с измерением только в одних единицах
     (глаголы). Иначе вердикт «несопоставимо», а не «совпало» (compare).

Запуск:
    python3 -m act.npp_act.prober --manifest act/manifests/venue.act.json \\
            --base-url http://127.0.0.1:8210 [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .manifest import EFFECTS, Capability, Manifest, load_manifest, parse_manifest
from .profile import LevelProfile

#: Имена проб. Строками — они уезжают в JSON и в отчёт человеку.
CONTRACT, STOCK, CONCURRENCY, IDEMPOTENCY, LATENCY = (
    "contract", "stock", "concurrency", "idempotency", "latency",
)
PROBES = (LATENCY, CONCURRENCY, CONTRACT, IDEMPOTENCY, STOCK)

#: Направление расхождения. Различать обязательно: скромность безвредна,
#: приукрашивание — это то, из-за чего агент выберет негодный сервис.
#: `incomparable` — заявление и измерение выражены в РАЗНЫХ единицах (§10.1):
#: доли несопоставимы, поэтому ни совпадением, ни расхождением это не является.
EMBELLISHED, MODEST, UNVERIFIABLE, INCOMPARABLE = (
    "embellished", "modest", "unverifiable", "incomparable",
)

#: Что 404/405/501 говорит о маршруте глагола (см. Prober._route_verdict).
#: «Не выяснено» — отдельный исход: ни «маршрут есть», ни «маршрута нет».
ROUTE_MISSING, ROUTE_UNRESOLVED = "missing", "unresolved"

#: Слова складского отказа в тексте сообщения (без учёта регистра, по основе:
#: «остат» покрывает «остаток», «остатка», «остатков»).
STOCK_WORDS = ("остат", "склад", "stock", "недостаточно",
               "insufficient", "not enough", "out of stock")

#: Слова сбоя сервиса в теле ответа. Если они есть, отказ НЕ доказывает проверку
#: склада, даже когда в том же теле стоят складские слова: «stock >= 0» внутри
#: трассировки — это падение базы, а не решение склада.
FAILURE_WORDS = ("traceback", "exception", "checkviolation", "constraint", "internal")

_PATH_PARAM_RE = re.compile(r"\{([^{}]+)\}")

#: Суффиксы, по которым видно, что значение — РУЧКА ресурса, а не данные.
#: Такое значение нельзя выдумать: выдуманный токен даст 404 и обвинит сервис
#: в чужой ошибке. Поэтому глагол с незаполненной ручкой пропускается.
HANDLE_SUFFIXES = ("_id", "_token", "_number", "_key", "_ref")

#: Ключи, которые меняются сами по себе и потому не годятся для сравнения двух
#: ответов на один и тот же ключ идемпотентности.
VOLATILE_KEYS = frozenset({
    "ts", "now", "created_at", "updated_at", "expires_at", "valid_until",
    "accepted_at", "measured_at", "ttl_s", "idempotent_replay",
})

#: Как называется количество в заказе и как — позиция каталога.
#: Это и есть вся «предметная» догадка складской пробы.
QTY_KEYS = ("quantity", "qty", "count", "units", "amount", "hours")
ITEM_KEYS = ("items", "lines", "positions")

#: Заведомо недостижимое количество: если такой заказ приняли, остаток не читают.
ABSURD_QUANTITY = 1_000_000

_SYNTH_TEXT = "проба NPP-Act"

_BASE_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class ProbeError(RuntimeError):
    """Пробу не удалось провести: сервис недоступен или манифест непригоден."""


# ────────────────────────────────────────────────────────────────────────────
# Результаты
# ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProbeResult:
    """Исход одной пробы.

    `applicable=False` — это НЕ провал: у сервиса, продающего время, нет склада,
    и выдать по этому поводу вердикт было бы ложью. Неприменимость обязана
    отличаться от отрицательного результата, иначе отчёт врёт в обе стороны.

    `applicable=True, ok=None` — проба проведена, но вердикт установить нельзя:
    например, сервис ответил 500 вместо отказа по складу. Это «не проверено»,
    а не «нет» и не «да»: отказ сервиса сам по себе ещё не доказательство.
    """

    name: str
    applicable: bool
    ok: bool | None
    evidence: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"probe": self.name, "applicable": self.applicable,
                "ok": self.ok, "evidence": self.evidence, "data": self.data}


@dataclass(frozen=True)
class Feature:
    """Один измеренный признак профиля.

    `evidence` обязателен и содержит НАБЛЮДЕНИЕ, а не пересказ значения:
    «заказ 1000000 шт. принят с HTTP 201» вместо «склад не проверяется».
    Признак без наблюдения — такое же заявление, как поле в манифесте, и
    смысла в этом модуле тогда не было бы.
    """

    name: str
    value: Any
    evidence: str
    probe: str

    def to_json(self) -> dict[str, Any]:
        return {"value": self.value, "evidence": self.evidence, "probe": self.probe}


@dataclass(frozen=True)
class MeasuredProfile:
    """Профиль, собранный из наблюдений за живым сервисом."""

    service: str
    base_url: str
    service_profile: str
    measured_at: str
    features: dict[str, Feature]
    probes: tuple[ProbeResult, ...]
    declared_idempotent_verbs: frozenset[str] = frozenset()
    spent: tuple[str, ...] = ()
    calls: int = 0

    # ---------- доступ ----------

    def feature(self, name: str) -> Feature | None:
        return self.features.get(name)

    def value(self, name: str, default: Any = None) -> Any:
        f = self.features.get(name)
        return default if f is None else f.value

    def probe(self, name: str) -> ProbeResult | None:
        for p in self.probes:
            if p.name == name:
                return p
        return None

    @property
    def conformance(self) -> tuple[int, int]:
        passed, total = self.value("contract_conformance", (0, 0))
        return int(passed), int(total)

    @property
    def conformance_ratio(self) -> float:
        passed, total = self.conformance
        return (passed / total) if total else 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "base_url": self.base_url,
            "service_profile": self.service_profile,
            "measured_at": self.measured_at,
            "calls": self.calls,
            "spent": list(self.spent),
            "declared_idempotent_verbs": sorted(self.declared_idempotent_verbs),
            "features": {k: v.to_json() for k, v in sorted(self.features.items())},
            "probes": [p.to_json() for p in self.probes],
        }

    def describe(self) -> str:
        passed, total = self.conformance
        lines = [f"{self.service} @ {self.base_url} — измерено {self.measured_at}",
                 f"  контракт: {passed}/{total} глаголов ответили по своей же схеме"]
        unresolved = self.value("unresolved_verbs", []) or []
        if unresolved:
            # Такие глаголы НЕ входят в итог выше: показываем, что их не хватает.
            lines.append("  маршрут НЕ ВЫЯСНЕН (в итог не входит): " + ", ".join(unresolved))
        for name in sorted(self.features):
            f = self.features[name]
            lines.append(f"  {name} = {f.value!r}  [{f.probe}] {f.evidence}")
        if self.spent:
            lines.append("  израсходовано безвозвратно: " + "; ".join(self.spent))
        return "\n".join(lines)


@dataclass(frozen=True)
class Discrepancy:
    """Расхождение заявленного с измеренным.

    Направление — главное поле. «Заявил хуже, чем есть» (`modest`) означает
    лишь упущенную выгоду: такой сервис проиграет конкурс, который мог бы
    выиграть. «Заявил лучше, чем есть» (`embellished`) означает, что агент
    выберет его под требование, которого сервис не держит, и узнает об этом
    после необратимого обязательства. Это разные по цене события, и сводить их
    в одно «несовпадение» нельзя.
    """

    field: str
    declared: Any
    measured: Any
    direction: str
    severity: str
    detail: str
    evidence: str = ""

    @property
    def worse_than_declared(self) -> bool:
        return self.direction == EMBELLISHED

    def to_json(self) -> dict[str, Any]:
        return {"field": self.field, "declared": self.declared, "measured": self.measured,
                "direction": self.direction, "severity": self.severity,
                "detail": self.detail, "evidence": self.evidence}

    def human(self) -> str:
        mark = {EMBELLISHED: "приукрашено", MODEST: "скромность",
                UNVERIFIABLE: "не проверяемо", INCOMPARABLE: "несопоставимо"}[self.direction]
        return (f"[{self.severity}/{mark}] {self.field}: "
                f"заявлено {self.declared!r}, измерено {self.measured!r} — {self.detail}")


# ────────────────────────────────────────────────────────────────────────────
# Сверка формы ответа с объявленной output-схемой
# ────────────────────────────────────────────────────────────────────────────

def _spec_base(spec: Any) -> tuple[str, bool]:
    """('string', optional) из 'string?'. 'array of slot' → ('array', False)."""
    if not isinstance(spec, str):
        return "object", True
    text = spec.strip()
    optional = text.endswith("?")
    if optional:
        text = text[:-1]
    return text.split()[0].lower() if text else "object", optional


def _type_ok(base: str, value: Any) -> bool:
    expected = _BASE_TYPES.get(base)
    if expected is None:
        return True  # тип, которого схема не формализует, — не повод обвинять сервис
    if base in ("integer", "number") and isinstance(value, bool):
        return False  # bool — подтип int в Python, но не число в контракте
    return isinstance(value, expected)


def check_shape(declared: dict[str, Any], body: Any) -> tuple[bool, list[str]]:
    """Совпадает ли ответ с объявленной output-схемой → (да/нет, претензии).

    Два решения, объясняющих поведение:

    1. Пустой ключ `""` означает, что схема описывает ТЕЛО ЦЕЛИКОМ
       (`{"": "array of slot"}` — ответ сам является массивом). Без этого
       правила каталоги daten2, отдающие массив, а не конверт, считались бы
       нарушителями.
    2. Лишние поля в ответе — НЕ нарушение. Манифест объявляет минимум
       контракта; сервис вправе отдать больше. Иначе любое расширение ответа
       ломало бы совместимость, и сервисы перестали бы её объявлять.
    """
    if not declared:
        return True, []
    if "" in declared:
        base, _ = _spec_base(declared[""])
        if _type_ok(base, body):
            return True, []
        return False, [f"тело целиком должно быть '{base}', получено {type(body).__name__}"]

    if not isinstance(body, dict):
        return False, [f"ожидался объект с полями {sorted(declared)}, "
                       f"получено {type(body).__name__}"]

    problems: list[str] = []
    for key, spec in declared.items():
        base, optional = _spec_base(spec)
        if key not in body:
            if not optional:
                problems.append(f"нет объявленного поля '{key}'")
            continue
        if body[key] is None:
            if not optional:
                problems.append(f"поле '{key}' пришло пустым (null) при обязательном '{base}'")
            continue
        if not _type_ok(base, body[key]):
            problems.append(f"поле '{key}': объявлено '{base}', "
                            f"получено {type(body[key]).__name__}")
    return (not problems), problems


# ────────────────────────────────────────────────────────────────────────────
# Проба
# ────────────────────────────────────────────────────────────────────────────

def _is_handle(key: str) -> bool:
    return key.endswith(HANDLE_SUFFIXES)


def _path_params(cap: Capability) -> tuple[str, ...]:
    """Имена параметров пути глагола: `/api/orders/{order_number}` → ('order_number',)."""
    return tuple(_PATH_PARAM_RE.findall(str(cap.binding.get("path", ""))))


def _element_keys(spec: Any) -> tuple[str, ...]:
    """Имена полей элемента из спецификации вида `array of {product_id, quantity}`.

    Зачем это нужно и почему это НЕ домысел о предметной области. Массив во
    входе глагола проба раньше заполняла пустым списком — и живой уровень 1
    daten2 законно отвечал `400 name/items required`. Проба записывала это
    себе в зачёт как «глагол не ответил по своей схеме» и обвиняла сервис в
    приукрашивании соответствия контракту (измерено 2/3 против заявленных
    22/22). Обвинение было ложным: сервис исполнял контракт, а собрать заказ
    не умела проба.

    Форму позиции объявляет сам манифест — строкой `array of {a, b}`. Читать
    её и значит верить манифесту в том, что он ОБЪЯВЛЯЕТ, продолжая не верить
    ему в том, что он УТВЕРЖДАЕТ о своём поведении. Выдумывания здесь нет:
    имена полей взяты из манифеста, а значения для них добываются ровно по тем
    же правилам, что и для полей верхнего уровня (ручку — только наблюдением).
    """
    if not isinstance(spec, str):
        return ()
    body = spec.strip().rstrip("?")
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        return ()
    names = [part.strip() for part in body[start + 1:end].split(",")]
    return tuple(name for name in names if name)


def _fresh_key(cap: Capability, prefix: str = "probe") -> str | None:
    """Новый ключ идемпотентности для глагола, который его объявил."""
    if cap.idempotency_slot() is None:
        return None
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _percentile(values: list[float], share: float) -> float:
    """Перцентиль по ближайшему рангу: без интерполяции и без numpy.

    На семи измерениях интерполяция всё равно иллюзия точности, а зависимость
    модуля от сторонней библиотеки — настоящая цена.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(share * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def _decode_body(raw: str) -> tuple[Any, bool]:
    """Тело ответа → (разобранное, было ли оно JSON).

    Пустое тело — не JSON. Непарсящееся тело отдаётся строкой и НЕ роняет пробу:
    раньше 2xx с HTML-страницей бросал JSONDecodeError прямо из пробы.
    """
    if not raw.strip():
        return None, False
    try:
        return json.loads(raw), True
    except json.JSONDecodeError:
        return raw, False


def _message_text(body: Any) -> str:
    """Строковые значения тела, склеенные в текст сообщения. Ключи — не сообщение."""
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return " ".join(_message_text(v) for v in body.values())
    if isinstance(body, list):
        return " ".join(_message_text(v) for v in body)
    return ""


def stock_verdict(status: int, body: Any, is_json: bool) -> tuple[bool | None, str]:
    """Что ответ сервиса на завышенный заказ говорит о складе → (вердикт, наблюдение).

    Вердикт `True` («склад проверяется») выдаётся ТОЛЬКО когда сходятся три
    условия сразу:

      (а) статус 4xx: сервис ОТКАЗАЛ, а не упал и не принял заказ;
      (б) тело — JSON-объект, и его строковые значения называют складскую
          причину (см. STOCK_WORDS);
      (в) в теле нет признаков сбоя (см. FAILURE_WORDS): отказ по существу не
          выглядит падением базы.

    `False` («остаток не читается») — 2xx: заказ принят.

    Во всех остальных случаях — `None` («не проверено»), причина названа в
    наблюдении. Вердикт «не проверено» допустим; вердикт «проверено» без
    доказательства — нет.

    Почему 5xx никогда не считается проверкой, какие бы слова ни были в теле:
    падение базы выглядит как отказ, но о складе не говорит ничего. Измерено на
    daten2: L3, L5, L7 отвечали 500 или 400 CheckViolation ПОСЛЕ записи строк
    заказа. Инструмент тогда записал бы stock_checked=true — а проверки не было,
    и частичная запись осталась.
    """
    if 200 <= status < 300:
        return False, "ПРИНЯТ, значит остаток не читается"
    # Наблюдение ниже уже стоит после «HTTP N» в evidence пробы, поэтому статус
    # в нём не повторяем.
    if not 400 <= status < 500:
        return None, ("сбой или отсутствие ответа, а не отказ по существу: "
                      "склад НЕ ПРОВЕРЕН")
    if not (is_json and isinstance(body, dict)):
        return None, ("тело не JSON-объект: сообщения не разобрать, склад НЕ ПРОВЕРЕН")
    dumped = json.dumps(body, ensure_ascii=False).lower()
    failures = [w for w in FAILURE_WORDS if w in dumped]
    if failures:
        return None, (f"в теле признаки сбоя ({', '.join(failures)}): склад НЕ ПРОВЕРЕН")
    text = _message_text(body)
    if any(w in text.lower() for w in STOCK_WORDS):
        return True, f"отказ по складу: «{text[:120]}»"
    return None, "сообщение не о складе: склад НЕ ПРОВЕРЕН"


class Prober:
    """Набор живых проб против работающего сервиса по его манифесту."""

    def __init__(
        self,
        manifest: Manifest,
        base_url: str | None = None,
        timeout: float = 5.0,
        max_effect: str = "commit",
        max_calls: int = 300,
    ) -> None:
        if max_effect not in EFFECTS:
            raise ProbeError(f"max_effect должен быть одним из {EFFECTS}")
        if max_effect == "destroy":
            # §10.4: губернатор неотключаем для destroy. Проба тем более не
            # вправе уничтожать чужое состояние, чтобы «проверить поведение».
            raise ProbeError("пробовать effect='destroy' запрещено: "
                             "измерение не оправдывает необратимого уничтожения")
        self.manifest = manifest
        self.base_url = (base_url or manifest.base_url).rstrip("/")
        self.timeout = timeout
        self.max_severity = EFFECTS.index(max_effect)
        self.max_calls = max_calls

        self.calls = 0
        self.spent: list[str] = []          # необратимо израсходованное
        self._fresh: dict[str, Any] = {}    # наблюдённые живые значения
        self._listings: dict[str, list] = {}
        self._outstanding: list[tuple[str, dict[str, Any]]] = []  # (обратный глагол, вход)
        self._reads_dirty = True            # нужно ли перечитать каталоги
        self._depth = 0
        self._failures = 0                  # сколько вызовов не дошло вовсе
        self.sweeps: list[dict[str, Any]] = []  # все уборки за собой
        self.leaked: list[str] = []          # что вернуть не удалось вовсе
        self._lock = threading.Lock()

    # ---------- отбор глаголов ----------

    def _allowed(self) -> list[Capability]:
        """Глаголы, которые проба вправе вызывать, по возрастанию тяжести (§4.1)."""
        caps = [c for c in self.manifest if c.severity <= self.max_severity]
        return sorted(caps, key=lambda c: (c.severity, c.id))

    def _reads(self) -> list[Capability]:
        return [c for c in self._allowed() if c.effect == "read"]

    def _reverses(self) -> frozenset[str]:
        """Глаголы, которые являются чьим-то обратным.

        Нужны отдельно по той же причине, по которой §5.1.4 ограничивает
        жёсткий предикат одними обязательствами: `slot.release` формально
        необратим («отменить отмену» нельзя), но он не расходует мир, а
        возвращает его в прежнее состояние. Записать его в `spent` значило бы
        объявить уборку за собой ущербом.
        """
        return frozenset(c.reverse for c in self.manifest if c.reverse)

    # ---------- HTTP ----------

    def _http(self, method: str, url: str, body: dict | None,
              headers: dict[str, str]) -> tuple[int, Any, float, bool]:
        """Один HTTP-вызов → (статус, тело, мс, тело_было_JSON).

        Флаг отдельно от тела нужен потому, что нечитаемое тело ошибки
        оборачивается в {"error": ...} — так удобно для отчёта, но выдавать такую
        обёртку за JSON-объект нельзя: складской вердикт опирается на форму тела.
        """
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                ms = (time.perf_counter() - started) * 1000
                parsed, is_json = _decode_body(raw)
                return resp.status, parsed, ms, is_json
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            ms = (time.perf_counter() - started) * 1000
            parsed, is_json = _decode_body(raw)
            if not is_json:
                parsed = {"error": raw[:200]}
            return e.code, parsed, ms, is_json
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            ms = (time.perf_counter() - started) * 1000
            # status=0 означает «сервис не ответил вовсе» — это не 5xx сервиса,
            # и смешивать два разных события в одно нельзя.
            return 0, {"error": f"не ответил: {e}"}, ms, False

    def _invoke(self, cap: Capability, payload: dict[str, Any],
                idem_key: str | None = None, track: bool = True) -> tuple[int, Any, float]:
        """Один живой вызов глагола без признака формы тела (см. _invoke_full)."""
        status, parsed, ms, _ = self._invoke_full(cap, payload, idem_key=idem_key, track=track)
        return status, parsed, ms

    def _invoke_full(self, cap: Capability, payload: dict[str, Any],
                     idem_key: str | None = None,
                     track: bool = True) -> tuple[int, Any, float, bool]:
        """Единственное место, где проба трогает сеть → (статус, тело, мс, тело_JSON)."""
        with self._lock:
            if self.calls >= self.max_calls:
                raise ProbeError(f"исчерпан лимит вызовов ({self.max_calls}): "
                                 f"проба обязана быть конечной")
            self.calls += 1

        path = cap.binding["path"]
        body: dict[str, Any] = dict(payload)
        for key in list(body):
            token = "{" + key + "}"
            if token in path:
                path = path.replace(token, urllib.parse.quote(str(body.pop(key)), safe=""))
        if "{" in path:
            return 0, {"error": f"незаполненный path-параметр в '{path}'"}, 0.0, False

        headers = {"Accept": "application/json"}
        slot = cap.idempotency_slot()
        if slot and idem_key:
            kind, name = slot
            if kind == "header":
                headers[name] = idem_key
            else:
                body[name] = idem_key

        method = cap.binding["method"]
        url = self.base_url + path
        send: dict | None = None
        if method in ("POST", "PUT", "PATCH"):
            send = body
            headers["Content-Type"] = "application/json"
        elif body:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in body.items() if not isinstance(v, (dict, list))}
            )

        status, parsed, ms, is_json = self._http(method, url, send, headers)
        if status == 0:
            self._failures += 1
        if track:
            self._after(cap, payload, status, parsed)
        return status, parsed, ms, is_json

    # ---------- учёт наблюдений ----------

    def _after(self, cap: Capability, payload: dict[str, Any],
               status: int, body: Any) -> None:
        if 200 <= status < 300:
            self._harvest(body)
        if cap.effect != "read":
            # Любой нечитающий глагол ИЗРАСХОДОВАЛ то, что получил на вход:
            # удержанный слот больше не свободен, отпущенное удержание больше
            # не действует. Правило намеренно грубое — лишний раз перечитать
            # каталог дешевле, чем послать вызов с просроченной ручкой.
            #
            # Забываем ПОСЛЕ сбора наблюдений, а не до: обратный глагол
            # возвращает в ответе ту самую ручку, которую только что погасил
            # (`{"released": true, "hold_id": "hold_…"}`). Сбор после забывания
            # вернул бы мёртвый токен в живые, и следующий `commit` получил бы
            # «удержание уже отпущено» — ровно это и случилось на живом сервисе.
            self._forget(payload)
            self._reads_dirty = True
            if 200 <= status < 300:
                self._remember_reverse(cap, payload, body)
                if cap.is_committing and not cap.reversible and cap.id not in self._reverses():
                    self._spend(cap, body)

    def _forget(self, payload: dict[str, Any]) -> None:
        for key in payload:
            self._fresh.pop(key, None)
            if key.endswith("_id"):
                self._fresh.pop("id", None)

    def _harvest(self, body: Any) -> None:
        """Запомнить живые значения из ответа — только скаляры.

        Вложенные объекты не разбираются сознательно: угадывать, что `order.id`
        подойдёт на вход `order_id`, — путь к вызовам с чужими ручками.
        """
        if isinstance(body, dict):
            for key, value in body.items():
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    self._fresh[key] = value
        elif isinstance(body, list) and body:
            if isinstance(body[0], dict):
                self._listings[json.dumps(sorted(body[0]), ensure_ascii=False)] = body
                self._harvest(body[0])

    def _remember_reverse(self, cap: Capability, payload: dict[str, Any], body: Any) -> None:
        """Записать, что именно придётся вернуть на место (§4.2)."""
        if not (cap.reversible and cap.reverse):
            return
        rev = self.manifest.verb(cap.reverse)
        if rev is None or rev.severity > self.max_severity:
            return
        known: dict[str, Any] = dict(payload)
        if isinstance(body, dict):
            known.update({k: v for k, v in body.items() if isinstance(v, (str, int, float))})
        need = {k: known[k] for k in rev.input if k in known}
        missing = [k for k, spec in rev.input.items()
                   if k not in need and not _spec_base(spec)[1]]
        if missing:
            return
        self._outstanding.append((rev.id, need))

    def _spend(self, cap: Capability, body: Any) -> None:
        handle = ""
        if isinstance(body, dict):
            for key, value in body.items():
                if _is_handle(key):
                    handle = f" ({key}={value})"
                    break
        self.spent.append(f"{cap.id}{handle} — глагол необратим, вернуть нечем")

    # ---------- добывание входных данных ----------

    def _issued(self) -> frozenset[str]:
        """Ручки, которые сервис САМ выдаёт: все ключи из объявленных output."""
        return frozenset(k for cap in self.manifest for k in (cap.output or {}) if k)

    def _lookup(self, key: str) -> Any:
        """Живое значение под входной ключ.

        Единственная догадка об именах во всём модуле: в списке ресурс зовётся
        `id`, а во входе глагола — `<ресурс>_id`. Связка объявлена здесь, одним
        местом, и её видно в отчёте — а не размазана по коду как магия.

        И у догадки есть жёсткая граница: если ручку ВЫДАЁТ какой-то глагол
        (ключ встречается в чьём-то `output`), подставлять вместо неё `id` из
        каталога запрещено. Иначе `hold_id` получит значение `1` — номер слота
        вместо номера удержания, то есть личность одного ресурса вместо
        другого. Живой сервис на это ответил `400`, и правильно ответил:
        единственный честный способ получить такую ручку — вызвать тот глагол,
        который её выдаёт.
        """
        if key in self._fresh:
            return self._fresh[key]
        if key.endswith("_id") and "id" in self._fresh and key not in self._issued():
            return self._fresh["id"]
        return None

    def _refresh_reads(self, exclude: str = "") -> None:
        """Перечитать все каталоги: самый дешёвый способ добыть живые ручки.

        Вход здесь собирается БЕЗ рекурсивного добывания (`ensure=False`) —
        иначе чтение, которому нужна ручка, попросило бы перечитать каталоги,
        и обновление вызвало бы само себя. Читающий глагол, которому ручки не
        хватает, в обновлении просто не участвует: он и не каталог.
        """
        self._reads_dirty = False
        for cap in self._reads():
            if cap.id == exclude:
                continue
            payload, missing = self._synth(cap, allow_severity=0, ensure=False)
            if missing:
                continue
            try:
                self._invoke(cap, payload)
            except ProbeError:
                return

    def _ensure(self, key: str, allow_severity: int, exclude: str = "") -> Any:
        """Добыть значение под `key`, не превышая разрешённой тяжести.

        Порядок строго по §4.2: сначала бесплатные чтения, и только если они не
        дали ручку — глагол, который её выдаёт. Производителя тяжелее, чем
        пробуемый глагол, не вызываем: создавать обязательство ради проверки
        ЧТЕНИЯ — не измерение, а порча чужого состояния.

        Глубина ограничена жёстко: цепочка «глагол ← производитель ←
        производитель производителя» длиннее двух звеньев означает, что проба
        начала домысливать сценарий, а не измерять сервис.
        """
        if self._depth >= 2:
            return self._lookup(key)
        self._depth += 1
        try:
            value = self._lookup(key)
            if value is not None:
                return value

            self._refresh_reads(exclude=exclude)
            value = self._lookup(key)
            if value is not None:
                return value

            producers = [c for c in self._allowed()
                         if c.severity > 0 and c.severity <= allow_severity
                         and c.id != exclude and key in (c.output or {})]
            for cap in sorted(producers, key=lambda c: (c.severity, c.id)):
                payload, missing = self._synth(cap, allow_severity=cap.severity,
                                               exclude=exclude or cap.id)
                if missing:
                    continue
                try:
                    # Производителю ключ идемпотентности нужен так же, как и
                    # пробуемому глаголу: без него сервис, объявивший ключ,
                    # законно отвечает 400, и проба решит, что ручку получить
                    # нельзя, — хотя не выполнила его же условие.
                    self._invoke(cap, payload, idem_key=_fresh_key(cap))
                except ProbeError:
                    break
                value = self._lookup(key)
                if value is not None:
                    return value
            return None
        finally:
            self._depth -= 1

    def _synth(self, cap: Capability, allow_severity: int,
               ensure: bool = True, exclude: str = "") -> tuple[dict[str, Any], list[str]]:
        """Вход для глагола → (payload, недостающие ключи).

        Необязательные поля не заполняются ВОВСЕ, даже когда подходящее живое
        значение под рукой. Два повода, и оба выяснились на живом сервисе:

          1. Это проверяет, что сервис действительно считает их
             необязательными, — то есть сверяет манифест с поведением, а не
             подыгрывает ему.
          2. Необязательные параметры чтения — это, как правило, ФИЛЬТРЫ.
             Подставив в `/api/slots` подсмотренные `day` и `specialist`,
             проба сузила каталог до одного дня и потом объявила, что
             параллель измерять не на чем. Фильтр, взятый из предыдущего
             ответа, превращает пробу в разговор с собственным эхом.

        Массив с объявленной формой элемента (`array of {product_id, quantity}`)
        заполняется ОДНОЙ позицией, а не пустым списком: пустой заказ — это не
        заказ, и сервис, отвергнувший его, прав. Одна позиция, а не несколько,
        потому что контракт проверяется формой ответа, а не объёмом заказа.
        """
        payload: dict[str, Any] = {}
        missing: list[str] = []
        path = cap.binding.get("path", "")
        for key, spec in (cap.input or {}).items():
            if not key:
                continue
            base, optional = _spec_base(spec)
            in_path = ("{" + key + "}") in path
            if optional and not in_path:
                continue
            element = _element_keys(spec) if base == "array" else ()
            if element:
                line, lost = self._synth_element(element, allow_severity, ensure,
                                                 exclude or cap.id)
                if lost:
                    # Недостающую ручку внутри позиции называем вместе с путём
                    # до неё: «order.create пропущен из-за items» непонятно,
                    # «items[].product_id» показывает, чего именно не хватило.
                    missing.extend(f"{key}[].{name}" for name in lost)
                    continue
                payload[key] = [line]
                continue
            value = self._lookup(key)
            if value is None and ensure:
                value = self._ensure(key, allow_severity, exclude=exclude or cap.id)
            if value is None:
                if _is_handle(key):
                    # Ручку выдумывать нельзя: 404 на выдуманный токен —
                    # ошибка пробы, а не сервиса.
                    missing.append(key)
                    continue
                value = {"string": _SYNTH_TEXT, "integer": 1, "number": 1,
                         "boolean": False, "array": [], "object": {}}.get(base, _SYNTH_TEXT)
            payload[key] = value
        return payload, missing

    def _synth_element(self, keys: tuple[str, ...], allow_severity: int,
                       ensure: bool, exclude: str) -> tuple[dict[str, Any], list[str]]:
        """Одна позиция массива по объявленной форме элемента.

        Типов полей элемента манифест не объявляет — только имена. Поэтому
        порядок добывания значения такой, и каждая ступень объяснима:

          1. живое наблюдённое значение под этим именем (`product_id` →
             `id` из каталога) — единственный честный источник ручки;
          2. ручка, которую наблюсти не удалось, делает позицию несобираемой:
             выдуманный `product_id` дал бы 404, то есть обвинил сервис в
             ошибке пробы;
          3. поле количества (`QTY_KEYS` — та самая единственная предметная
             догадка модуля, объявленная вверху файла и здесь не умножаемая) → 1;
          4. всё остальное — та же текстовая заглушка, что и у скаляра.
        """
        line: dict[str, Any] = {}
        lost: list[str] = []
        for key in keys:
            value = self._lookup(key)
            if value is None and ensure:
                value = self._ensure(key, allow_severity, exclude=exclude)
            if value is None:
                if _is_handle(key):
                    lost.append(key)
                    continue
                value = 1 if key in QTY_KEYS else _SYNTH_TEXT
            line[key] = value
        return line, lost

    # ---------- уборка ----------

    def cleanup(self) -> dict[str, Any]:
        """Вернуть на место всё обратимое, что проба создала.

        Проба, оставившая висеть удержания, портит замеры всем следующим и
        делает сервис непригодным к повторному измерению. Поэтому уборка —
        часть пробы, а не вежливость: `concurrency_probe` без неё просто
        съела бы все свободные слоты.
        """
        released, failed = 0, []
        while self._outstanding:
            verb_id, payload = self._outstanding.pop()
            cap = self.manifest.verb(verb_id)
            if cap is None:
                failed.append(f"{verb_id}: нет в манифесте")
                continue
            try:
                status, body, _ = self._invoke(cap, payload, track=False)
            except ProbeError as e:
                failed.append(f"{verb_id}: {e}")
                continue
            if 200 <= status < 300:
                released += 1
                # Отпущенную ручку обязательно забыть. Иначе следующая проба
                # возьмёт её из наблюдённых и получит «удержание уже отпущено»,
                # то есть обвинит сервис в собственной уборке. Именно так
                # `booking.create` однажды получил 409 на живом сервисе.
                self._forget(payload)
            else:
                failed.append(f"{verb_id}({payload}) → HTTP {status}")
        self._reads_dirty = True
        sweep = {"released": released, "failed": failed, "clean": not failed}
        self.sweeps.append(sweep)
        return sweep

    # ---------- проба 1: контракт ----------

    def _route_verdict(self, cap: Capability, payload: dict[str, Any],
                       status: int) -> tuple[str | None, str]:
        """Что код ответа говорит о МАРШРУТЕ глагола → (вердикт, наблюдение).

        Вердикт `None` — код не касается маршрута (сервис ответил, либо не ответил
        вовсе): обычная сверка формы, как и раньше.

        405 и 501 — маршрута под этим методом нет при любом объекте: `missing` всегда.

        404 — самый двусмысленный код: «объекта нет» и «маршрута нет» отвечают им
        одинаково. Поэтому смотрим, ЧЕМ проба адресовалась:

          · путь с параметрами, и КАЖДЫЙ параметр — реальный идентификатор, который
            сам сервис выдал под тем же именем (order_number из ответа order.create)
            → `missing`. Сервис только что сообщил, что объект создан; 404 по его
            же ручке значит, что маршрута чтения нет. Оговорка: проба не отличает
            это от удаления объекта между созданием и чтением. Её собственный
            сценарий (создал → сразу читает) делает удаление маловероятным, но не
            исключает, поэтому граница записана здесь, а не замолчана.
          · путь с параметрами, а хотя бы один параметр — заглушка или чужая ручка
            (`id` вместо `order_id`, подставленная по догадке) → `unresolved`:
            объекта могло не быть, а маршрут — быть. Объявить такой маршрут
            отсутствующим значило бы обвинить сервис в незнании самой пробы.
          · путь без параметров и без входа → `missing` (адрес сам по себе не
            нашёлся, как и раньше). Путь без параметров, но с входом (фильтр) →
            `unresolved`: пустая выборка по фильтру отвечает тем же кодом.
        """
        if status in (405, 501):
            return ROUTE_MISSING, f"HTTP {status}: маршрута под методом {cap.binding.get('method')} нет"
        if status != 404:
            return None, ""
        params = _path_params(cap)
        if not params:
            if not payload:
                return ROUTE_MISSING, "HTTP 404 на путь без параметров и без входа: маршрута нет"
            return ROUTE_UNRESOLVED, ("HTTP 404 на путь без параметров, но с входом: пустая "
                                      "выборка по фильтру дала бы тот же код")
        real = [k for k in params if k in self._fresh and self._fresh[k] == payload.get(k)]
        if len(real) == len(params):
            return ROUTE_MISSING, (f"HTTP 404 по реальному идентификатору, который выдал сам "
                                   f"сервис ({', '.join(params)}): объект существует, значит "
                                   "маршрута чтения нет")
        fake = [k for k in params if k not in real]
        return ROUTE_UNRESOLVED, (f"HTTP 404 без реального идентификатора у {', '.join(fake)} "
                                  "(проба подставила заглушку или чужую ручку): отсутствие "
                                  "объекта и отсутствие маршрута здесь не различить")

    def contract_probe(self) -> ProbeResult:
        """Вызвать каждый объявленный глагол и сверить форму ответа с его схемой.

        Два прохода не для красоты: `booking.get` нельзя проверить, пока брони
        нет, а создавать бронь ради проверки чтения в первом проходе запрещено
        (§4.2 — начинать с обратимого). Поэтому сначала проходим по возрастанию
        тяжести на дешёвых производителях, а во втором проходе возвращаемся к
        пропущенным — к тому времени ручки уже наблюдены законно.

        Маршрут, который проба не смогла выяснить (404 без реального идентификатора),
        не проходит и не проваливается: глагол выведен из итога и назван в
        `unresolved`. Иначе проба, не знающая, есть ли маршрут, выдавала бы
        «не пройдено» без доказательства. См. _route_verdict.
        """
        verbs: dict[str, dict[str, Any]] = {}
        skipped: dict[str, str] = {}
        unresolved: dict[str, dict[str, Any]] = {}
        missing_verbs: list[str] = []

        def run(cap: Capability, allow: int) -> bool:
            payload, missing = self._synth(cap, allow_severity=allow)
            if missing:
                skipped[cap.id] = "нет наблюдённого значения для " + ", ".join(missing)
                return False
            skipped.pop(cap.id, None)
            unresolved.pop(cap.id, None)
            status, body, ms = self._invoke(cap, payload, idem_key=_fresh_key(cap))
            route, route_note = self._route_verdict(cap, payload, status)
            if route == ROUTE_UNRESOLVED:
                verbs.pop(cap.id, None)
                unresolved[cap.id] = {"status": status, "reason": route_note}
                return True
            ok_status = 200 <= status < 300
            shape_ok, problems = check_shape(cap.output or {}, body) if ok_status else (False, [])
            detail = ""
            if not ok_status:
                detail = f"HTTP {status}"
                if isinstance(body, dict) and body.get("error"):
                    detail += f": {str(body['error'])[:120]}"
            elif problems:
                detail = "; ".join(problems)
            if route == ROUTE_MISSING:
                detail = "; ".join(part for part in (detail, route_note) if part)
                missing_verbs.append(cap.id)
            verbs[cap.id] = {"status": status, "ok": ok_status and shape_ok,
                             "shape_ok": shape_ok, "ms": round(ms, 1), "detail": detail,
                             "effect": cap.effect}
            return True

        order = self._allowed()
        for cap in order:
            run(cap, cap.severity)
        for cap in order:
            # Во втором проходе — пропущенные (ручек ещё не было) и нерешённые ЧТЕНИЯ:
            # после создания объектов их ручки могли появиться. Записывающие глаголы
            # повторно не вызываем: повтор создал бы второе обязательство.
            if cap.id in skipped or (cap.id in unresolved and cap.effect == "read"):
                run(cap, self.max_severity)

        passed = sum(1 for v in verbs.values() if v["ok"])
        total = len(verbs)
        declared = len(self.manifest.capabilities)
        called = total + len(unresolved)
        evidence = (
            f"вызвано {called} из {declared} объявленных глаголов; "
            f"{passed} ответили по своей же output-схеме"
        )
        if unresolved:
            evidence += (f"; маршрут НЕ ВЫЯСНЕН у {len(unresolved)} (в итог не входит): " +
                         "; ".join(f"{k}: {v['reason']}" for k, v in sorted(unresolved.items())))
        if skipped:
            evidence += f"; пропущено {len(skipped)} (" + \
                "; ".join(f"{k}: {v}" for k, v in sorted(skipped.items())) + ")"
        if missing_verbs:
            evidence += "; маршрут отсутствует у: " + ", ".join(sorted(set(missing_verbs)))
        # Итог: «да» только если все установленные глаголы прошли и ни один маршрут
        # не остался неясным. Неясный маршрут даёт None: известное совпало, полной
        # картины нет, и «проверено» без доказательства не выдаём.
        verdict: bool | None
        if passed < total or (total == 0 and not unresolved):
            verdict = False
        elif unresolved:
            verdict = None
        else:
            verdict = True
        return ProbeResult(
            CONTRACT, True, verdict, evidence,
            {"passed": passed, "total": total, "declared": declared,
             "verbs": verbs, "skipped": skipped, "unresolved": unresolved,
             "missing_verbs": sorted(set(missing_verbs))},
        )

    # ---------- проба 2: склад ----------

    def _stock_target(self) -> tuple[Capability, str, str] | None:
        """Какой глагол и какое поле изображают «сколько штук».

        Возвращает (глагол, вид, имя поля): вид — 'scalar' (количество прямо во
        входе) или 'items' (позиции заказа). Если ни одного не нашлось, проба
        объявит себя неприменимой, а не выдумает вердикт.
        """
        for cap in self._allowed():
            if not cap.is_committing:
                continue
            for name in QTY_KEYS:
                if name in (cap.input or {}):
                    return cap, "scalar", name
            for name in ITEM_KEYS:
                spec = (cap.input or {}).get(name)
                if spec is not None and _spec_base(spec)[0] == "array":
                    return cap, "items", name
        return None

    def stock_probe(self) -> ProbeResult:
        """Заказать заведомо больше остатка и смотреть, ОТКУДА пришёл ответ.

        Исходы, и только один из них доказывает проверку склада:

          · 2xx — заказ принят: остаток не читается → stock_checked = False;
          · 4xx, тело — JSON-объект, его сообщение называет складскую причину и
            в теле нет признаков сбоя → stock_checked = True (отказ по складу
            НАБЛЮДАЛСЯ);
          · всё прочее — 5xx, отсутствие ответа, 4xx без складского сообщения,
            тело не JSON-объект или с признаками сбоя → stock_checked = None
            («не проверено»), причина названа в наблюдении.

        Вердикт «не проверено» допустим; вердикт «проверено» без доказательства —
        нет. Правила разбора ответа — в stock_verdict, там же почему 5xx не
        считается проверкой.

        Именно эта проба поймала шесть уровней daten2 из семи: контракт-тест
        проверял ФОРМУ ответа и был зелёным, а заказ 99999 роз при остатке 48
        проходил с HTTP 201. Форму ответа можно сверить с моком; инвариант
        предметной области — только с живым сервисом.
        """
        if self.manifest.profile != "vendor":
            return ProbeResult(
                STOCK, False, None,
                f"профиль '{self.manifest.profile}' не торгует штуками: остатка склада "
                f"у него нет, и вердикт о нём был бы выдуман", {},
            )
        target = self._stock_target()
        if target is None:
            return ProbeResult(
                STOCK, False, None,
                "у vendor-сервиса не нашлось обязывающего глагола с количеством "
                f"(искали {list(QTY_KEYS)} и {list(ITEM_KEYS)}): форма заказа "
                "из манифеста не выводится", {},
            )
        cap, kind, field_name = target
        payload, missing = self._synth(cap, allow_severity=self.max_severity)
        if missing:
            return ProbeResult(
                STOCK, False, None,
                f"{cap.id}: нет наблюдённого значения для {', '.join(missing)} — "
                f"заказ не собрать", {"verb": cap.id},
            )

        # Завышаем количество в УЖЕ собранном входе, а не собираем заказ заново
        # своими руками. Прежняя версия подставляла позицию
        # `{"product_id": …, "quantity": …, "qty": …}` — три имени, которых
        # могло не быть в манифесте вовсе, причём два взаимоисключающих сразу,
        # «чтобы хоть одно подошло». Это уже не измерение контракта, а догадка
        # о чужом формате: сервис с другим именем поля ответил бы 400, и проба
        # записала бы свою неудачу ему в дефекты. Имена полей позиции объявлены
        # манифестом (`array of {product_id, quantity}`), оттуда их и берём.
        line: dict[str, Any] = {}
        if kind == "scalar":
            payload[field_name] = ABSURD_QUANTITY
            bumped = field_name
        else:
            lines = payload.get(field_name) or []
            if not lines:
                return ProbeResult(
                    STOCK, False, None,
                    f"{cap.id}: '{field_name}' объявлен массивом без формы элемента — "
                    f"позицию заказа пришлось бы выдумать", {"verb": cap.id},
                )
            line = dict(lines[0])
            qty_fields = [k for k in line if k in QTY_KEYS]
            if not qty_fields:
                return ProbeResult(
                    STOCK, False, None,
                    f"{cap.id}: в объявленной позиции заказа {sorted(line)} нет поля "
                    f"количества (искали {list(QTY_KEYS)}) — завышать нечего",
                    {"verb": cap.id},
                )
            for name in qty_fields:
                line[name] = ABSURD_QUANTITY
            payload[field_name] = [line]
            bumped = f"{field_name}[].{'/'.join(sorted(qty_fields))}"
        status, body, _, is_json = self._invoke_full(cap, payload,
                                                     idem_key=_fresh_key(cap, "stock"))
        verdict, observation = stock_verdict(status, body, is_json)
        evidence = f"{cap.id} с {bumped}={ABSURD_QUANTITY} → HTTP {status}: {observation}"
        return ProbeResult(STOCK, True, verdict, evidence,
                           {"verb": cap.id, "field": field_name, "bumped": bumped,
                            "line": line, "quantity": ABSURD_QUANTITY,
                            "status": status, "accepted": 200 <= status < 300,
                            "verdict_basis": observation})

    # ---------- проба 3: конкурентность ----------

    def _concurrency_target(self) -> tuple[Capability, str] | None:
        """Обратимый глагол и ключ, который будем варьировать."""
        for cap in self._allowed():
            if not (cap.reversible and cap.reverse):
                continue
            for key, spec in (cap.input or {}).items():
                if _is_handle(key) and not _spec_base(spec)[1]:
                    return cap, key
        return None

    def _listed_values(self, key: str) -> list[Any]:
        """Все живые значения под варьируемый ключ — из любого каталога."""
        self._refresh_reads()
        item_key = key if not key.endswith("_id") else "id"
        best: list[Any] = []
        for items in self._listings.values():
            values = [it[key] if key in it else it.get(item_key) for it in items]
            values = [v for v in values if v is not None]
            if len(values) > len(best):
                best = values
        return best

    def _targets(self, key: str, want: int) -> list[Any]:
        """Не меньше двух разных целей под варьируемый ключ, иначе пусто."""
        values = self._listed_values(key)
        return values[:want] if len(values) >= 2 else []

    def concurrency_probe(self, n: int = 6) -> ProbeResult:
        """N одновременных обязательств: держит ли сервис параллель.

        Пробуем ТОЛЬКО обратимым глаголом и за собой убираем — иначе измерение
        конкурентности стоило бы N необратимых обязательств, и повторить его
        было бы нельзя. Измеряются два разных свойства, и смешивать их нельзя:

          · `distinct`  — N удержаний РАЗНЫХ ресурсов. Все обязаны пройти;
                          частичный отказ и есть concurrency_safe=false;
          · `contested` — N удержаний ОДНОГО ресурса. Пройти обязано ровно
                          одно: это взаимное исключение, а не пропускная
                          способность. Два успеха здесь — продали одно дважды.
        """
        target = self._concurrency_target()
        if target is None:
            return ProbeResult(
                CONCURRENCY, False, None,
                "у сервиса нет обратимых глаголов: пробу пришлось бы делать "
                "необратимыми обязательствами, чего проба себе не позволяет", {},
            )
        cap, vary = target
        values = self._targets(vary, n)
        if len(values) < 2:
            return ProbeResult(
                CONCURRENCY, False, None,
                f"свободных целей под '{vary}' меньше двух — параллель измерять не на чем",
                {"verb": cap.id, "vary": vary},
            )
        width = min(n, len(values))
        base_payload, missing = self._synth(cap, allow_severity=cap.severity)
        if missing and missing != [vary]:
            return ProbeResult(
                CONCURRENCY, False, None,
                f"{cap.id}: нет наблюдённого значения для {', '.join(missing)}",
                {"verb": cap.id},
            )

        def burst(payloads: list[dict[str, Any]]) -> dict[str, Any]:
            results: list[tuple[int, Any]] = [(0, None)] * len(payloads)
            start = threading.Barrier(len(payloads))

            def worker(i: int) -> None:
                start.wait(timeout=10)
                try:
                    status, body, _ = self._invoke(cap, payloads[i])
                except ProbeError as e:
                    status, body = 0, {"error": str(e)}
                results[i] = (status, body)

            threads = [threading.Thread(target=worker, args=(i,), daemon=True)
                       for i in range(len(payloads))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            ok = sum(1 for st, _ in results if 200 <= st < 300)
            codes: dict[str, int] = {}
            for st, _ in results:
                codes[str(st)] = codes.get(str(st), 0) + 1
            return {"sent": len(payloads), "ok": ok, "codes": codes}

        used: set[Any] = set()

        # Один ресурс: ожидается ровно один победитель.
        one = [dict(base_payload, **{vary: values[0]}) for _ in range(width)]
        used.add(values[0])
        contested = burst(one)
        first_sweep = self.cleanup()

        # Разные ресурсы: ожидаются все победители.
        values = self._targets(vary, width) or values
        width = min(width, len(values))
        many = [dict(base_payload, **{vary: values[i]}) for i in range(width)]
        used.update(values[:width])
        distinct = burst(many)
        swept = self.cleanup()
        swept = {"released": first_sweep["released"] + swept["released"],
                 "failed": first_sweep["failed"] + swept["failed"]}

        # Что НЕ вернулось на место. Проба обязана это посчитать сама: ручку
        # удержания можно не получить вовсе (сервис обрывает соединение под
        # параллелью) или получить мёртвой (201 с номером, которого в базе
        # нет). Отпустить такое нечем — и ровно поэтому §4.2 требует, чтобы
        # `reserve` истекал сам: самоистечение остаётся последней гарантией,
        # что мир вернётся в прежнее состояние. Умолчать об этом нельзя:
        # следующая проба мерила бы сервис с занятыми ресурсами.
        survivors = set(self._listed_values(vary))
        leaked = sorted(v for v in used if v not in survivors)
        swept["leaked"] = leaked
        swept["clean"] = not swept["failed"] and not leaked
        if leaked:
            self.leaked.extend(f"{cap.id}:{vary}={v}" for v in leaked)

        safe = distinct["ok"] == distinct["sent"]
        exclusive = contested["ok"] == 1
        evidence = (
            f"{cap.id}: {distinct['sent']} одновременных удержаний разных целей → "
            f"{distinct['ok']} успехов {distinct['codes']}; "
            f"{contested['sent']} на одну цель → {contested['ok']} успехов "
            f"{contested['codes']}; убрано {swept['released']} удержаний обратным "
            f"глаголом '{cap.reverse}'"
        )
        if not exclusive:
            evidence += (f"; ВЗАИМНОЕ ИСКЛЮЧЕНИЕ НАРУШЕНО: один ресурс удержан "
                         f"{contested['ok']} раз")
        if swept["failed"]:
            evidence += "; обратный вызов не удался: " + "; ".join(swept["failed"])
        if leaked:
            ttl = cap.expires_s
            evidence += (
                f"; ОСТАЛОСЬ УДЕРЖАННЫМИ {len(leaked)} ({vary}="
                + ", ".join(str(v) for v in leaked) + "): ручка удержания не "
                "получена или мертва, отпустить нечем"
                + (f"; освободятся сами через expires_s={ttl:g}" if ttl else
                   "; глагол не объявил expires_s, и они залипнут навсегда")
            )
        return ProbeResult(
            CONCURRENCY, True, safe, evidence,
            {"verb": cap.id, "vary": vary, "width": distinct["sent"],
             "distinct": distinct, "contested": contested,
             "mutual_exclusion": exclusive, "cleanup": swept},
        )

    # ---------- проба 4: идемпотентность ----------

    def _handles(self, cap: Capability, body: Any) -> dict[str, Any]:
        """Ручки из ответа — то, по чему видно, одно ли это обязательство."""
        if not isinstance(body, dict):
            return {}
        out = {k: v for k, v in body.items() if _is_handle(k)}
        if out:
            return out
        declared = [k for k in (cap.output or {}) if _is_handle(k)]
        return {k: body.get(k) for k in declared if k in body}

    def idempotency_probe(self) -> ProbeResult:
        """Один ключ дважды. Повтор обязан вернуть ТО ЖЕ обязательство (§4.5).

        Различаются три исхода, и это важнее самого вердикта:

          replay     — вернулась та же ручка: идемпотентность работает;
          rejected   — повтор отвергнут (409/400): второго обязательства нет,
                       но и объявленной идемпотентности нет — агент, повторивший
                       вызов после обрыва связи, получит ошибку вместо брони;
          duplicated — повтор создал ВТОРОЕ обязательство. Это и есть та авария,
                       ради которой §4.5 вообще существует.
        """
        targets = [c for c in self._allowed()
                   if c.idempotency_slot() is not None and c.severity > 0]
        if not targets:
            return ProbeResult(
                IDEMPOTENCY, False, None,
                "ни один допущенный глагол не объявляет идемпотентности — "
                "проверять нечего", {},
            )
        verbs: dict[str, dict[str, Any]] = {}
        for cap in targets:
            payload, missing = self._synth(cap, allow_severity=cap.severity)
            if missing:
                verbs[cap.id] = {"verdict": "skipped",
                                 "detail": "нет наблюдённого значения для "
                                           + ", ".join(missing)}
                continue
            key = _fresh_key(cap, "idem")
            # Второй вызов идёт ТЕМ ЖЕ payload: пересобирать вход нельзя, иначе
            # проверялась бы не идемпотентность, а новый вызов с новой ручкой.
            frozen = dict(payload)
            st1, b1, _ = self._invoke(cap, frozen, idem_key=key)
            if not 200 <= st1 < 300:
                verbs[cap.id] = {"verdict": "unknown", "first_status": st1,
                                 "detail": f"первый вызов не прошёл: HTTP {st1}"}
                continue
            st2, b2, _ = self._invoke(cap, dict(frozen), idem_key=key, track=False)
            h1, h2 = self._handles(cap, b1), self._handles(cap, b2)
            if not 200 <= st2 < 300:
                verdict, detail = "rejected", (
                    f"повтор отвергнут HTTP {st2} вместо повторной выдачи "
                    f"({str((b2 or {}).get('error', ''))[:100]})")
            elif h1 and h2 and h1 == h2:
                verdict, detail = "replay", f"повтор вернул ту же ручку {h1}"
            elif h1 and h2:
                verdict, detail = "duplicated", (
                    f"повтор создал ВТОРОЕ обязательство: {h1} и {h2}")
            else:
                a = _strip_volatile(b1)
                b = _strip_volatile(b2)
                verdict = "replay" if a == b else "duplicated"
                detail = ("ручек в ответе нет; тела "
                          + ("совпали" if verdict == "replay" else "разошлись"))
            verbs[cap.id] = {"verdict": verdict, "detail": detail,
                             "first_status": st1, "second_status": st2,
                             "declared": cap.idempotency}
            if verdict in ("duplicated", "rejected") and isinstance(b2, dict):
                self._remember_reverse(cap, frozen, b2)

        checked = {k: v for k, v in verbs.items() if v["verdict"] in
                   ("replay", "rejected", "duplicated")}
        if not checked:
            return ProbeResult(
                IDEMPOTENCY, False, None,
                "ни один объявивший идемпотентность глагол не удалось вызвать: "
                + "; ".join(f"{k}: {v['detail']}" for k, v in sorted(verbs.items())),
                {"verbs": verbs},
            )
        replayed = [k for k, v in checked.items() if v["verdict"] == "replay"]
        doubled = [k for k, v in checked.items() if v["verdict"] == "duplicated"]
        rejected = [k for k, v in checked.items() if v["verdict"] == "rejected"]
        evidence = f"проверено {len(checked)} глаголов с объявленным ключом: " + "; ".join(
            f"{k} — {v['detail']}" for k, v in sorted(checked.items()))
        return ProbeResult(
            IDEMPOTENCY, True, len(replayed) == len(checked), evidence,
            {"verbs": verbs, "replayed": sorted(replayed), "rejected": sorted(rejected),
             "duplicated": sorted(doubled), "double_execution": bool(doubled)},
        )

    # ---------- проба 5: задержка ----------

    def latency_probe(self, repeats: int = 7) -> ProbeResult:
        """p50/p95 на чтении. Читающие глаголы — единственные, которые можно
        повторять сколько угодно, не меняя мир."""
        samples: list[float] = []
        per_verb: dict[str, dict[str, Any]] = {}
        for cap in self._reads():
            payload, missing = self._synth(cap, allow_severity=0)
            if missing:
                continue
            own: list[float] = []
            for _ in range(repeats):
                status, _body, ms = self._invoke(cap, payload)
                if 200 <= status < 300:
                    own.append(ms)
            if own:
                per_verb[cap.id] = {"n": len(own), "p50_ms": round(_percentile(own, 0.5), 1),
                                    "p95_ms": round(_percentile(own, 0.95), 1)}
                samples.extend(own)
        if not samples:
            return ProbeResult(LATENCY, False, None,
                               "ни один читающий глагол не ответил — измерять нечего", {})
        p50 = round(_percentile(samples, 0.5), 1)
        p95 = round(_percentile(samples, 0.95), 1)
        return ProbeResult(
            LATENCY, True, True,
            f"{len(samples)} замеров на {len(per_verb)} читающих глаголах: "
            f"p50={p50} мс, p95={p95} мс",
            {"p50_ms": p50, "p95_ms": p95, "samples": len(samples), "verbs": per_verb},
        )

    # ---------- всё вместе ----------

    def probe_all(self, concurrency: int = 6, repeats: int = 7) -> list[ProbeResult]:
        """Пробы в порядке возрастания цены для сервиса.

        Порядок не произволен: `contract` и `idempotency` расходуют слоты
        необратимо, поэтому конкурентность измеряется ДО них — пока свободных
        целей много. Иначе вердикт о параллели зависел бы от того, сколько
        ресурса сожрали предыдущие пробы.
        """
        results = [
            self.latency_probe(repeats=repeats),
            self.concurrency_probe(n=concurrency),
            self.contract_probe(),
            self.idempotency_probe(),
            self.stock_probe(),
        ]
        self.cleanup()
        if self.calls and self._failures == self.calls:
            raise ProbeError(f"{self.base_url}: ни один из {self.calls} вызовов "
                             f"не дошёл — сервис недоступен")
        return results


def _strip_volatile(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    return {k: v for k, v in body.items() if k not in VOLATILE_KEYS}


# ────────────────────────────────────────────────────────────────────────────
# Сборка измеренного профиля
# ────────────────────────────────────────────────────────────────────────────

def measure(
    manifest: Manifest | str | Path | dict,
    base_url: str | None = None,
    concurrency: int = 6,
    repeats: int = 7,
    max_effect: str = "commit",
    timeout: float = 5.0,
) -> MeasuredProfile:
    """Измерить живой сервис и выдать профиль с наблюдением у каждого признака."""
    if isinstance(manifest, (str, Path)):
        manifest = load_manifest(manifest)
    elif isinstance(manifest, dict):
        manifest = parse_manifest(manifest)

    prober = Prober(manifest, base_url=base_url, max_effect=max_effect, timeout=timeout)
    results = prober.probe_all(concurrency=concurrency, repeats=repeats)
    by_name = {r.name: r for r in results}

    features: dict[str, Feature] = {}

    def put(name: str, value: Any, probe: str, evidence: str) -> None:
        features[name] = Feature(name, value, evidence, probe)

    contract = by_name[CONTRACT]
    put("contract_conformance",
        (contract.data.get("passed", 0), contract.data.get("total", 0)),
        CONTRACT, contract.evidence)
    put("missing_verbs", contract.data.get("missing_verbs", []), CONTRACT,
        contract.evidence)
    # Маршруты, которые проба не смогла выяснить. Их нет ни в missing_verbs
    # (признать отсутствующим нельзя), ни в итоге контракта (проверено не было).
    unresolved = contract.data.get("unresolved", {})
    put("unresolved_verbs", sorted(unresolved), CONTRACT,
        ("маршрут не выяснен у: " + "; ".join(f"{k} ({v['reason']})"
                                               for k, v in sorted(unresolved.items())))
        if unresolved else "не выяснено ни у одного глагола")

    stock = by_name[STOCK]
    put("stock_checked", stock.ok, STOCK, stock.evidence)

    conc = by_name[CONCURRENCY]
    put("concurrency_safe", conc.ok, CONCURRENCY, conc.evidence)
    put("mutual_exclusion", conc.data.get("mutual_exclusion") if conc.applicable else None,
        CONCURRENCY, conc.evidence)

    idem = by_name[IDEMPOTENCY]
    put("idempotent", idem.ok, IDEMPOTENCY, idem.evidence)
    put("double_execution",
        idem.data.get("double_execution") if idem.applicable else None,
        IDEMPOTENCY, idem.evidence)

    lat = by_name[LATENCY]
    put("latency_p50_ms", lat.data.get("p50_ms"), LATENCY, lat.evidence)
    put("latency_p95_ms", lat.data.get("p95_ms"), LATENCY, lat.evidence)

    # Признак о самой пробе: убрала ли она за собой. Без него нельзя доверять
    # ни одному следующему измерению того же сервиса — а значит и этому.
    released = sum(s["released"] for s in prober.sweeps)
    failed = [f for s in prober.sweeps for f in s["failed"]]
    put("probe_cleaned_up", not failed and not prober.leaked, CONCURRENCY,
        f"уборок: {len(prober.sweeps)}, обратных вызовов: {released}, "
        f"неудач: {failed or 'нет'}; осталось удержанными: "
        f"{prober.leaked or 'ничего'}; необратимо израсходовано: "
        f"{len(prober.spent)} обязательств")

    return MeasuredProfile(
        service=manifest.service,
        base_url=prober.base_url,
        service_profile=manifest.profile,
        measured_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        features=features,
        probes=tuple(results),
        declared_idempotent_verbs=frozenset(
            c.id for c in manifest if c.idempotency_slot() is not None
        ),
        spent=tuple(prober.spent),
        calls=prober.calls,
    )


# ────────────────────────────────────────────────────────────────────────────
# Сверка заявленного с измеренным
# ────────────────────────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_DIRECTION_ORDER = {EMBELLISHED: 0, INCOMPARABLE: 1, UNVERIFIABLE: 2, MODEST: 3}


def _boolean_gap(
    out: list[Discrepancy],
    name: str,
    declared_value: bool,
    feature: Feature | None,
    embellished: str,
    modest: str,
    extra: str = "",
) -> None:
    """Один булев признак: заявлено против измеренного."""
    if feature is None or feature.value is None:
        if declared_value:
            out.append(Discrepancy(
                name, declared_value, None, UNVERIFIABLE, "info",
                f"положительное заявление осталось непроверенным: {embellished} — "
                f"проба не установила значение (неприменима, либо её ответ не доказывает "
                f"проверку)",
                feature.evidence if feature else "проба не проводилась"))
        return
    measured = bool(feature.value)
    if declared_value and not measured:
        out.append(Discrepancy(name, True, False, EMBELLISHED, "critical",
                               embellished + extra, feature.evidence))
    elif measured and not declared_value:
        out.append(Discrepancy(name, False, True, MODEST, "info", modest, feature.evidence))


def compare(declared: LevelProfile, measured: MeasuredProfile) -> list[Discrepancy]:
    """Расхождения заявленного профиля с измеренным, опаснейшие первыми.

    Асимметрия заложена в вердикты сознательно. `embellished` — критично:
    агент, поверивший такому профилю, выберет сервис под требование, которого
    тот не держит, и узнает об этом ПОСЛЕ необратимого обязательства.
    `modest` — информационно: сервис лишь проигрывает конкурсы, которые мог бы
    выигрывать, и мир от этого не рушится. `unverifiable` — отдельный третий
    случай: положительное заявление, которое проба не смогла ни подтвердить, ни
    опровергнуть. Выдать его за ложь было бы такой же неправдой, как поверить.

    `incomparable` — заявление и измерение выражены в РАЗНЫХ единицах. Доли
    тогда ничего не говорят друг о друге: ни совпадения, ни расхождения нет,
    и отчёт обязан сказать «несопоставимо», а не «совпало».
    """
    out: list[Discrepancy] = []

    extra = ""
    if declared.concurrency_evidence == "not_measured":
        extra = " (причём заявление сделано с concurrency_evidence='not_measured', " \
                "то есть не измерялось вовсе)"
    _boolean_gap(
        out, "concurrency_safe", declared.concurrency_safe,
        measured.feature("concurrency_safe"),
        "заявлена устойчивость к параллельным обязательствам, а часть "
        "одновременных вызовов отвалилась",
        "параллель держит, хотя профиль это отрицает — требование "
        "'needs_concurrency' отсеет его напрасно",
        extra,
    )
    _boolean_gap(
        out, "stock_checked", declared.stock_checked,
        measured.feature("stock_checked"),
        "заявлена проверка остатка, а заведомо завышенный заказ принят",
        "остаток проверяется, хотя профиль это отрицает",
    )

    # Соответствие контракту: сравниваем доли, а не абсолютные числа —
    # у измерения свой знаменатель (пробуется только то, что удалось вызвать).
    # НО доли сравнимы только в одних единицах. Измеритель считает ГЛАГОЛЫ, а
    # знаменатель заявления обязан быть числом глаголов его манифеста. Иначе
    # заявление считает что-то другое: у уровня 1 daten2 заявлено 22/22 при 4
    # глаголах — это проверки контракта, и «4/4 = 22/22» было бы мнимым
    # совпадением. Ограничение: единица выводится из знаменателя, поэтому
    # проверки, случайно равные числу глаголов, этим признаком не отличить.
    m_passed, m_total = measured.conformance
    if m_total:
        d_ratio, m_ratio = declared.conformance_ratio, m_passed / m_total
        d_text = f"{declared.conformance_passed}/{declared.conformance_total}"
        m_text = f"{m_passed}/{m_total}"
        ev = measured.feature("contract_conformance").evidence
        verbs_declared = len(declared.declared_verbs)
        if declared.conformance_total != verbs_declared:
            out.append(Discrepancy(
                "contract_conformance", d_text, m_text, INCOMPARABLE, "warning",
                f"несопоставимо: заявлено {d_text}, но знаменатель "
                f"{declared.conformance_total} не равен числу глаголов манифеста "
                f"({verbs_declared}) — заявление считает, по всей видимости, проверки "
                f"контракта, а измеритель считает глаголы (измерено {m_text}). "
                "Доли несопоставимы: ни совпадения, ни расхождения здесь нет", ev))
        elif m_ratio < d_ratio - 1e-9:
            out.append(Discrepancy(
                "contract_conformance", d_text, m_text, EMBELLISHED,
                "critical" if d_ratio >= 1.0 else "warning",
                f"заявлено {d_text} ({d_ratio:.0%}), измерено {m_text} ({m_ratio:.0%}): "
                f"часть глаголов отвечает не своей объявленной схемой", ev))
        elif m_ratio > d_ratio + 1e-9:
            out.append(Discrepancy(
                "contract_conformance", d_text, m_text, MODEST, "info",
                f"измерено {m_text} ({m_ratio:.0%}) против заявленных {d_text} "
                f"({d_ratio:.0%}) — профиль занижает собственное соответствие", ev))

    # Нереализованные глаголы: умолчание опаснее признания.
    measured_missing = set(measured.value("missing_verbs", []) or [])
    hidden = sorted(measured_missing - declared.missing_verbs)
    overstated = sorted(declared.missing_verbs - measured_missing)
    mv = measured.feature("missing_verbs")
    if hidden:
        out.append(Discrepancy(
            "missing_verbs", sorted(declared.missing_verbs), sorted(measured_missing),
            EMBELLISHED, "critical",
            "глаголы объявлены в манифесте, но маршрута у них нет, и в "
            f"missing_verbs они не признаны: {', '.join(hidden)}",
            mv.evidence if mv else ""))
    if overstated:
        out.append(Discrepancy(
            "missing_verbs", sorted(declared.missing_verbs), sorted(measured_missing),
            MODEST, "info",
            "признаны нереализованными, но живой сервис их исполняет: "
            + ", ".join(overstated),
            mv.evidence if mv else ""))

    # Маршрут, который проба не смогла выяснить: ни признать отсутствующим, ни
    # подтвердить реализацию нельзя. Это не приукрашивание и не скромность, а
    # честное «не проверено»: такой глагол выведен из итога контракта, и без
    # этой строки совпавшая доля выглядела бы полной картиной.
    unresolved = sorted(measured.value("unresolved_verbs", []) or [])
    if unresolved:
        uf = measured.feature("unresolved_verbs")
        out.append(Discrepancy(
            "unresolved_verbs",
            sorted(v for v in unresolved if v not in declared.missing_verbs),
            unresolved, UNVERIFIABLE, "info",
            "маршрут не выяснен: проба не смогла ни подтвердить реализацию, ни признать "
            "отсутствие — " + ", ".join(unresolved),
            uf.evidence if uf else ""))

    # Идемпотентность заявлена не профилем уровня, а самим манифестом (§4.5),
    # поэтому заявление берём оттуда — это по-прежнему сверка слова с делом.
    idem = measured.feature("idempotent")
    if measured.declared_idempotent_verbs and idem is not None and idem.value is not None:
        if not idem.value:
            probe = measured.probe(IDEMPOTENCY)
            failed = sorted((probe.data.get("rejected", []) if probe else [])
                            + (probe.data.get("duplicated", []) if probe else []))
            out.append(Discrepancy(
                "idempotency", sorted(measured.declared_idempotent_verbs), failed,
                EMBELLISHED, "critical",
                "манифест объявляет ключ идемпотентности, а повтор с тем же ключом "
                f"не возвращает то же обязательство: {', '.join(failed)}",
                idem.evidence))
    dbl = measured.feature("double_execution")
    if dbl is not None and dbl.value:
        out.append(Discrepancy(
            "double_execution", False, True, EMBELLISHED, "critical",
            "повтор с тем же ключом создал ВТОРОЕ обязательство — ровно та авария, "
            "запрет на которую и есть §4.5", dbl.evidence))

    out.sort(key=lambda d: (_DIRECTION_ORDER[d.direction],
                            _SEVERITY_ORDER.get(d.severity, 3), d.field))
    return out


def embellishments(discrepancies: Iterable[Discrepancy]) -> list[Discrepancy]:
    """Только приукрашивания — то, из-за чего нельзя пускать сервис в маршрут."""
    return [d for d in discrepancies if d.worse_than_declared]


def report(measured: MeasuredProfile, declared: LevelProfile | None = None) -> str:
    """Отчёт человеку: что наблюдали и где слово разошлось с делом."""
    lines = [measured.describe()]
    if declared is not None:
        gaps = compare(declared, measured)
        lines.append("")
        if not gaps:
            lines.append("Заявленный профиль совпал с измеренным: расхождений нет.")
        else:
            lies = embellishments(gaps)
            lines.append(f"Расхождений: {len(gaps)}, из них приукрашиваний: {len(lies)}")
            for d in gaps:
                lines.append("  · " + d.human())
                if d.evidence:
                    lines.append(f"      наблюдение: {d.evidence}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m act.npp_act.prober",
        description="Измерить живой Actionable-сервис и выдать профиль по наблюдениям "
                    "(а не по его заявлению).",
    )
    ap.add_argument("--manifest", required=True, help="файл *.act.json")
    ap.add_argument("--base-url", default=None, help="корень сервиса (иначе из манифеста)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--concurrency", type=int, default=6, help="ширина параллельной пробы")
    ap.add_argument("--repeats", type=int, default=7, help="повторов в пробе задержки")
    ap.add_argument("--max-effect", default="commit", choices=[e for e in EFFECTS if e != "destroy"],
                    help="тяжелее этого эффекта проба не трогает (по умолчанию commit)")
    ap.add_argument("--declared", default=None,
                    help="манифест с level_profile для сверки (иначе берётся --manifest, "
                         "если блок есть в нём)")
    args = ap.parse_args(argv)

    raw = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    manifest = parse_manifest(raw)

    declared: LevelProfile | None = None
    declared_raw = raw
    if args.declared:
        declared_raw = json.loads(Path(args.declared).read_text(encoding="utf-8"))
    if "level_profile" in declared_raw:
        from .profile import parse_level_profile
        declared = parse_level_profile(declared_raw)

    try:
        measured = measure(manifest, base_url=args.base_url, concurrency=args.concurrency,
                           repeats=args.repeats, max_effect=args.max_effect)
    except ProbeError as e:
        print(f"проба не состоялась: {e}", file=sys.stderr)
        return 1

    gaps = compare(declared, measured) if declared is not None else []
    if args.json:
        print(json.dumps({"measured": measured.to_json(),
                          "discrepancies": [d.to_json() for d in gaps]},
                         ensure_ascii=False, indent=2))
    else:
        print(report(measured, declared))

    # Код возврата — часть смысла: гейт, который нашёл приукрашивание и вернул
    # 0, повторил бы ошибку plugin-marketplace (14/14 зелёных при отвергнутых
    # бэкендах). Поэтому ложь в профиле — ненулевой код.
    return 2 if embellishments(gaps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
