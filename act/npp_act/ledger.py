"""Журнал решений: append-only хэш-цепь (SPEC-NPP-ACT.md §6).

Отличие от ops-ledger в daten2: журнал пишется на диск построчно (JSONL) и
переживает перезапуск. Журнал решений ИИ, живущий в оперативной памяти, —
не журнал: его нельзя предъявить как доказательство.

Запись нельзя изменить задним числом, не разорвав цепь: каждая строка несёт
хэш предыдущей, а verify() проверяет сцепление целиком.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64

KINDS = ("intent", "decision", "execution", "outcome", "commitment")


class LedgerError(RuntimeError):
    """Цепь нарушена или запись отвергнута."""


def _canonical(obj: Any) -> str:
    """Каноническая форма JSON: от неё берётся хэш.

    sort_keys + компактные разделители + ensure_ascii=False делают представление
    воспроизводимым независимо от порядка полей в исходном словаре.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_hash(seq: int, ts: str, kind: str, payload: Any, prev: str) -> str:
    body = _canonical({"seq": seq, "ts": ts, "kind": kind, "payload": payload, "prev": prev})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Record:
    seq: int
    ts: str
    kind: str
    payload: dict[str, Any]
    prev: str
    hash: str

    def to_json(self) -> str:
        return _canonical(
            {"seq": self.seq, "ts": self.ts, "kind": self.kind,
             "payload": self.payload, "prev": self.prev, "hash": self.hash}
        )

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Record":
        return Record(d["seq"], d["ts"], d["kind"], d["payload"], d["prev"], d["hash"])


class Ledger:
    """Персистентная хэш-цепь.

    >>> led = Ledger("/tmp/demo.jsonl")
    >>> _ = led.append("intent", {"verb": "order.create"})
    >>> led.verify()
    True
    """

    def __init__(self, path: str | Path, owner: str = "unknown"):
        self.path = Path(path)
        self.owner = owner
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[Record] = []
        if self.path.exists():
            self._load()

    # ---------- чтение ----------

    def _load(self) -> None:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                self._records.append(Record.from_dict(json.loads(line)))

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[Record]:
        return iter(self._records)

    @property
    def head(self) -> str:
        return self._records[-1].hash if self._records else GENESIS

    def by_kind(self, kind: str) -> list[Record]:
        return [r for r in self._records if r.kind == kind]

    def find_idempotency(self, key: str) -> Record | None:
        """Встречался ли уже такой ключ идемпотентности (§5.1.6)."""
        for r in self._records:
            if r.kind == "execution" and r.payload.get("idempotency_key") == key:
                return r
        return None

    # ---------- запись ----------

    def append(self, kind: str, payload: dict[str, Any]) -> Record:
        if kind not in KINDS:
            raise LedgerError(f"неизвестный вид записи: {kind!r} (допустимо: {KINDS})")

        seq = len(self._records)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        prev = self.head
        h = record_hash(seq, ts, kind, payload, prev)
        rec = Record(seq, ts, kind, payload, prev, h)

        # Сначала на диск, потом в память: при сбое между ними журнал не соврёт,
        # а перечитается с диска в консистентном виде.
        with self.path.open("a", encoding="utf-8") as f:
            f.write(rec.to_json() + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._records.append(rec)
        return rec

    # ---------- проверка ----------

    def verify(self) -> bool:
        """Проверить сцепление цепи целиком."""
        prev = GENESIS
        for i, r in enumerate(self._records):
            if r.seq != i:
                raise LedgerError(f"запись {i}: нарушена нумерация (seq={r.seq})")
            if r.prev != prev:
                raise LedgerError(f"запись {i}: не сцеплена с предыдущей")
            expect = record_hash(r.seq, r.ts, r.kind, r.payload, r.prev)
            if expect != r.hash:
                raise LedgerError(f"запись {i}: содержимое изменено (хэш не сходится)")
            prev = r.hash
        return True

    def reload(self) -> "Ledger":
        """Перечитать с диска — доказательство персистентности."""
        return Ledger(self.path, owner=self.owner)
