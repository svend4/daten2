"""NPP-Act 1.0 — эталонная реализация уровня совместимости 4 Nautilus Portal Protocol.

Зависимостей нет: только стандартная библиотека Python.
Та же дисциплина, что у daten2 — всё работает без API-ключей и без сети наружу.

Слои:
    manifest   — схема последствий: что глагол сделает с миром
    registry   — какие сервисы существуют и что они умеют
    profile    — профили возможностей семи уровней (ядро общее, ограничения разные)
    governor   — допуск действия до исполнения
    ledger     — персистентная хэш-цепь решений
    executor   — единственное место, где глагол становится HTTP-вызовом
    agent      — протокол двустороннего обязательства
    router     — выбор уровня по требованию, а не «любой из равных»
    market     — переговоры двух агентов
    settlement — двойная запись, эскроу, saga-клиринг
    calendar   — карта обязательств во времени и обнаружение конфликтов
"""

__version__ = "1.0"

from .manifest import Capability, Manifest, ManifestError, load_manifest, parse_manifest
from .ledger import Ledger, LedgerError, Record
from .governor import Governor, Decision, Budget
from .executor import Executor, ExecutionError
from .registry import Registry
from .agent import Agent, Commitment, Hold, new_key
from .profile import LevelProfile, ProfileError, Requirement, covers, load_level_profiles, rank
from .router import CapabilityRouter, RouteDecision, RouterError
from .settlement import Book, SettlementError
from .market import Deal, Party, Preference
from .calendar import Conflict, Entry, build_timeline, detect_conflicts, explain

__all__ = [
    # ядро
    "Capability", "Manifest", "ManifestError", "load_manifest", "parse_manifest",
    "Ledger", "LedgerError", "Record",
    "Governor", "Decision", "Budget",
    "Executor", "ExecutionError",
    "Registry",
    "Agent", "Commitment", "Hold", "new_key",
    # профили и маршрутизация
    "LevelProfile", "ProfileError", "Requirement", "covers", "load_level_profiles", "rank",
    "CapabilityRouter", "RouteDecision", "RouterError",
    # экономика
    "Book", "SettlementError",
    "Deal", "Party", "Preference",
    # время
    "Conflict", "Entry", "build_timeline", "detect_conflicts", "explain",
]
