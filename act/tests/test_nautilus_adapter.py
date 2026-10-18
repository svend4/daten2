"""Тест адаптера NPP-Act для Nautilus Portal.

Главное правило проекта: не сверять модуль с собственным моком. Здесь это
означает четыре вещи, и каждая из них — отдельная группа проверок.

  1. ПРОТОКОЛ берётся из НАСТОЯЩЕГО исходника `svend4/nautilus`: `adapters/base.py`
     грузится из клона, и адаптер проверяется как подкласс настоящего
     `BaseAdapter`, а записи — как экземпляры настоящего `PortalEntry`. Локальный
     дублёр, который живёт в адаптере для запуска без Наутилуса, сверяется с
     исходником по полям: разойдутся — тест упадёт. Требования («MUST NOT raise»,
     «at most 20 entries», семь допустимых типов) читаются из текста
     PORTAL-PROTOCOL.md, а не пересказываются по памяти.
  2. ДАННЫЕ берутся из НАСТОЯЩИХ манифестов `act/manifests/` (включая `levels/`),
     и каждое поле, прочитанное адаптером, сверяется с результатом НАСТОЯЩЕГО
     валидатора `act.npp_act.load_manifest`. Разойдётся манифест — упадёт тест.
  3. ЖИВОЙ КОНТУР: поднимается настоящий сервис цеха (`act.services.freelance`),
     и адаптер читает его манифест по сети. Заодно проверяется деградация на
     настоящем 404 сервиса заведения — это не придуманный сбой, а реальный
     дефект пути в `act/services/venue/server.py`.
  4. ПАКЕТ ПЕРЕНОСА проверяется против настоящих файлов Наутилуса: схема
     паспорта, список допустимых типов мостов, требования `health_check.py`,
     и — главное — что каждая строка, которую `APPLY.md` велит найти и
     поправить, действительно существует в целевом файле. Инструкция, ссылающаяся
     на несуществующую строку, невыполнима, сколько бы её ни читали.

Клон Наутилуса обязателен. Без него тест отказывается работать, а не «проходит
на дублёре»: сверка с собственным дублёром — ровно та самосертификация, из-за
которой `plugin-marketplace` в этом же репозитории имеет 14/14 зелёных и
отвергает все настоящие бэкенды.

Путь к клону: `NAUTILUS_SRC`, иначе ищется рядом (~/svend4/nautilus и соседи).

Запуск:  python3 -m act.tests.test_nautilus_adapter
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PKG = ROOT / "act" / "integrations" / "nautilus"
ADAPTER_SRC = PKG / "npp_act_adapter.py"
REGISTRY_ENTRY = PKG / "registry-entry.json"
PASSPORT = PKG / "passport-daten2.md"
APPLY = PKG / "APPLY.md"
PKG_README = PKG / "README.md"
MANIFESTS = ROOT / "act" / "manifests"

GUILD_PORT = 8233
VENUE_PORT = 8234
GUILD = f"http://127.0.0.1:{GUILD_PORT}"
VENUE = f"http://127.0.0.1:{VENUE_PORT}"

PASSED = 0
FAILED = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def wait_up(url: str, attempts: int = 60) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# Поиск настоящего исходника протокола
# ---------------------------------------------------------------------------


def find_nautilus() -> Path | None:
    env = os.environ.get("NAUTILUS_SRC", "").strip()
    candidates = [Path(env)] if env else []
    candidates += [
        Path.home() / "svend4" / "nautilus",
        ROOT.parent / "svend4" / "nautilus",
        ROOT.parent / "nautilus",
        Path("/home/user/svend4/nautilus"),
    ]
    for c in candidates:
        if (c / "adapters" / "base.py").is_file() and (c / "PORTAL-PROTOCOL.md").is_file():
            return c.resolve()
    return None


def load_real_base(naut: Path) -> types.ModuleType:
    """Загрузить настоящий adapters/base.py, не исполняя adapters/__init__.py.

    `__init__.py` Наутилуса тянет все адаптеры сразу, часть которых требует
    внешних пакетов. Нам нужен только протокол, поэтому синтетический
    пакет-пустышка с правильным __path__: он перехватывает импорт `adapters`,
    а `adapters.base` грузится из настоящего файла.
    """
    pkg = types.ModuleType("adapters")
    pkg.__path__ = [str(naut / "adapters")]  # type: ignore[attr-defined]
    sys.modules["adapters"] = pkg
    spec = importlib.util.spec_from_file_location("adapters.base", naut / "adapters" / "base.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["adapters.base"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_adapter(module_name: str) -> types.ModuleType:
    """Загрузить файл адаптера под заданным именем (без пакета → без относительных импортов)."""
    spec = importlib.util.spec_from_file_location(module_name, ADAPTER_SRC)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# 1. Протокол из настоящего исходника
# ---------------------------------------------------------------------------


def test_protocol(naut: Path, base: types.ModuleType, M: types.ModuleType) -> None:
    print("\n[1] Протокол — настоящий adapters/base.py и PORTAL-PROTOCOL.md")

    check("адаптер импортировался против настоящего base.py",
          M.BASE_SOURCE.startswith("nautilus:"), M.BASE_SOURCE)
    check("NppActAdapter — подкласс настоящего BaseAdapter",
          issubclass(M.NppActAdapter, base.BaseAdapter))

    a = M.NppActAdapter([str(MANIFESTS)], live=False)
    check("экземпляр создаётся (оба абстрактных метода реализованы)",
          isinstance(a, base.BaseAdapter))
    check("абстрактных методов ровно два: fetch и describe",
          set(base.BaseAdapter.__abstractmethods__) == {"fetch", "describe"},
          str(set(base.BaseAdapter.__abstractmethods__)))

    entries = a.fetch("")
    check("fetch возвращает экземпляры настоящего PortalEntry",
          bool(entries) and all(isinstance(e, base.PortalEntry) for e in entries))

    d = a.describe()
    check("describe отдаёт REQUIRED-ключи format и native_unit",
          isinstance(d.get("format"), str) and isinstance(d.get("native_unit"), str))
    check("describe отдаёт compatibility = 4", d.get("compatibility") == 4, str(d.get("compatibility")))
    totals = [k for k in d if k.startswith("total_") and isinstance(d[k], int)]
    check("describe отдаёт хотя бы один int-ключ total_* (его читает health_check)",
          bool(totals), str(totals))
    check("describe отдаёт q6_range — список адресов домена (§5, §10)",
          isinstance(d.get("q6_range"), list) and bool(d["q6_range"]))

    # --- дублёр сверяется с настоящим исходником, а не наоборот ---
    saved = {k: sys.modules.pop(k) for k in ("adapters", "adapters.base") if k in sys.modules}
    try:
        shim = load_adapter("npp_act_shim_probe")
    finally:
        sys.modules.update(saved)
    check("без Наутилуса адаптер падает на локальный дублёр", shim.BASE_SOURCE == "local-shim",
          shim.BASE_SOURCE)

    real_fields = dataclasses.fields(base.PortalEntry)
    shim_fields = dataclasses.fields(shim.PortalEntry)
    check("дублёр PortalEntry: те же поля в том же порядке",
          [f.name for f in real_fields] == [f.name for f in shim_fields],
          f"{[f.name for f in shim_fields]} vs {[f.name for f in real_fields]}")
    check("дублёр PortalEntry: те же обязательные поля (без значения по умолчанию)",
          [f.name for f in real_fields if f.default is dataclasses.MISSING
           and f.default_factory is dataclasses.MISSING]
          == [f.name for f in shim_fields if f.default is dataclasses.MISSING
              and f.default_factory is dataclasses.MISSING])
    check("дублёр BaseAdapter: те же абстрактные методы",
          set(shim.BaseAdapter.__abstractmethods__) == set(base.BaseAdapter.__abstractmethods__))
    check("дублёр fuzzy_match ведёт себя как настоящий",
          all(shim.fuzzy_match(q, t) == base.fuzzy_match(q, t)
              for q, t in [("заказ", "Оформить заказ"), ("", "x"), ("xyz", "Оформить заказ"),
                           ("order", "order.create · flower-shop")]))

    # --- требования читаются из текста протокола ---
    proto = (naut / "PORTAL-PROTOCOL.md").read_text(encoding="utf-8")

    block41 = proto.split("### 4.1.")[1].split("### 4.2.")[0]
    declared = set(re.findall(r"^\|\s*`(\w+)`", block41, re.M))
    check("§4.1 протокола объявляет ровно семь типов записи",
          len(declared) == 7, str(sorted(declared)))
    check("'action' среди них отсутствует — тип действительно новый",
          "action" not in declared)
    check("'document' и 'schema' среди них есть — деградация и тип манифеста законны",
          {"document", "schema"} <= declared)
    check("§4.1 разрешает дополнительные значения типа",
          "MAY define additional values" in block41, "текст §4.1 изменился")
    check("§4.1 требует трактовать неизвестный тип как document",
          bool(re.search(r"MUST\s+be\s+treated\s+as\s+`document`", block41)))

    block5 = proto.split("## 5. BaseAdapter Interface")[1].split("## 6.")[0]
    check("§5 требует не бросать исключений", "MUST NOT raise" in block5)
    check("§5 ограничивает выдачу 20 записями", "at most 20 entries" in block5)
    check("§4.4 требует непустой fallback с is_fallback=True",
          "is_fallback=True" in proto.split("### 4.4.")[1].split("## 5.")[0])
    check("§9.3 разрешает адаптеру свою проекцию в Q6",
          "Each adapter defines a rule" in proto.split("### 9.3.")[1].split("### 9.4.")[0])


# ---------------------------------------------------------------------------
# 2. PortalEntry по настоящим манифестам
# ---------------------------------------------------------------------------


def test_entries(base: types.ModuleType, M: types.ModuleType) -> None:
    print("\n[2] Записи по настоящим манифестам act/manifests/ (включая levels/)")

    files = sorted(MANIFESTS.rglob("*.act.json"))
    check("манифесты в репозитории найдены", len(files) >= 10, str(len(files)))

    a = M.NppActAdapter([str(MANIFESTS)], live=False)
    entries = a.entries()
    d = a.describe()

    from act.npp_act import load_manifest  # настоящий валидатор проекта

    real = [load_manifest(f) for f in files]
    real_verbs = sum(len(m.capabilities) for m in real)

    check("сервисов столько же, сколько манифестов",
          d["total_services"] == len(files), f"{d['total_services']} vs {len(files)}")
    check("глаголов столько же, сколько в манифестах по настоящему валидатору",
          d["total_verbs"] == real_verbs, f"{d['total_verbs']} vs {real_verbs}")
    check("записей = якорь + сервисы + глаголы",
          len(entries) == 1 + len(files) + real_verbs, str(len(entries)))
    check("ни одна запись не помечена fallback при живых источниках",
          not any(e.is_fallback for e in entries))
    check("ни одного источника в failed", d["sources"]["failed"] == [], str(d["sources"]["failed"]))

    ids = [e.id for e in entries]
    check("id уникальны глобально", len(ids) == len(set(ids)))
    check("id по форме '<adapter>:<slug>' (§4.3)",
          all(e.id.startswith("npp_act:") and ":" in e.id for e in entries))
    check("title ≤ 200 символов (§4)", all(len(e.title) <= 200 for e in entries))
    check("content ≤ 1000 символов (§4)", all(len(e.content) <= 1000 for e in entries))
    check("source — slug репозитория у всех записей",
          all(e.source == "svend4/daten2" for e in entries))
    check("metadata — словарь, links — список строк",
          all(isinstance(e.metadata, dict) and isinstance(e.links, list)
              and all(isinstance(x, str) for x in e.links) for e in entries))

    verbs = [e for e in entries if e.metadata.get("verb")]
    svcs = [e for e in entries if e.metadata.get("verb") is None and e.id != "npp_act:spec"]
    check("запись о глаголе имеет format_type='action'",
          all(e.format_type == M.ACTION_TYPE for e in verbs))
    check("запись о манифесте имеет существующий тип 'schema'",
          all(e.format_type == M.SCHEMA_TYPE for e in svcs) and len(svcs) == len(files))
    check("якорь расширения присутствует ровно один", ids.count("npp_act:spec") == 1)

    known = set(ids)
    dangling = sorted({x for e in entries for x in e.links} - known)
    check("все перекрёстные ссылки разрешаются внутри каталога (уровень 2)",
          not dangling, str(dangling[:3]))
    check("у каждой записи о глаголе ссылки непусты (уровень 2)",
          all(e.links for e in verbs))

    # обратный глагол обязан быть в ссылках
    with_reverse = [e for e in verbs if e.metadata.get("reverse")]
    check("обратный глагол попадает в links",
          bool(with_reverse) and all(
              f"npp_act:{e.metadata['service']}.{e.metadata['reverse']}" in e.links
              for e in with_reverse))

    # стабильность id между двумя независимыми сборками (§4.3)
    b = M.NppActAdapter([str(MANIFESTS)], live=False)
    check("id стабильны между сборками (§4.3)", [e.id for e in b.entries()] == ids)

    check("fetch('') не больше 20 записей", len(a.fetch("")) <= 20, str(len(a.fetch(""))))
    check("fetch(запрос) не больше 20 записей", len(a.fetch("read")) <= 20)
    sample = a.fetch("")
    check("представительная выборка начинается с якоря", sample[0].id == "npp_act:spec")
    check("в выборке представлен каждый встреченный адрес последствия",
          {e.metadata["q6"] for e in sample if e.metadata.get("verb")}
          == {e.metadata["q6"] for e in verbs},
          str(sorted({e.metadata["q6"] for e in verbs}
                     - {e.metadata["q6"] for e in sample if e.metadata.get("verb")})))
    check("остаток мест выборки добран коллизиями §9.4, а не оставлен пустым",
          len(sample) == 20 and
          len({e.metadata["q6"] for e in sample if e.metadata.get("verb")})
          < len([e for e in sample if e.metadata.get("verb")]),
          str(len(sample)))
    check("тяжёлые последствия стоят в выборке раньше безопасных",
          [e.metadata["severity"] for e in sample if e.metadata.get("verb")][:3]
          >= [e.metadata["severity"] for e in sample if e.metadata.get("verb")][-3:])

    scored = a.fetch("заказ")
    vals = [M.NppActAdapter._score("заказ", e) for e in scored]
    check("выдача упорядочена по релевантности по убыванию (§5.1)",
          vals == sorted(vals, reverse=True), str(vals))
    check("поиск по глаголу находит именно его",
          any(e.id == "npp_act:flower-shop.order.create" for e in a.fetch("order.create")))
    check("поиск по эффекту находит все денежные глаголы",
          {e.id for e in a.fetch("money") if e.metadata.get("verb")}
          == {e.id for e in verbs if e.metadata["effect"] == "money"})


# ---------------------------------------------------------------------------
# 3. Сверка с настоящим валидатором act.npp_act
# ---------------------------------------------------------------------------


def test_against_real_validator(M: types.ModuleType) -> None:
    print("\n[3] Каждое поле записи сверено с настоящим act.npp_act.load_manifest")

    from act.npp_act import load_manifest

    a = M.NppActAdapter([str(MANIFESTS)], live=False)
    by_id = {e.id: e for e in a.entries()}

    mismatch: list[str] = []
    q6_mismatch: list[str] = []
    seen = 0
    for f in sorted(MANIFESTS.rglob("*.act.json")):
        man = load_manifest(f)
        for cap in man.capabilities.values():
            seen += 1
            e = by_id.get(f"npp_act:{man.service}.{cap.id}")
            if e is None:
                mismatch.append(f"{man.service}.{cap.id}: записи нет")
                continue
            m = e.metadata
            for key, want in (
                ("effect", cap.effect),
                ("consent", cap.consent),
                ("reversible", cap.reversible),
                ("reverse", cap.reverse),
                ("severity", cap.severity),
                ("committing", cap.is_committing),
                ("idempotency", cap.idempotency),
                ("expires_s", cap.expires_s),
                ("method", cap.binding["method"]),
                ("path", cap.binding["path"]),
                ("money", cap.cost.get("money")),
                ("profile", man.profile),
                ("service", man.service),
            ):
                if m.get(key) != want:
                    mismatch.append(f"{man.service}.{cap.id}.{key}: {m.get(key)!r} != {want!r}")
            want_q6 = M.q6_for_verb(cap.effect, cap.reversible, cap.consent)
            if m.get("q6") != want_q6:
                q6_mismatch.append(f"{man.service}.{cap.id}: {m.get('q6')} != {want_q6}")

    check(f"терпимый читатель адаптера совпал с валидатором на всех {seen} глаголах",
          not mismatch, "; ".join(mismatch[:3]))
    check("адрес Q6 вычислен из полей настоящего манифеста", not q6_mismatch,
          "; ".join(q6_mismatch[:3]))

    man = load_manifest(MANIFESTS / "venue.act.json")
    svc = by_id["npp_act:venue-clinic-nord"]
    check("сервисная запись несёт заявленный манифестом q6", svc.metadata["q6"] == man.q6, str(man.q6))
    worst = max(man.capabilities.values(), key=lambda c: c.severity)
    check("тяжелейший глагол сервиса определён верно",
          svc.metadata["worst_verb"] == worst.id, svc.metadata["worst_verb"])
    check("requires_human совпадает с требованием согласия",
          all(e.metadata["requires_human"] == (e.metadata["consent"] in ("confirm", "two_party"))
              for e in by_id.values() if e.metadata.get("verb")))
    check("governor_required стоит у всех глаголов, кроме read (SPEC §5)",
          all(e.metadata["governor_required"] == (e.metadata["effect"] != "read")
              for e in by_id.values() if e.metadata.get("verb")))


# ---------------------------------------------------------------------------
# 4. Q6: шесть бит и различение последствий
# ---------------------------------------------------------------------------


def test_q6(M: types.ModuleType) -> None:
    print("\n[4] Q6 — ровно шесть бит, детерминированно, обратимо")

    a = M.NppActAdapter([str(MANIFESTS)], live=False)
    entries = a.entries()

    check("у каждой записи есть q6 ровно из шести бит 0/1",
          all(isinstance(e.metadata.get("q6"), str) and len(e.metadata["q6"]) == 6
              and set(e.metadata["q6"]) <= {"0", "1"} for e in entries))

    combos = [(eff, rev, con) for eff in M.EFFECTS for rev in (True, False) for con in M.CONSENTS]
    addrs = {M.q6_for_verb(*c) for c in combos}
    check("40 комбинаций последствия дают 40 различных адресов", len(addrs) == 40, str(len(addrs)))
    check("круговой обход decode(encode(x)) == x на всех 40",
          all(
              (lambda d, c: d["effect"] == c[0] and d["reversible"] == c[1]
               and d["consent"] == c[2] and not d["reserved"])(M.decode_q6(M.q6_for_verb(*c)), c)
              for c in combos))

    # эффект различается всегда — это главное требование к схеме
    bad: list[str] = []
    for rev in (True, False):
        for con in M.CONSENTS:
            tops = [M.q6_for_verb(eff, rev, con)[0:3] for eff in M.EFFECTS]
            if len(set(tops)) != len(M.EFFECTS):
                bad.append(f"{rev}/{con}: {tops}")
    check("разные эффекты всегда дают разные старшие три бита", not bad, "; ".join(bad))
    check("старшие три бита монотонны по тяжести",
          [int(M.q6_for_verb(eff, False, "none")[0:3], 2) for eff in M.EFFECTS]
          == list(range(len(M.EFFECTS))))
    check("b2 = 1 означает необратимость",
          M.q6_for_verb("commit", False, "none")[3] == "1"
          and M.q6_for_verb("commit", True, "none")[3] == "0")
    check("b1b0 растут вместе с участием человека",
          [M.q6_for_verb("commit", False, c)[4:6] for c in M.CONSENTS]
          == ["00", "01", "10", "11"])
    check("число единиц в адресе растёт от безопасного к предельному",
          M.q6_for_verb("read", True, "none").count("1")
          < M.q6_for_verb("destroy", False, "two_party").count("1"))

    check("зарезервированная область распознаётся",
          M.decode_q6("101111")["reserved"] and M.decode_q6("111111")["reserved"]
          and not M.decode_q6("100111")["reserved"])
    check("ни один настоящий глагол не попадает в зарезервированную область",
          not [e for e in entries if e.metadata.get("verb")
               and M.decode_q6(e.metadata["q6"])["reserved"]])
    check("адрес якоря расширения недостижим для глагола", M.SPEC_Q6 not in addrs)

    for bad_eff in ("", "READ", "delete", None):
        try:
            M.q6_for_verb(bad_eff, False, "none")  # type: ignore[arg-type]
            check(f"неизвестный effect {bad_eff!r} отвергается", False, "исключения не было")
        except (ValueError, TypeError):
            check(f"неизвестный effect {bad_eff!r} отвергается", True)
    try:
        M.q6_for_verb("commit", False, "maybe")
        check("неизвестный consent отвергается", False, "исключения не было")
    except ValueError:
        check("неизвестный consent отвергается", True)
    for bad_q6 in ("", "11111", "1111111", "11112", 110110, None):
        try:
            M.decode_q6(bad_q6)  # type: ignore[arg-type]
            check(f"битый адрес {bad_q6!r} отвергается", False, "исключения не было")
        except (ValueError, TypeError):
            check(f"битый адрес {bad_q6!r} отвергается", True)

    hit = a.fetch("011110")
    check("поиск по адресу находит деньги/необратимо/подтверждение",
          bool(hit) and all(e.metadata["q6"] == "011110" for e in hit)
          and {e.metadata["effect"] for e in hit} == {"money"},
          str([e.id for e in hit]))
    bits = M.q6_bits_explained("011110")
    check("побитовое объяснение адреса читаемо человеком",
          "money" in bits["b5b4b3"] and "необратим" in bits["b2"] and "confirm" in bits["b1b0"],
          str(bits))
    check("q6_key описывает схему бит явно",
          all(t in M.Q6_KEY for t in ("b5b4b3", "b2", "b1b0", "destroy", "two_party")))


# ---------------------------------------------------------------------------
# 5. registry-entry.json
# ---------------------------------------------------------------------------


def test_registry_entry(naut: Path, M: types.ModuleType) -> None:
    print("\n[5] registry-entry.json — запись для nautilus.json")

    try:
        entry = json.loads(REGISTRY_ENTRY.read_text(encoding="utf-8"))
        ok = True
    except Exception as exc:
        entry, ok = {}, False
        check("registry-entry.json — валидный JSON", False, str(exc))
    if ok:
        check("registry-entry.json — валидный JSON", True)
    check("это один объект записи, готовый к вставке в массив registry",
          isinstance(entry, dict))

    proto = (naut / "PORTAL-PROTOCOL.md").read_text(encoding="utf-8")
    block62 = proto.split("### 6.2.")[1].split("### 6.3.")[0]
    required = [k for k in ("repo", "adapter", "format", "compatibility") if f"`{k}`" in block62]
    check("§6.2 требует четыре поля — список прочитан из протокола",
          len(required) == 4, str(required))
    check("все обязательные по §6.2 поля на месте",
          all(k in entry for k in required), str(sorted(entry)))
    check("compatibility = 4", entry.get("compatibility") == 4, str(entry.get("compatibility")))
    check("adapter совпадает с именем класса адаптера",
          entry.get("adapter") == M.NppActAdapter.name, str(entry.get("adapter")))
    check("format совпадает с describe()['format']",
          entry.get("format") == M.NppActAdapter([str(MANIFESTS)], live=False).describe()["format"])

    schema = json.loads((naut / "passport_schema.json").read_text(encoding="utf-8"))
    pattern = schema["properties"]["repo"]["pattern"]
    check("repo соответствует шаблону из настоящей passport_schema.json",
          bool(re.match(pattern, str(entry.get("repo")))), f"{entry.get('repo')} vs {pattern}")

    check("passport указывает на passports/npp_act.md (имя = имя адаптера)",
          entry.get("passport") == f"passports/{M.NppActAdapter.name}.md",
          str(entry.get("passport")))
    check("act_manifest указывает на существующий манифест репозитория",
          (ROOT / str(entry.get("act_manifest"))).is_file(), str(entry.get("act_manifest")))

    live_registry = json.loads((naut / "nautilus.json").read_text(encoding="utf-8"))["registry"]
    common = set(live_registry[0])
    for item in live_registry[1:]:
        common &= set(item)
    check("наша запись содержит все поля, общие для всех настоящих записей реестра",
          common <= set(entry), str(sorted(common - set(entry))))
    check("имя адаптера не занято в настоящем реестре",
          entry.get("adapter") not in {e.get("adapter") for e in live_registry})

    merged = json.loads((naut / "nautilus.json").read_text(encoding="utf-8"))
    merged["registry"].append(entry)
    try:
        json.loads(json.dumps(merged))
        check("реестр с добавленной записью остаётся валидным JSON", True)
    except Exception as exc:  # pragma: no cover
        check("реестр с добавленной записью остаётся валидным JSON", False, str(exc))


# ---------------------------------------------------------------------------
# 6. Паспорт против настоящей схемы и настоящих потребителей
# ---------------------------------------------------------------------------


def test_passport(naut: Path, M: types.ModuleType) -> None:
    print("\n[6] Паспорт против настоящих passport_schema.json, bridge_registry, health_check")

    text = PASSPORT.read_text(encoding="utf-8")
    schema = json.loads((naut / "passport_schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]

    blocks = re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)
    check("в паспорте есть машинно-читаемые JSON-блоки", len(blocks) >= 2, str(len(blocks)))
    data: dict[str, Any] = {}
    for b in blocks:
        try:
            parsed = json.loads(b)
        except Exception:
            continue
        if isinstance(parsed, dict) and "repo" in parsed:
            data = parsed
            break
    check("блок паспорта разбирается как JSON-объект с полем repo", bool(data))

    missing = [k for k in schema["required"] if k not in data]
    check(f"все обязательные поля схемы на месте: {', '.join(schema['required'])}",
          not missing, str(missing))

    jtypes = {"string": str, "integer": int, "object": dict, "array": list, "boolean": bool}
    wrong: list[str] = []
    for key, val in data.items():
        spec = props.get(key)
        if not spec or "type" not in spec:
            continue
        want = spec["type"]
        allowed = tuple(jtypes[t] for t in (want if isinstance(want, list) else [want]) if t in jtypes)
        if allowed and not isinstance(val, allowed):
            wrong.append(f"{key}: {type(val).__name__} ∉ {want}")
        if isinstance(val, str) and "pattern" in spec and not re.match(spec["pattern"], val):
            wrong.append(f"{key}: не по шаблону {spec['pattern']}")
    check("типы полей совпадают со схемой", not wrong, "; ".join(wrong))

    check("compatibility в паспорте = 4", data.get("compatibility") == 4, str(data.get("compatibility")))
    cmax = props["compatibility"].get("maximum")
    allowed_now = isinstance(cmax, int) and cmax >= 4
    instructed = '"maximum": 4' in APPLY.read_text(encoding="utf-8")
    check("уровень 4 либо уже разрешён схемой, либо APPLY.md велит поднять потолок",
          allowed_now or instructed, f"maximum={cmax}, инструкция={instructed}")

    recommended = ["description", "total_items", "q6_key", "bridges", "adapter_file",
                   "access", "example_queries"]
    absent = [k for k in recommended if k not in data]
    check("рекомендованные схемой поля заполнены", not absent, str(absent))
    check("access.type — из перечисления схемы",
          data.get("access", {}).get("type") in props["access"]["properties"]["type"]["enum"],
          str(data.get("access", {}).get("type")))
    check("токены не требуются", data.get("access", {}).get("requires_token") is False)
    check("adapter_file совпадает с именем, которое велит APPLY.md",
          data.get("adapter_file") == f"{M.NppActAdapter.name}.py", str(data.get("adapter_file")))
    check("q6_key в паспорте совпадает со схемой бит адаптера",
          data.get("q6_key") == M.Q6_KEY)
    check("native_unit говорит о глаголе, а не о документе",
          "лагол" in str(data.get("native_unit")), str(data.get("native_unit")))

    # --- мосты: настоящая регулярка bridge_registry.py и настоящие типы §15.2 ---
    br_src = (naut / "bridge_registry.py").read_text(encoding="utf-8")
    pat = re.search(r"_BRIDGE_SECTION_RE = re\.compile\(\s*\n\s*r\"(.*?)\",", br_src, re.DOTALL)
    check("регулярка раздела мостов извлечена из настоящего bridge_registry.py", bool(pat))
    bridges: list[dict[str, Any]] = []
    if pat:
        rx = re.compile(pat.group(1), re.DOTALL | re.IGNORECASE)
        m = rx.search(text)
        check("раздел 'Bridges (machine-readable)' находится настоящей регуляркой", bool(m))
        if m:
            try:
                bridges = json.loads(m.group(1))
            except Exception as exc:
                check("блок мостов разбирается как JSON", False, str(exc))
    check("мостов объявлено не меньше трёх", len(bridges) >= 3, str(len(bridges)))

    proto = (naut / "PORTAL-PROTOCOL.md").read_text(encoding="utf-8")
    block152 = proto.split("### 15.2.")[1].split("### 15.3.")[0]
    valid_types = set(re.findall(r"^\|\s*`(\w+)`", block152, re.M))
    check("список допустимых типов мостов прочитан из §15.2",
          len(valid_types) == 5, str(sorted(valid_types)))
    check("все мосты несут REQUIRED-поля §15.1 (target, type, description)",
          all({"target", "type", "description"} <= set(b) for b in bridges))
    check("тип каждого моста — из §15.2",
          all(b.get("type") in valid_types for b in bridges),
          str([b.get("type") for b in bridges if b.get("type") not in valid_types]))
    check("confidence каждого моста в пределах 0..1",
          all(0.0 <= float(b.get("confidence", 1.0)) <= 1.0 for b in bridges))
    check("мосты несут и поля, которые читает работающий код (direction, mapping)",
          all({"direction", "mapping"} <= set(b) for b in bridges))
    live_adapters = {e.get("adapter") for e in
                     json.loads((naut / "nautilus.json").read_text(encoding="utf-8"))["registry"]}
    unknown = [b["target"] for b in bridges if b["target"] not in live_adapters]
    check("каждый мост ведёт к адаптеру, который есть в настоящем реестре",
          not unknown, str(unknown))

    # --- форма, которую требует настоящий health_check.py ---
    hc = (naut / "health_check.py").read_text(encoding="utf-8")
    req = re.search(r"required = \[(.*?)\]", hc, re.DOTALL)
    labels = re.findall(r'"([^"]+)"', req.group(1)) if req else []
    check("список обязательных полей паспорта прочитан из health_check.py",
          len(labels) == 4, str(labels))
    absent_labels = [l for l in labels if l not in text]
    check("паспорт содержит все поля, которые ищет health_check", not absent_labels,
          str(absent_labels))
    check("health_check найдёт в паспорте Q6", "Q6" in text or "q6" in text)
    check("health_check найдёт в паспорте раздел мостов",
          "Мосты" in text or "Bridges" in text)
    # Дефект well-known заведения исправлен (путь к манифесту считался на каталог
    # выше). Паспорт обязан больше не объявлять его открытым.
    check("паспорт не объявляет исправленный дефект well-known открытым",
          "**404**" not in text and "считается на один каталог выше" not in text)


# ---------------------------------------------------------------------------
# 7. Живой контур: настоящий сервис по сети
# ---------------------------------------------------------------------------


def test_live(M: types.ModuleType) -> None:
    print("\n[7] Живой контур — манифест читается у настоящего работающего сервиса")

    a = M.NppActAdapter([GUILD], live=True, timeout=3.0)
    entries = a.entries()
    d = a.describe()

    check("манифест прочитан по сети, а не из файла",
          d["sources"]["http"] == 1 and d["sources"]["files"] == 0, str(d["sources"]))
    check("ни одна запись не fallback при живом источнике",
          not any(e.is_fallback for e in entries) and not d["sources"]["fallback"])
    check("source_kind у записей — http",
          all(e.metadata.get("source_kind") == "http" for e in entries
              if e.id != "npp_act:spec"))

    from act.npp_act import load_manifest

    man = load_manifest(MANIFESTS / "freelance.act.json")
    check("живой сервис отдал тот же набор глаголов, что лежит в манифесте",
          {e.metadata["verb"] for e in entries if e.metadata.get("verb")}
          == set(man.capabilities), str(d["total_verbs"]))
    check("адреса Q6 по живому манифесту совпадают с адресами по файлу",
          {(e.metadata["verb"], e.metadata["q6"]) for e in entries if e.metadata.get("verb")}
          == {(c.id, M.q6_for_verb(c.effect, c.reversible, c.consent))
              for c in man.capabilities.values()})

    # base_url в манифесте указывает на штатный порт сервиса, а не на тестовый —
    # адаптеру это безразлично: он читает объявление, а не ходит по адресам.
    svc = [e for e in entries if e.id == "npp_act:freelance-guild"][0]
    check("сервисная запись несёт адрес манифеста, а не адрес действия",
          str(svc.metadata["manifest_url"]).endswith("/.well-known/npp-act.json"),
          str(svc.metadata["manifest_url"]))

    # Исправленный дефект: манифест заведения отдаётся по well-known (было 404).
    with urllib.request.urlopen(f"{VENUE}/.well-known/npp-act.json", timeout=3) as r:
        code = r.status
    check("манифест заведения отдаётся по well-known (исправлено: было 404)",
          code == 200, f"well-known={code}")

    # Деградация проверяется на НАСТОЯЩЕМ 404 живого сервиса: адрес несуществующего
    # манифеста, а не подделанный ответ. Адаптер обязан упасть к локальному файлу.
    deg = M.NppActAdapter([f"{VENUE}/.well-known/no-such-manifest.json",
                           str(MANIFESTS / "venue.act.json")], live=True, timeout=3.0)
    dd = deg.describe()
    check("на настоящий 404 адаптер не падает, а падает к локальному файлу",
          dd["total_services"] == 1 and dd["sources"]["files"] == 1
          and any("404" in f or "HTTPError" in f for f in dd["sources"]["failed"]),
          str(dd["sources"]))

    live = M.NppActAdapter([VENUE], live=True, timeout=3.0)
    ld = live.describe()
    check("живой адрес заведения теперь читается по сети, без падения к файлу",
          ld["sources"]["http"] == 1 and ld["sources"]["fallback"] is False,
          str(ld["sources"]))

    both = M.NppActAdapter([str(MANIFESTS / "freelance.act.json"), GUILD], live=True, timeout=3.0)
    kinds = {e.metadata.get("source_kind") for e in both.entries() if e.metadata.get("verb")}
    check("при дубликате сервиса побеждает живой источник", kinds == {"http"}, str(kinds))

    off = M.NppActAdapter([GUILD], live=False)
    check("live=False отключает сеть и уводит в fallback",
          off.describe()["sources"]["fallback"] and all(e.is_fallback for e in off.entries()))


# ---------------------------------------------------------------------------
# 8. Устойчивость: манифест без необязательных полей и прочие края
# ---------------------------------------------------------------------------


def test_robustness(base: types.ModuleType, M: types.ModuleType) -> None:
    print("\n[8] Устойчивость — неполный манифест, мусор, пустота, деградация")

    from act.npp_act import parse_manifest
    from act.npp_act.manifest import ManifestError

    # Манифест ровно из обязательных полей: ни title, ни description, ни q6,
    # ни input/output, ни currency. Валидность подтверждает настоящий валидатор.
    minimal = {
        "npp_act": "1.0",
        "service": "bare-minimum",
        "base_url": "http://127.0.0.1:9999",
        "profile": "vendor",
        "capabilities": [
            {
                "id": "thing.read",
                "title": "Чтение",
                "effect": "read",
                "reversible": False,
                "cost": {"money": 0},
                "consent": "none",
                "binding": {"protocol": "http", "method": "GET", "path": "/thing"},
            },
            {
                "id": "thing.destroy",
                "title": "Снос",
                "effect": "destroy",
                "reversible": False,
                "cost": {"money": 0},
                "consent": "two_party",
                "idempotency": "header:Idempotency-Key",
                "binding": {"protocol": "http", "method": "DELETE", "path": "/thing"},
            },
        ],
    }
    try:
        parse_manifest(minimal)
        check("минимальный манифест валиден по настоящему валидатору", True)
    except ManifestError as exc:
        check("минимальный манифест валиден по настоящему валидатору", False, str(exc))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "bare.act.json").write_text(json.dumps(minimal), encoding="utf-8")

        a = M.NppActAdapter([str(tmp)], live=False)
        es = a.entries()
        d = a.describe()
        check("на манифесте без необязательных полей адаптер не падает",
              d["total_verbs"] == 2 and d["total_services"] == 1, str(d["sources"]))
        check("записи остаются валидными PortalEntry",
              all(isinstance(e, base.PortalEntry) for e in es))
        destroy = [e for e in es if e.metadata.get("verb") == "thing.destroy"][0]
        check("destroy + необратим + two_party → адрес 100111",
              destroy.metadata["q6"] == "100111", destroy.metadata["q6"])
        check("отсутствующий q6 сервиса подменяется адресом тяжелейшего глагола",
              [e for e in es if e.id == "npp_act:bare-minimum"][0].metadata["q6"] == "100111")
        check("пустые input/output не ломают запись",
              destroy.metadata["input"] == {} and destroy.metadata["output"] == {})
        check("отсутствующий title сервиса заменяется именем сервиса",
              "bare-minimum" in [e for e in es if e.id == "npp_act:bare-minimum"][0].title)

        # мусор рядом с годным манифестом
        (tmp / "broken.act.json").write_text("{ это не json", encoding="utf-8")
        (tmp / "alien.act.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        (tmp / "badverb.act.json").write_text(json.dumps({
            "npp_act": "1.0", "service": "half-bad", "base_url": "http://x",
            "profile": "vendor",
            "capabilities": [
                {"id": "a.b", "effect": "teleport", "consent": "none",
                 "reversible": False, "cost": {"money": 0},
                 "binding": {"protocol": "http", "method": "GET", "path": "/a"}},
                {"id": "a.c", "effect": "read", "consent": "none",
                 "reversible": False, "cost": {"money": 0},
                 "binding": {"protocol": "http", "method": "GET", "path": "/c"}},
            ],
        }), encoding="utf-8")

        b = M.NppActAdapter([str(tmp)], live=False)
        bd = b.describe()
        check("битый JSON и чужой файл не ломают сборку каталога",
              bd["total_services"] == 2 and len(bd["sources"]["failed"]) == 2,
              f"{bd['total_services']} сервисов, failed={bd['sources']['failed']}")
        check("глагол с неизвестным эффектом пропущен, остальные взяты",
              {e.metadata["verb"] for e in b.entries()
               if e.metadata.get("service") == "half-bad" and e.metadata.get("verb")}
              == {"a.c"})

        # согласие, которого нет в словаре, трактуется в сторону человека
        (tmp2 := tmp / "sub").mkdir()
        (tmp2 / "weird.act.json").write_text(json.dumps({
            "npp_act": "1.0", "service": "weird", "base_url": "http://x", "profile": "vendor",
            "capabilities": [{"id": "x.y", "effect": "money", "consent": "whatever",
                              "reversible": False, "cost": {"money": 1},
                              "binding": {"protocol": "http", "method": "POST", "path": "/x"}}],
        }), encoding="utf-8")
        c = M.NppActAdapter([str(tmp2)], live=False)
        weird = [e for e in c.entries() if e.metadata.get("verb") == "x.y"][0]
        check("неизвестное согласие трактуется в сторону человека (confirm), а не none",
              weird.metadata["consent"] == "confirm" and weird.metadata["requires_human"],
              weird.metadata["consent"])

    # пустота и мусор на входе fetch
    empty = M.NppActAdapter(["/нет/такого/пути"], live=False)
    fb = empty.fetch("")
    check("без источников возвращается непустой fallback (§4.4)", bool(fb))
    check("все fallback-записи помечены is_fallback=True", all(e.is_fallback for e in fb))
    check("fallback содержит и чтение, и обязательство",
          {e.metadata["effect"] for e in fb if e.metadata.get("verb")} == {"read", "commit"})
    check("fallback-запись получает штраф релевантности §5.1",
          M.NppActAdapter._score("заказ", fb[-1]) < 1.0)

    a = M.NppActAdapter([str(MANIFESTS)], live=False)
    weird_queries: list[Any] = ["", "   ", "ALL", "*", None, 0, "х" * 5000, "[", "(((",
                                "💥", "null", "../../etc/passwd", "011110", "1111111"]
    crashed = []
    for q in weird_queries:
        try:
            res = a.fetch(q)  # type: ignore[arg-type]
            if not isinstance(res, list) or len(res) > 20:
                crashed.append(repr(q))
        except Exception as exc:
            crashed.append(f"{q!r}: {type(exc).__name__}")
    check("fetch не бросает исключений ни на одном запросе (§5)", not crashed, str(crashed[:3]))
    check("describe не бросает исключений даже без источников",
          isinstance(empty.describe(), dict))

    # деградация типа
    deg = M.NppActAdapter([str(MANIFESTS)], live=False, degrade=True)
    dverbs = [e for e in deg.entries() if e.metadata.get("verb")]
    check("degrade=True ставит старый тип document",
          all(e.format_type == M.LEGACY_TYPE for e in dverbs))
    check("деградация восстановима: настоящий тип остался в metadata",
          all(e.metadata.get("format_type") == M.ACTION_TYPE for e in dverbs))
    check("деградация не меняет ни id, ни адреса",
          [(e.id, e.metadata["q6"]) for e in dverbs]
          == [(e.id, e.metadata["q6"]) for e in a.entries() if e.metadata.get("verb")])
    check("describe честно сообщает о режиме деградации",
          deg.describe()["degraded"] is True and a.describe()["degraded"] is False)

    # адаптер не содержит кода исполнения
    src = ADAPTER_SRC.read_text(encoding="utf-8")
    check("адаптер не делает ничего, кроме GET (нет POST/PUT/DELETE в запросах)",
          'method="GET"' in src and 'method="POST"' not in src and 'method="PUT"' not in src)
    check("адаптер не знает адреса шлюза действия",
          "/act/perform" not in src)
    check("единственный сетевой путь — well-known манифест",
          src.count("urllib.request.urlopen") == 1 and "/.well-known/npp-act.json" in src)
    check("внешних зависимостей нет",
          not re.search(r"^\s*(import|from)\s+(requests|httpx|yaml|jsonschema|pydantic)",
                        src, re.M))


# ---------------------------------------------------------------------------
# 9. APPLY.md выполним вручную: каждая строка существует в целевом файле
# ---------------------------------------------------------------------------


def test_apply(naut: Path) -> None:
    print("\n[9] APPLY.md — каждая правка указывает на настоящую строку Наутилуса")

    apply = APPLY.read_text(encoding="utf-8")

    targets = [
        ("adapters/npp_act.py", "куда кладётся адаптер"),
        ("passports/npp_act.md", "куда кладётся паспорт"),
        ("nautilus.json", "реестр"),
        ("passport_schema.json", "схема паспорта"),
        ("PORTAL-PROTOCOL.md", "текст протокола"),
        ("generate_passport.py", "генератор паспортов"),
        ("adapters/__init__.py", "регистрация класса"),
        ("portal.py", "подключение в портал"),
    ]
    absent = [t for t, _ in targets if t not in apply]
    check("инструкция называет все восемь целевых файлов", not absent, str(absent))

    # строки, которые инструкция велит найти в чужом репозитории
    anchors = [
        ("adapters/__init__.py", "from .ai_research import AIResearchAdapter"),
        ("portal.py", '"ai_research":  AIResearchAdapter(),'),
        ("passport_schema.json", '"maximum": 3'),
        ("generate_passport.py", "COMPAT_LABELS"),
        ("nautilus.json", '"version": "1.2"'),
        ("PORTAL-PROTOCOL.md", "### 4.1. `format_type` Values"),
        ("PORTAL-PROTOCOL.md", "## 8. Compatibility Levels"),
        ("PORTAL-PROTOCOL.md", "### 8.1. Current Ecosystem Distribution"),
        ("PORTAL-PROTOCOL.md", "### 9.3. Per-Format Projection Rules"),
    ]
    for rel, needle in anchors:
        in_apply = needle in apply
        in_real = needle in (naut / rel).read_text(encoding="utf-8")
        check(f"{rel}: «{needle[:46]}» есть и в инструкции, и в настоящем файле",
              in_apply and in_real, f"в инструкции={in_apply}, в файле={in_real}")

    check("инструкция велит переименовать файл адаптера в npp_act.py",
          "npp_act.py" in apply and "npp_act_adapter.py" in apply)
    check("инструкция объясняет, почему имя паспорта обязано совпадать с адаптером",
          "md_file.stem" in apply or "BridgeRegistry" in apply)
    check("инструкция даёт способ указать каталог манифестов без правки кода",
          "NPP_ACT_MANIFESTS" in apply)
    check("инструкция содержит проверочный прогон",
          "health_check.py" in apply and "NautilusPortal" in apply)
    check("инструкция предупреждает, что исполнение глаголов в Наутилус не переносится",
          "/act/perform" in apply)
    check("инструкция не требует переносить act/ целиком",
          "Не нужно" in apply and "целиком" in apply)
    check("README пакета обосновывает выбор типа записи",
          "MAY define additional values" in PKG_README.read_text(encoding="utf-8"))
    check("README пакета описывает схему бит явно",
          all(t in PKG_README.read_text(encoding="utf-8")
              for t in ("b5 b4 b3", "b2", "b1 b0", "код Грея")))


# ---------------------------------------------------------------------------
# 10. Инструкция исполняется: копия настоящего Наутилуса принимает пакет
#
# Самая сильная проверка этапа и единственная, которая отвечает на вопрос
# «а примет ли?». Шаги 1-7 из APPLY.md применяются программно — по тем же
# якорным строкам, которые инструкция велит найти, — к копии настоящего клона.
# Затем в этой копии запускаются НАСТОЯЩИЕ portal.py, bridge_registry.py,
# health_check.py и generate_passport.py. Если бы инструкция врала хоть в одном
# шаге, эта группа упала бы: патчи не нашли бы якорь либо портал не поднялся.
# Оригинал клона не трогается — все правки в копии во временном каталоге.
# ---------------------------------------------------------------------------


_PROBE = r"""
import json, sys
from portal import NautilusPortal
from bridge_registry import BridgeRegistry
import health_check

out = {}
p = NautilusPortal()
out["adapters"] = sorted(p.adapters)
d = p.describe().get("npp_act", {})
out["compat"] = d.get("compatibility")
out["verbs"] = d.get("total_verbs")
out["services"] = d.get("total_services")
out["fallback"] = d.get("sources", {}).get("fallback")
r = p.query("money")
out["money_total"] = len(r.entries)
out["money_actions"] = sorted(e.id for e in r.entries if e.format_type == "action")
out["neighbors"] = sorted(e.id for e in p.query_neighbors("011110", 0).entries)
b = BridgeRegistry("passports")
out["bridges"] = sorted(x["target"] for x in b.all_for("npp_act"))
out["annotate"] = b.annotate_link("npp_act", "continuum")["bridge_type"]
out["passport"] = health_check.check_passports().get("npp_act")
json.dump(out, sys.stdout, ensure_ascii=False)
"""


def test_apply_for_real(naut: Path, M: types.ModuleType) -> None:
    print("\n[10] Инструкция исполнена на копии настоящего Наутилуса")

    import shutil

    entry = json.loads(REGISTRY_ENTRY.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "nautilus"
        shutil.copytree(naut, dst, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "snapshots", ".github"))

        # шаг 1 — адаптер под штатным именем
        shutil.copy(ADAPTER_SRC, dst / "adapters" / "npp_act.py")
        check("шаг 1: адаптер лёг как adapters/npp_act.py",
              (dst / "adapters" / "npp_act.py").is_file())

        # шаг 2 — регистрация класса по якорю из инструкции
        p = dst / "adapters" / "__init__.py"
        t = p.read_text(encoding="utf-8")
        anchor = "from .ai_research import AIResearchAdapter"
        t2 = t.replace(anchor, anchor + "\nfrom .npp_act import NppActAdapter", 1)
        t2 = t2.replace('"AIResearchAdapter",', '"AIResearchAdapter",\n    "NppActAdapter",', 1)
        p.write_text(t2, encoding="utf-8")
        check("шаг 2: якоря в adapters/__init__.py нашлись и правка применилась",
              t2 != t and "NppActAdapter" in t2)

        # шаг 3 — подключение в портал по двум якорям
        p = dst / "portal.py"
        t = p.read_text(encoding="utf-8")
        imp = "    ContinuumAdapter, AIResearchAdapter,\n)"
        reg = '            "ai_research":  AIResearchAdapter(),'
        t2 = t.replace(imp, "    ContinuumAdapter, AIResearchAdapter, NppActAdapter,\n)", 1)
        t2 = t2.replace(reg, reg + '\n            "npp_act":      NppActAdapter(),', 1)
        p.write_text(t2, encoding="utf-8")
        check("шаг 3: оба якоря в portal.py нашлись и правки применились",
              "NppActAdapter," in t2 and '"npp_act":' in t2)

        # шаг 4 — паспорт под именем адаптера
        shutil.copy(PASSPORT, dst / "passports" / f"{M.NppActAdapter.name}.md")
        check("шаг 4: паспорт лёг как passports/npp_act.md",
              (dst / "passports" / "npp_act.md").is_file())

        # шаг 5 — запись реестра и версия
        p = dst / "nautilus.json"
        reg_json = json.loads(p.read_text(encoding="utf-8"))
        reg_json["registry"].append(entry)
        reg_json["version"] = "1.3"
        p.write_text(json.dumps(reg_json, ensure_ascii=False, indent=2), encoding="utf-8")
        check("шаг 5: реестр принял запись с compatibility=4",
              json.loads(p.read_text(encoding="utf-8"))["registry"][-1]["compatibility"] == 4)

        # шаг 6 — потолок схемы
        p = dst / "passport_schema.json"
        t = p.read_text(encoding="utf-8")
        t2 = t.replace('"maximum": 3', '"maximum": 4', 1)
        p.write_text(t2, encoding="utf-8")
        schema = json.loads(p.read_text(encoding="utf-8"))
        check("шаг 6: потолок совместимости поднят до 4, схема осталась валидной",
              schema["properties"]["compatibility"]["maximum"] == 4
              and schema["properties"]["compatibility"]["minimum"] == 0)

        # шаг 7 — метка уровня в генераторе
        p = dst / "generate_passport.py"
        t = p.read_text(encoding="utf-8")
        t2 = t.replace('    3: "интерактивный",', '    3: "интерактивный",\n    4: "действующий",', 1)
        p.write_text(t2, encoding="utf-8")
        check("шаг 7: метка уровня 4 добавлена в COMPAT_LABELS", t2 != t)

        env = {**os.environ, "NPP_ACT_MANIFESTS": str(MANIFESTS), "PYTHONPATH": str(dst)}
        env.pop("PYTHONDONTWRITEBYTECODE", None)

        res = subprocess.run([sys.executable, "-c", _PROBE], cwd=str(dst), env=env,
                             capture_output=True, text=True, timeout=240)
        check("настоящий портал поднялся с новым адаптером", res.returncode == 0,
              (res.stderr or "").strip().splitlines()[-1] if res.stderr else "")
        if res.returncode != 0:
            return

        out = json.loads(res.stdout)
        check("адаптер npp_act зарегистрирован в настоящем портале",
              "npp_act" in out["adapters"], str(out["adapters"]))
        check("портал видит уровень совместимости 4", out["compat"] == 4, str(out["compat"]))
        check("портал видит все глаголы настоящих манифестов (не fallback)",
              out["verbs"] == 56 and out["services"] == 10 and out["fallback"] is False,
              f"{out['services']}/{out['verbs']}, fallback={out['fallback']}")
        check("поиск 'money' в настоящем портале возвращает записи типа action",
              len(out["money_actions"]) == 3, str(out["money_actions"]))
        check("окрестность Q6 настоящего портала находит глагол по адресу 011110",
              out["neighbors"] == ["npp_act:freelance-guild.escrow.refund",
                                   "npp_act:freelance-guild.payment.release"],
              str(out["neighbors"]))
        check("настоящий BridgeRegistry загрузил мосты паспорта",
              len(out["bridges"]) == 5, str(out["bridges"]))
        check("настоящий BridgeRegistry читает тип моста к continuum",
              out["annotate"] == "embedding", str(out["annotate"]))
        hp = out["passport"] or {}
        check("настоящий health_check признал паспорт полным",
              hp.get("exists") is True and hp.get("missing_fields") == []
              and hp.get("has_q6") is True and hp.get("has_bridges") is True, str(hp))

        val = subprocess.run([sys.executable, "generate_passport.py", "--validate",
                              "passports/npp_act.md"], cwd=str(dst), env=env,
                             capture_output=True, text=True, timeout=120)
        check("настоящий generate_passport.py --validate принял паспорт",
              "в порядке" in val.stdout, (val.stdout + val.stderr).strip()[:120])

        lst = subprocess.run([sys.executable, "generate_passport.py", "--list"],
                             cwd=str(dst), env=env, capture_output=True, text=True, timeout=120)
        check("паспорт виден в списке паспортов Наутилуса",
              "npp_act.md" in lst.stdout and "Паспортов в репозитории: 13" in lst.stdout,
              lst.stdout.strip().splitlines()[0] if lst.stdout else "")

        # ничего из уровней 0-3 не пострадало
        before = subprocess.run(
            [sys.executable, "-c",
             "import json;from portal import NautilusPortal;"
             "p=NautilusPortal();"
             "print(json.dumps(sorted(set(p.adapters)-{'npp_act'})))"],
            cwd=str(naut), capture_output=True, text=True, timeout=240)
        check("набор прежних адаптеров не изменился",
              before.returncode == 0
              and json.loads(before.stdout) == sorted(set(out["adapters"]) - {"npp_act"}),
              (before.stderr or "").strip()[-120:])


# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 62)
    print("ТЕСТ: адаптер NPP-Act для Nautilus Portal (этап 17)")
    print("=" * 62)

    naut = find_nautilus()
    if naut is None:
        print("\n✗ Клон svend4/nautilus не найден. Проверять адаптер против")
        print("  собственного дублёра бессмысленно — это самосертификация.")
        print("  Укажите путь: NAUTILUS_SRC=/путь/к/nautilus python3 -m act.tests.test_nautilus_adapter")
        return 1
    print(f"\nИсходник протокола: {naut}")

    base = load_real_base(naut)
    M = load_adapter("npp_act_under_test")

    test_protocol(naut, base, M)
    test_entries(base, M)
    test_against_real_validator(M)
    test_q6(M)
    test_registry_entry(naut, M)
    test_passport(naut, M)

    procs: list[subprocess.Popen] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        try:
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "act.services.freelance.server",
                 "--port", str(GUILD_PORT), "--db", str(tmp / "guild.db"), "--reset"],
                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "act.services.venue.server",
                 "--port", str(VENUE_PORT), "--db", str(tmp / "venue.db"), "--reset"],
                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            if not (wait_up(f"{GUILD}/api/health") and wait_up(f"{VENUE}/api/health")):
                print("✗ настоящие сервисы не поднялись")
                return 1
            print(f"\nЦех на :{GUILD_PORT}, заведение на :{VENUE_PORT} — живые")
            test_live(M)
        finally:
            for p in procs:
                p.terminate()
            for p in procs:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    test_robustness(base, M)
    test_apply(naut)
    test_apply_for_real(naut, M)

    print(f"\n{'─' * 62}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
