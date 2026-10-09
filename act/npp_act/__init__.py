"""NPP-Act 1.0 — эталонная реализация уровня совместимости 4 Nautilus Portal Protocol.

Зависимостей нет: только стандартная библиотека Python.
Та же дисциплина, что у daten2 — всё работает без API-ключей и без сети наружу.
"""

__version__ = "1.0"

from .manifest import Capability, Manifest, ManifestError, load_manifest
from .ledger import Ledger, LedgerError
from .governor import Governor, Decision, Budget
from .executor import Executor, ExecutionError
from .registry import Registry
from .agent import Agent

__all__ = [
    "Capability", "Manifest", "ManifestError", "load_manifest",
    "Ledger", "LedgerError",
    "Governor", "Decision", "Budget",
    "Executor", "ExecutionError",
    "Registry", "Agent",
]
