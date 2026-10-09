"""Адаптер NPP-Act для Nautilus Portal: глагол становится записью каталога.

Зачем он нужен. Наутилус федерирует знание: его единственная структура,
пересекающая границу адаптера, — `PortalEntry`, и все семь допустимых значений
`format_type` (document/concept/rule/theory/schema/archetype/conversation)
описывают то, что можно ПРОЧИТАТЬ. Репозиторий, который что-то ДЕЛАЕТ, в этот
словарь не входит. Этот адаптер — мост: он берёт манифесты NPP-Act и отдаёт
портал те же глаголы в виде обычных `PortalEntry`, чтобы действие искалось
наравне со знанием.

Три решения, которые здесь приняты, и почему именно так.

1. ТИП ЗАПИСИ — новый `format_type = "action"`, с деградацией к `document`.
   Протокол сам оставил эту дверь открытой (§4.1: «Implementations MAY define
   additional values. Unknown values MUST be treated as `document`»), поэтому
   новый тип — не нарушение, а предусмотренное расширение. Врать `document`
   по умолчанию нельзя: читатель, который видит `document`, вправе считать, что
   запись безопасна для показа и пересказа, а запись о глаголе `money` —
   не безопасна. Для читателей старше v1.2, которые требование о деградации
   не исполняют, есть явный режим `degrade=True`: он ставит `document`
   в `format_type`, но НЕ теряет правду — настоящий тип уезжает в
   `metadata["format_type"] = "action"`. Потеря информации при деградации
   должна быть восстановимой, иначе это не деградация, а подмена.

2. Q6-АДРЕС ГЛАГОЛА — детерминированный, из последствия, а не курированный.
   Шесть бит, разложенные по трём осям, которые и нужны агенту для решения:

       b5 b4 b3  эффект (тяжесть, 3 бита, монотонно по возрастанию)
                 000 read · 001 reserve · 010 commit · 011 money · 100 destroy
                 101 110 111 — зарезервировано под будущие эффекты
       b2        необратимость: 0 — обратим (объявлен reverse), 1 — необратим
       b1 b0     согласие: 00 none · 01 notify · 10 confirm · 11 two_party

   Почему «необратимость», а не «обратимость»: так единица всегда означает
   «тяжелее», и число единиц в адресе растёт вместе с риском. Читать адрес
   можно слева направо как ответ на три вопроса §1 спецификации: что изменится,
   можно ли отменить, нужен ли человек.

   Честная оговорка: биты b5..b3 — двоичное ЧИСЛО, а не код Грея. Поэтому
   расстояние Хэмминга внутри этого поля нельзя читать как семантическую
   близость (`001` reserve и `011` money отличаются одним битом, но двумя
   шагами тяжести). Для упорядочивания по риску надо брать `severity`, а
   соседство по Хэммингу означает лишь «тот же профиль последствия с точностью
   до одной оси». Это расходится с §9.2 v1.2, где b5b4 — класс CA: NPP-Act
   занимает то же 64-вершинное пространство, но проектирует в него другую
   сущность, что §9.3 прямо разрешает («Each adapter defines a rule…»).

3. ИСТОЧНИК ДАННЫХ — живой сервис, потом файл, потом статика.
   Уровень 4 обязывает к живому контуру, но адаптер после переноса окажется
   в репозитории Наутилуса, где каталога `act/manifests` нет. Порядок такой:
   явно переданные источники → переменная окружения `NPP_ACT_MANIFESTS` →
   найденный рядом каталог `act/manifests` → вкомпилированный минимум с
   `is_fallback=True` (§4.4: адаптер MUST вернуть непустой список и MUST NOT
   бросить исключение).

Чего адаптер НЕ делает и не должен уметь. Он не вызывает ни один глагол.
Единственный HTTP-запрос, который он делает, — чтение манифеста
(`GET /.well-known/npp-act.json`), то есть объявления, а не действия. Каталог
описывает последствия; исполнять их вправе только рантайм NPP-Act, где стоят
губернатор и журнал. Та же дисциплина, что у узла n8n в этом репозитории.

Файл самодостаточен: ни `act.npp_act`, ни внешних зависимостей. После переноса
он кладётся в `nautilus/adapters/npp_act.py` и работает оттуда без правок.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Базовый протокол: три попытки, по убыванию «настоящести»
#
# Внутри nautilus/adapters/ работает первая. Когда Наутилус просто лежит в
# sys.path — вторая. Третья нужна, чтобы файл можно было проверять и
# запускать внутри daten2, где Наутилуса нет вовсе; определения в ней
# повторяют adapters/base.py по полям и подписям (тест это сверяет
# с настоящим исходником, а не с этим дублёром).
# ---------------------------------------------------------------------------

try:  # pragma: no cover — ветка живёт только внутри nautilus/adapters/
    from .base import BaseAdapter, PortalEntry, fuzzy_match  # type: ignore

    BASE_SOURCE = "nautilus:adapters.base (relative)"
except ImportError:  # pragma: no cover
    try:
        from adapters.base import BaseAdapter, PortalEntry, fuzzy_match  # type: ignore

        BASE_SOURCE = "nautilus:adapters.base (sys.path)"
    except ImportError:
        import difflib
        from abc import ABC, abstractmethod
        from dataclasses import dataclass, field

        BASE_SOURCE = "local-shim"

        @dataclass
        class PortalEntry:  # type: ignore[no-redef]
            """Дублёр PortalEntry из adapters/base.py — поля и порядок те же."""

            id: str
            title: str
            source: str
            format_type: str
            content: str
            metadata: dict[str, Any] = field(default_factory=dict)
            links: list[str] = field(default_factory=list)
            is_fallback: bool = False

        def fuzzy_match(query: str, text: str, threshold: float = 0.6) -> bool:  # type: ignore[misc]
            """Дублёр fuzzy_match из adapters/base.py."""
            if not query or not text:
                return False
            q, t = query.lower(), text.lower()
            if q in t:
                return True
            return difflib.SequenceMatcher(None, q, t).ratio() >= threshold

        class BaseAdapter(ABC):  # type: ignore[no-redef]
            """Дублёр BaseAdapter из adapters/base.py — два абстрактных метода."""

            name: str = "unnamed"

            @abstractmethod
            def fetch(self, query: str) -> list[PortalEntry]:
                ...

            @abstractmethod
            def describe(self) -> dict[str, Any]:
                ...


# ---------------------------------------------------------------------------
# Словарь последствий (SPEC-NPP-ACT.md §4.1, §4.4)
# ---------------------------------------------------------------------------

#: Порядок строго по возрастанию тяжести — он же значение битов b5..b3.
EFFECTS = ["read", "reserve", "commit", "money", "destroy"]
CONSENTS = ["none", "notify", "confirm", "two_party"]

#: Глаголы тяжелее `reserve` создают последствия, которые нельзя «просто отменить».
COMMITTING = {"commit", "money", "destroy"}

EFFECT_HUMAN = {
    "read": "ничего не меняет",
    "reserve": "удерживает ресурс временно, удержание истекает само",
    "commit": "создаёт обязательство",
    "money": "двигает деньги",
    "destroy": "уничтожает состояние необратимо",
}

CONSENT_HUMAN = {
    "none": "агент действует сам",
    "notify": "агент действует и уведомляет постфактум",
    "confirm": "требуется подтверждение владельца до исполнения",
    "two_party": "требуется согласие обоих профилей, оформленное обязательством",
}

#: Новый тип записи и тип, к которому он деградирует у старых читателей.
ACTION_TYPE = "action"
LEGACY_TYPE = "document"

#: Тип для мета-записей: манифест — это действительно схема (последствий).
SCHEMA_TYPE = "schema"

#: Адрес мета-записей расширения. Зарезервированная тяжесть (111) + необратимость
#: + согласие обеих сторон = «последствие неизвестной тяжести, которое нельзя
#: отменить и на которое нужны оба». Предельная точка, ради охраны которой
#: расширение и существует; настоящий глагол такой адрес получить не может.
SPEC_Q6 = "111111"

WELL_KNOWN = "/.well-known/npp-act.json"

SPEC_URL = "https://github.com/svend4/daten2/blob/main/act/SPEC-NPP-ACT.md"


# ---------------------------------------------------------------------------
# Q6: отображение глагола в шесть бит
# ---------------------------------------------------------------------------


def q6_for_verb(effect: str, reversible: bool, consent: str) -> str:
    """Адрес глагола в Q6-пространстве. Детерминирован: тот же глагол — тот же адрес.

    Схема бит описана в заголовке модуля. Функция намеренно строгая: неизвестный
    эффект или согласие — ошибка, а не «нулевой бит по умолчанию». Молчаливое
    приведение к нулю поставило бы `destroy` рядом с `read`.
    """
    if effect not in EFFECTS:
        raise ValueError(f"неизвестный effect '{effect}': допустимы {EFFECTS}")
    if consent not in CONSENTS:
        raise ValueError(f"неизвестный consent '{consent}': допустимы {CONSENTS}")
    severity = EFFECTS.index(effect)
    irreversible = 0 if reversible else 1
    return f"{severity:03b}{irreversible:d}{CONSENTS.index(consent):02b}"


def decode_q6(q6: str) -> dict[str, Any]:
    """Разобрать адрес обратно в последствие. Обратна q6_for_verb на всех 40 комбинациях.

    Нужна не для красоты: Наутилус умеет искать по окрестности Хэмминга
    (`query_neighbors`), и человеку, увидевшему в выдаче «110110», надо чем-то
    объяснить, что это значит.
    """
    if not isinstance(q6, str) or len(q6) != 6 or any(c not in "01" for c in q6):
        raise ValueError(f"Q6 — ровно шесть бит из 0/1, получено {q6!r}")
    severity = int(q6[0:3], 2)
    reserved = severity >= len(EFFECTS)
    return {
        "q6": q6,
        "severity": severity,
        "effect": None if reserved else EFFECTS[severity],
        "reserved": reserved,
        "reversible": q6[3] == "0",
        "consent": CONSENTS[int(q6[4:6], 2)],
    }


def q6_bits_explained(q6: str) -> dict[str, str]:
    """Побитовое объяснение адреса — то, что показывают человеку рядом с записью."""
    d = decode_q6(q6)
    effect = d["effect"] or f"зарезервировано ({d['severity']})"
    return {
        "b5b4b3": f"{q6[0:3]} — эффект: {effect}",
        "b2": f"{q6[3]} — {'необратим' if not d['reversible'] else 'обратим'}",
        "b1b0": f"{q6[4:6]} — согласие: {d['consent']} ({CONSENT_HUMAN[d['consent']]})",
    }


Q6_KEY = (
    "b5b4b3 = эффект (000 read · 001 reserve · 010 commit · 011 money · 100 destroy; "
    "101..111 зарезервировано) · b2 = необратимость (1 = необратим) · "
    "b1b0 = согласие (00 none · 01 notify · 10 confirm · 11 two_party)"
)


# ---------------------------------------------------------------------------
# Чтение манифеста
#
# Это НЕ валидатор NPP-Act: полный валидатор живёт в act/npp_act/manifest.py и
# остаётся на стороне сервиса. Здесь — терпимый читатель: он берёт то, что
# нужно для записи каталога, и молча пропускает глагол, у которого нет
# обязательного поля. Адаптер в портале обязан не падать (§5), а неполный
# манифест — это ошибка сервиса, а не повод уронить чужой каталог.
# ---------------------------------------------------------------------------


def _norm_capability(raw: Any) -> dict[str, Any] | None:
    """Нормализовать один глагол. None — если запись непригодна для каталога."""
    if not isinstance(raw, dict):
        return None
    verb_id = raw.get("id")
    effect = raw.get("effect")
    if not isinstance(verb_id, str) or not verb_id:
        return None
    if effect not in EFFECTS:
        return None
    consent = raw.get("consent")
    if consent not in CONSENTS:
        consent = "confirm"  # неизвестное согласие трактуем в сторону человека
    cost = raw.get("cost") if isinstance(raw.get("cost"), dict) else {}
    binding = raw.get("binding") if isinstance(raw.get("binding"), dict) else {}
    return {
        "id": verb_id,
        "title": raw.get("title") or verb_id,
        "description": raw.get("description") or "",
        "effect": effect,
        "reversible": bool(raw.get("reversible", False)),
        "reverse": raw.get("reverse"),
        "consent": consent,
        "money": cost.get("money", 0),
        "currency": cost.get("currency"),
        "time_s": cost.get("time_s"),
        "idempotency": raw.get("idempotency", "none"),
        "expires_s": raw.get("expires_s"),
        "method": binding.get("method"),
        "path": binding.get("path"),
        "input": raw.get("input") if isinstance(raw.get("input"), dict) else {},
        "output": raw.get("output") if isinstance(raw.get("output"), dict) else {},
    }


def read_manifest(raw: Any) -> dict[str, Any] | None:
    """Нормализовать манифест. None — если это вообще не манифест NPP-Act."""
    if not isinstance(raw, dict):
        return None
    service = raw.get("service")
    if not isinstance(service, str) or not service:
        return None
    caps_raw = raw.get("capabilities")
    if not isinstance(caps_raw, list):
        return None
    caps = [c for c in (_norm_capability(x) for x in caps_raw) if c is not None]
    if not caps:
        return None
    q6 = raw.get("q6")
    if not (isinstance(q6, str) and len(q6) == 6 and all(c in "01" for c in q6)):
        q6 = None
    return {
        "npp_act": raw.get("npp_act", "1.0"),
        "service": service,
        "title": raw.get("title") or service,
        "base_url": (raw.get("base_url") or "").rstrip("/"),
        "profile": raw.get("profile") or "vendor",
        "q6_service": q6,
        "capabilities": caps,
    }


# ---------------------------------------------------------------------------
# Поиск источников
# ---------------------------------------------------------------------------


def discover_sources() -> list[str]:
    """Где искать манифесты, если источники не переданы явно.

    Порядок осмысленный: переменная окружения побеждает, потому что владелец
    Наутилуса должен иметь способ указать свой каталог манифестов, не правя код.
    """
    env = os.environ.get("NPP_ACT_MANIFESTS", "").strip()
    if env:
        return [p for p in (s.strip() for s in env.split(os.pathsep)) if p]

    here = Path(__file__).resolve()
    seen: list[str] = []
    for parent in list(here.parents)[:6] + [Path.cwd()]:
        for candidate in (parent / "act" / "manifests", parent / "manifests"):
            if candidate.is_dir() and str(candidate) not in seen:
                seen.append(str(candidate))
    return seen


# ---------------------------------------------------------------------------
# Статический минимум (§4.4): без него адаптер вернул бы пустоту и соврал,
# что действий нет. Один глагол на чтение и один на обязательство — чтобы по
# выдаче было видно и форму записи, и то, что тип записи различает риск.
# ---------------------------------------------------------------------------

_FALLBACK_MANIFEST: dict[str, Any] = {
    "npp_act": "1.0",
    "service": "flower-shop",
    "title": "Магазин цветов — единый контракт семи уровней",
    "base_url": "http://127.0.0.1:8181",
    "profile": "vendor",
    "q6": "100101",
    "capabilities": [
        {
            "id": "catalog.list",
            "title": "Каталог активных товаров",
            "description": "Чтение каталога. Ничего не меняет в мире.",
            "effect": "read",
            "reversible": False,
            "cost": {"money": 0, "time_s": 0.1},
            "consent": "none",
            "binding": {"protocol": "http", "method": "GET", "path": "/api/products"},
        },
        {
            "id": "order.create",
            "title": "Оформить заказ",
            "description": "Необратимое обязательство: отмены в контракте v1 нет.",
            "effect": "commit",
            "reversible": False,
            "cost": {"money": "variable", "currency": "EUR", "time_s": 0.3},
            "consent": "confirm",
            "idempotency": "field:client_token",
            "binding": {"protocol": "http", "method": "POST", "path": "/api/orders"},
        },
    ],
}


# ---------------------------------------------------------------------------
# Адаптер
# ---------------------------------------------------------------------------


class NppActAdapter(BaseAdapter):
    """Адаптер уровня совместимости 4: отдаёт порталу глаголы как записи каталога."""

    name = "npp_act"
    REPO = "svend4/daten2"
    FORMAT = "daten2-act"
    NATIVE_UNIT = "Глагол контракта (capability) — операция с объявленным последствием"

    #: Сколько записей максимум отдаёт fetch() (§5: «at most 20 entries»).
    LIMIT = 20

    def __init__(
        self,
        sources: list[str] | None = None,
        *,
        repo: str = REPO,
        degrade: bool = False,
        live: bool = True,
        timeout: float = 1.5,
    ) -> None:
        self.repo = repo
        self.degrade = degrade
        self.live = live
        self.timeout = timeout
        self._sources = list(sources) if sources else discover_sources()
        self._entries: list[PortalEntry] | None = None
        self._stats: dict[str, Any] = {
            "files": 0,
            "http": 0,
            "failed": [],
            "services": 0,
            "verbs": 0,
            "fallback": False,
        }

    # ---------------- протокол BaseAdapter ----------------

    def fetch(self, query: str) -> list[PortalEntry]:
        """Поиск по каталогу последствий. Не бросает исключений никогда (§5)."""
        try:
            entries = self.entries()
            q = (query or "").strip().lower()

            if q in ("", "all", "*"):
                return self._sample(entries)

            # Запрос вида «110110» — поиск по адресу последствия.
            if len(q) == 6 and all(c in "01" for c in q):
                hit = [e for e in entries if e.metadata.get("q6") == q]
                return hit[: self.LIMIT]

            hit = [e for e in entries if self._matches(q, e)]
            hit.sort(key=lambda e: self._score(q, e), reverse=True)
            return hit[: self.LIMIT]
        except Exception:
            # Падение адаптера не должно ронять чужой каталог.
            return self._fallback_entries()

    def describe(self) -> dict[str, Any]:
        """Описание формата. REQUIRED по §5 — format и native_unit."""
        try:
            entries = self.entries()
        except Exception:
            entries = self._fallback_entries()

        used = sorted({str(e.metadata.get("q6")) for e in entries if e.metadata.get("q6")})
        return {
            "repo": self.repo,
            "format": self.FORMAT,
            "native_unit": self.NATIVE_UNIT,
            "compatibility": 4,
            "description": (
                "NPP-Act 1.0: манифесты последствий, губернатор допуска и журнал "
                "исполнений. Единица — глагол, а не документ."
            ),
            "q6": SPEC_Q6,
            "q6_range": used,
            "q6_key": Q6_KEY,
            "total_services": int(self._stats["services"]),
            "total_verbs": int(self._stats["verbs"]),
            "total_entries": len(entries),
            "format_type": ACTION_TYPE,
            "format_type_fallback": LEGACY_TYPE,
            "degraded": self.degrade,
            "npp_act": "1.0",
            "spec": SPEC_URL,
            "act_manifest": "act/manifests/flower-shop.act.json",
            "effects": dict(EFFECT_HUMAN),
            "consents": dict(CONSENT_HUMAN),
            "governor_required": True,
            "executes_verbs": False,
            "sources": {
                "declared": list(self._sources),
                "files": int(self._stats["files"]),
                "http": int(self._stats["http"]),
                "failed": list(self._stats["failed"]),
                "fallback": bool(self._stats["fallback"]),
            },
            "base_protocol": BASE_SOURCE,
        }

    # ---------------- сборка каталога ----------------

    def entries(self) -> list[PortalEntry]:
        """Все записи каталога без ограничения по количеству (fetch режет до LIMIT)."""
        if self._entries is None:
            self._entries = self._build()
        return self._entries

    def _build(self) -> list[PortalEntry]:
        manifests: list[dict[str, Any]] = []
        for src in self._sources:
            manifests.extend(self._load_source(src))

        if not manifests:
            self._stats["fallback"] = True
            return self._fallback_entries()

        # Один и тот же сервис может прийти из двух источников (живой сервис и
        # файл рядом). Живой побеждает: манифест по сети — это то, что сервис
        # заявляет СЕЙЧАС, а файл в репозитории мог отстать.
        by_service: dict[str, dict[str, Any]] = {}
        for m in manifests:
            key = m["service"]
            if key not in by_service or m["_kind"] == "http":
                by_service[key] = m

        out: list[PortalEntry] = [self._spec_entry()]
        verbs = 0
        for m in sorted(by_service.values(), key=lambda x: x["service"]):
            out.append(self._service_entry(m))
            for cap in m["capabilities"]:
                out.append(self._verb_entry(m, cap))
                verbs += 1

        self._stats["services"] = len(by_service)
        self._stats["verbs"] = verbs
        return out

    def _load_source(self, src: str) -> list[dict[str, Any]]:
        """Прочитать источник: URL, файл или каталог. Ошибка — не исключение, а запись в stats."""
        try:
            if src.startswith(("http://", "https://")):
                if not self.live:
                    return []
                m = self._load_http(src)
                return [m] if m else []

            path = Path(src)
            if path.is_dir():
                found: list[dict[str, Any]] = []
                for f in sorted(path.rglob("*.act.json")):
                    m = self._load_file(f)
                    if m:
                        found.append(m)
                return found
            if path.is_file():
                m = self._load_file(path)
                return [m] if m else []
        except Exception as exc:  # pragma: no cover — защита периметра
            self._stats["failed"].append(f"{src}: {type(exc).__name__}")
            return []

        self._stats["failed"].append(f"{src}: источник не найден")
        return []

    def _load_file(self, path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._stats["failed"].append(f"{path}: {type(exc).__name__}")
            return None
        m = read_manifest(raw)
        if m is None:
            self._stats["failed"].append(f"{path}: не манифест NPP-Act")
            return None
        m["_kind"] = "file"
        m["_origin"] = path.name
        self._stats["files"] += 1
        return m

    def _load_http(self, url: str) -> dict[str, Any] | None:
        """Прочитать манифест у живого сервиса. Читается ОБЪЯВЛЕНИЕ, не действие."""
        if not url.endswith(".json"):
            url = url.rstrip("/") + WELL_KNOWN
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            # Самая частая причина здесь — 404: сервис есть, манифест не отдаёт.
            self._stats["failed"].append(f"{url}: {type(exc).__name__}")
            return None
        m = read_manifest(raw)
        if m is None:
            self._stats["failed"].append(f"{url}: не манифест NPP-Act")
            return None
        m["_kind"] = "http"
        m["_origin"] = url
        self._stats["http"] += 1
        return m

    # ---------------- записи ----------------

    def _type(self, native: str) -> str:
        """Тип записи с учётом режима деградации."""
        if self.degrade and native == ACTION_TYPE:
            return LEGACY_TYPE
        return native

    def _verb_entry(self, m: dict[str, Any], cap: dict[str, Any]) -> PortalEntry:
        service = m["service"]
        q6 = q6_for_verb(cap["effect"], cap["reversible"], cap["consent"])

        links = [f"{self.name}:{service}", f"{self.name}:spec"]
        if cap["reverse"]:
            links.append(f"{self.name}:{service}.{cap['reverse']}")
        # Обязательство связывается с обратимыми шагами того же сервиса:
        # по §4.2 многошаговый сценарий обязан начинаться с них, и читателю
        # каталога важно видеть, что у `commit` есть безопасный предшественник.
        if cap["effect"] in COMMITTING:
            links.extend(
                f"{self.name}:{service}.{other['id']}"
                for other in m["capabilities"]
                if other["effect"] == "reserve" and other["reversible"]
            )

        metadata: dict[str, Any] = {
            "q6": q6,
            "q6_bits": q6_bits_explained(q6),
            "q6_service": m["q6_service"],
            "npp_act": m["npp_act"],
            "compatibility": 4,
            "service": service,
            "service_title": m["title"],
            "profile": m["profile"],
            "verb": cap["id"],
            "effect": cap["effect"],
            "severity": EFFECTS.index(cap["effect"]),
            "reversible": cap["reversible"],
            "reverse": cap["reverse"],
            "committing": cap["effect"] in COMMITTING,
            "consent": cap["consent"],
            "requires_human": cap["consent"] in ("confirm", "two_party"),
            "money": cap["money"],
            "currency": cap["currency"],
            "idempotency": cap["idempotency"],
            "expires_s": cap["expires_s"],
            "method": cap["method"],
            "path": cap["path"],
            "input": cap["input"],
            "output": cap["output"],
            "governor_required": cap["effect"] != "read",
            "source_kind": m["_kind"],
            "file": m["_origin"],
            "tags": self._tags(m, cap),
        }
        # При деградации настоящий тип не теряется, а переезжает в metadata.
        if self.degrade:
            metadata["format_type"] = ACTION_TYPE

        return PortalEntry(
            id=f"{self.name}:{service}.{cap['id']}",
            title=self._title(cap["title"], service),
            source=self.repo,
            format_type=self._type(ACTION_TYPE),
            content=self._content(m, cap),
            metadata=metadata,
            links=links,
            is_fallback=False,
        )

    def _service_entry(self, m: dict[str, Any]) -> PortalEntry:
        """Запись о сервисе: это схема последствий, поэтому тип `schema`.

        Адрес: заявленный сервисом `q6`, если он есть (это его место в
        пространстве знания, курированное автором), иначе — адрес его
        тяжелейшего глагола. Второе честнее, чем ноль: работающий с сервисом
        рискует ровно тем, что умеет сделать самый опасный его глагол.
        """
        worst = max(m["capabilities"], key=lambda c: EFFECTS.index(c["effect"]))
        worst_q6 = q6_for_verb(worst["effect"], worst["reversible"], worst["consent"])
        counts: dict[str, int] = {}
        for cap in m["capabilities"]:
            counts[cap["effect"]] = counts.get(cap["effect"], 0) + 1

        lines = [
            f"Манифест NPP-Act сервиса «{m['title']}» ({m['service']}, профиль {m['profile']}).",
            f"Глаголов: {len(m['capabilities'])}; по эффектам: "
            + ", ".join(f"{k} — {counts[k]}" for k in EFFECTS if k in counts)
            + ".",
            f"Тяжелейший глагол: {worst['id']} ({worst['effect']}, "
            f"{'необратим' if not worst['reversible'] else 'обратим'}, "
            f"согласие {worst['consent']}).",
            "Манифест — заявление, а не доказательство: поведение сервиса "
            "проверяется пробами, а не доверием к полю (SPEC §10.1).",
        ]
        return PortalEntry(
            id=f"{self.name}:{m['service']}",
            title=f"{m['title']} — манифест последствий",
            source=self.repo,
            format_type=self._type(SCHEMA_TYPE),
            content=" ".join(lines)[:1000],
            metadata={
                "q6": m["q6_service"] or worst_q6,
                "q6_worst": worst_q6,
                "q6_bits": q6_bits_explained(m["q6_service"] or worst_q6),
                "npp_act": m["npp_act"],
                "compatibility": 4,
                "service": m["service"],
                "profile": m["profile"],
                "base_url": m["base_url"],
                "manifest_url": m["base_url"] + WELL_KNOWN if m["base_url"] else None,
                "total_verbs": len(m["capabilities"]),
                "effects": counts,
                "worst_verb": worst["id"],
                "source_kind": m["_kind"],
                "file": m["_origin"],
                "tags": ["манифест", "npp-act", "level4", m["service"], m["profile"]],
            },
            links=[f"{self.name}:spec"]
            + [f"{self.name}:{m['service']}.{c['id']}" for c in m["capabilities"]],
            is_fallback=False,
        )

    def _spec_entry(self) -> PortalEntry:
        """Якорь расширения: одна запись, объясняющая, откуда в каталоге действия."""
        return PortalEntry(
            id=f"{self.name}:spec",
            title="NPP-Act 1.0 — уровень совместимости 4 (Actionable)",
            source=self.repo,
            format_type=self._type(SCHEMA_TYPE),
            content=(
                "Расширение Nautilus Portal Protocol v1.2 до уровня 4: репозиторий "
                "объявляет не только знание, но и глаголы — операции с описанным "
                "последствием (effect), обратимостью, стоимостью и требованием согласия. "
                "Уровни 0-3 не меняются. Запись о глаголе имеет format_type='action' и "
                "деградирует к 'document' у читателей, не знающих нового типа (§4.1). "
                "Исполнять глагол вправе только рантайм NPP-Act, где стоят губернатор "
                "(8 жёстких предикатов) и персистентный журнал; каталог описывает "
                "последствия, но не является способом вызова."
            ),
            metadata={
                "q6": SPEC_Q6,
                "q6_bits": q6_bits_explained(SPEC_Q6),
                "q6_key": Q6_KEY,
                "compatibility": 4,
                "npp_act": "1.0",
                "spec": SPEC_URL,
                "effects": dict(EFFECT_HUMAN),
                "consents": dict(CONSENT_HUMAN),
                "tags": ["npp-act", "level4", "actionable", "действие", "глагол",
                         "губернатор", "журнал", "согласие"],
            },
            links=[],
            is_fallback=False,
        )

    def _fallback_entries(self) -> list[PortalEntry]:
        """Статика на случай, когда ни один источник не прочитался (§4.4)."""
        m = read_manifest(_FALLBACK_MANIFEST)
        if m is None:  # pragma: no cover — вкомпилированный манифест валиден
            return []
        m["_kind"] = "static"
        m["_origin"] = "вкомпилированный минимум"
        out = [self._spec_entry(), self._service_entry(m)]
        out.extend(self._verb_entry(m, cap) for cap in m["capabilities"])
        for e in out:
            e.is_fallback = True
        self._stats["services"] = 1
        self._stats["verbs"] = len(m["capabilities"])
        return out

    # ---------------- вспомогательное ----------------

    @staticmethod
    def _title(verb_title: str, service: str) -> str:
        """Заголовок ≤200 символов (§4). Имя сервиса обязательно: семь уровневых
        манифестов объявляют одинаковые глаголы, и без него выдача неразличима."""
        t = f"{verb_title} · {service}"
        return t if len(t) <= 200 else t[:197] + "..."

    @staticmethod
    def _tags(m: dict[str, Any], cap: dict[str, Any]) -> list[str]:
        obj, _, action = cap["id"].partition(".")
        tags = [
            "действие", "глагол", "npp-act", "level4",
            m["service"], m["profile"], cap["effect"], cap["consent"], obj,
        ]
        if action:
            tags.append(action)
        tags.append("обратим" if cap["reversible"] else "необратим")
        if cap["effect"] in COMMITTING:
            tags.append("обязательство")
        if cap["money"] == "variable":
            tags.append("переменная стоимость")
        return sorted(set(tags))

    @staticmethod
    def _content(m: dict[str, Any], cap: dict[str, Any]) -> str:
        """Текст записи: последствие словами, а не пересказ HTTP-формы."""
        if cap["money"] == "variable":
            money = "сумма известна только из ответа"
            if cap["currency"]:
                money += f" ({cap['currency']})"
        elif cap["money"]:
            money = f"{cap['money']} {cap['currency'] or ''}".strip()
        else:
            money = "бесплатно"

        reverse = (
            f"обратим через {cap['reverse']}" if cap["reversible"] and cap["reverse"]
            else ("обратим" if cap["reversible"] else "необратим")
        )
        idem = (
            f"идемпотентность: {cap['idempotency']}"
            if cap["idempotency"] != "none"
            else "идемпотентность не объявлена"
        )
        expires = f" Удержание истекает через {cap['expires_s']} с." if cap["expires_s"] else ""

        parts = [
            f"Глагол {cap['id']} сервиса {m['service']} (профиль {m['profile']}).",
            f"Последствие: {cap['effect']} — {EFFECT_HUMAN[cap['effect']]}.",
            f"Отмена: {reverse}.",
            f"Стоимость: {money}.",
            f"Согласие: {cap['consent']} — {CONSENT_HUMAN[cap['consent']]}.",
            f"Повтор: {idem}." + expires,
            f"Форма вызова: {cap['method'] or '?'} {cap['path'] or '?'} (справочно).",
            "Исполнять вправе только рантайм NPP-Act: губернатор и журнал.",
        ]
        if cap["description"]:
            parts.append(cap["description"])
        return " ".join(parts)[:1000]

    def _sample(self, entries: list[PortalEntry]) -> list[PortalEntry]:
        """Представительная выборка на пустой запрос (§5).

        Представительность здесь — покрытие РИСКА, а не алфавита: якорь, сервисы,
        затем по одному глаголу на каждый встреченный адрес последствия, от
        тяжёлого к безопасному. Так в первых строках виден `money`, а не
        двадцать безобидных `read`.
        """
        anchors = [e for e in entries if e.id == f"{self.name}:spec"]
        services = [e for e in entries
                    if e.metadata.get("verb") is None and e.id != f"{self.name}:spec"]
        # Семь уровневых манифестов объявляют один и тот же контракт: показывать
        # их все на пустой запрос — значит вытеснить глаголы однообразием.
        services.sort(key=lambda e: -int(decode_q6(str(e.metadata.get("q6_worst",
                                                                     "000000")))["severity"]))
        head = anchors + services[:5]
        verbs = [e for e in entries if e.metadata.get("verb") is not None]
        verbs.sort(
            key=lambda e: (-int(e.metadata.get("severity", 0)), str(e.metadata.get("q6", ""))),
        )
        picked: list[PortalEntry] = []
        rest: list[PortalEntry] = []
        seen: set[str] = set()
        for e in verbs:
            key = str(e.metadata.get("q6"))
            if key not in seen:
                seen.add(key)
                picked.append(e)
            else:
                rest.append(e)

        out = (head + picked)[: self.LIMIT]
        # Остаток мест добирается коллизиями по §9.4 — и это не косметика.
        # Окрестностный поиск портала (`query_neighbors`) ходит в адаптер
        # через fetch(""), то есть видит только эту выборку. Схлопнув адрес до
        # одного представителя и не добрав остальных, мы сделали бы второго
        # претендента на тот же адрес ненаходимым. Полный ответ по адресу
        # всегда даёт fetch("<шесть бит>").
        if len(out) < self.LIMIT:
            out.extend(rest[: self.LIMIT - len(out)])
        return out

    @staticmethod
    def _matches(q: str, e: PortalEntry) -> bool:
        if q in e.title.lower() or q in e.content.lower() or q in e.id.lower():
            return True
        tags = e.metadata.get("tags") or []
        if any(q in str(t).lower() for t in tags):
            return True
        return fuzzy_match(q, e.title)

    @staticmethod
    def _score(q: str, e: PortalEntry) -> float:
        """Релевантность по §5.1, плюс попадание в тег."""
        score = 0.0
        title = e.title.lower()
        if q == title:
            score += 1.0
        elif q in title:
            score += 0.7
        if q in e.content.lower():
            score += 0.3
        if q in e.id.lower():
            score += 0.4
        tags = [str(t).lower() for t in (e.metadata.get("tags") or [])]
        if q in tags:
            score += 0.25
        score += min(len(e.links) * 0.05, 0.2)
        if e.is_fallback:
            score *= 0.5
        return score


__all__ = [
    "NppActAdapter",
    "PortalEntry",
    "BaseAdapter",
    "ACTION_TYPE",
    "LEGACY_TYPE",
    "SCHEMA_TYPE",
    "SPEC_Q6",
    "EFFECTS",
    "CONSENTS",
    "COMMITTING",
    "EFFECT_HUMAN",
    "CONSENT_HUMAN",
    "Q6_KEY",
    "BASE_SOURCE",
    "q6_for_verb",
    "decode_q6",
    "q6_bits_explained",
    "read_manifest",
    "discover_sources",
]
