"""Реестр Actionable-сервисов — аналог nautilus.json для уровня 4."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .manifest import Manifest, load_manifest, parse_manifest


class Registry:
    """Какие сервисы существуют и что они умеют.

    Наутилус отвечает на вопрос «что существует и что с чем совместимо».
    Реестр уровня 4 отвечает дополнительно: «что из этого можно сделать».
    """

    def __init__(self) -> None:
        self._manifests: dict[str, Manifest] = {}

    # ---------- наполнение ----------

    def add(self, manifest: Manifest) -> "Registry":
        self._manifests[manifest.service] = manifest
        return self

    def add_file(self, path: str | Path) -> "Registry":
        return self.add(load_manifest(path))

    def load_dir(self, directory: str | Path) -> "Registry":
        for path in sorted(Path(directory).glob("*.act.json")):
            self.add_file(path)
        return self

    def load_registry(self, path: str | Path) -> "Registry":
        """Загрузить по файлу-реестру вида {"services": [{"act_manifest": "..."}]}."""
        base = Path(path).parent
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for entry in data.get("services", []):
            self.add_file(base / entry["act_manifest"])
        return self

    def rebind(self, service: str, base_url: str) -> "Registry":
        """Переопределить адрес сервиса.

        Манифест объявляет адрес по умолчанию, но один и тот же сервис живёт по
        разным адресам в разных развёртываниях (и на разных из семи уровней
        daten2). Перепривязка меняет только адрес — объявленные последствия
        глаголов остаются ровно теми, что прошли валидацию.
        """
        man = self._manifests.get(service)
        if man is None:
            raise KeyError(f"сервис '{service}' не зарегистрирован")
        self._manifests[service] = dataclasses.replace(man, base_url=base_url.rstrip("/"))
        return self

    # ---------- чтение ----------

    def manifest(self, service: str) -> Manifest | None:
        return self._manifests.get(service)

    def services(self) -> list[str]:
        return sorted(self._manifests)

    def __len__(self) -> int:
        return len(self._manifests)

    def find(self, *, effect: str | None = None, profile: str | None = None) -> list[tuple[str, str]]:
        """Найти глаголы по последствию и/или роли сервиса → [(service, verb_id)]."""
        out: list[tuple[str, str]] = []
        for svc, man in sorted(self._manifests.items()):
            if profile and man.profile != profile:
                continue
            for cap in man:
                if effect and cap.effect != effect:
                    continue
                out.append((svc, cap.id))
        return out

    def catalog(self) -> list[dict]:
        """Плоский каталог возможностей — то, что мог бы читать оркестратор вроде n8n."""
        rows = []
        for svc, man in sorted(self._manifests.items()):
            for cap in man:
                rows.append({
                    "service": svc,
                    "profile": man.profile,
                    "verb": cap.id,
                    "title": cap.title,
                    "effect": cap.effect,
                    "severity": cap.severity,
                    "reversible": cap.reversible,
                    "consent": cap.consent,
                    "money": cap.cost.get("money"),
                })
        return rows
