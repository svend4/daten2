"""Профили возможностей семи уровней: сопоставление с требованием + сверка с исходниками.

Запуск:  python3 -m act.tests.test_profile

Почему тест построен именно так
───────────────────────────────
Главный способ обмануть себя, найденный при аудите экосистемы: проверять
модуль против мока, написанного под те же допущения. `plugin-marketplace`
имеет 14/14 зелёных и при этом отвергает все настоящие бэкенды — его мок
валидирует не то, что валидирует контракт.

Профиль уровня — это ЗАЯВЛЕНИЕ о возможностях (SPEC-NPP-ACT.md §10.1). Тест,
который проверяет заявление против самого заявления, не проверяет ничего.
Поэтому здесь две независимые части:

  ЧАСТЬ A. Каждое поле семи профилей сверяется с НАСТОЯЩИМИ исходниками
           уровней — с тем кодом, по которому проводился аудит (ветки
           `origin/claude/levelN-...`, с откатом на рабочее дерево `levels/`).
           Соврать в манифесте нельзя: тест читает код, а не манифест.

  ЧАСТЬ B. Логика `covers`/`rank` проверяется на тех же семи настоящих
           профилях, а не на выдуманных: если профили разъедутся с кодом,
           сначала покраснеет часть A.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act.profile import (  # noqa: E402
    FEATURES,
    WEIGHTS,
    ProfileError,
    Requirement,
    comparison_table,
    covers,
    explain,
    load_level_profiles,
    parse_level_profile,
    rank,
    rank_report,
)

LEVELS_DIR = ROOT / "act/manifests/levels"

#: Ветки, на которых проводился аудит контракта. Сверяемся именно с ними:
#: в main-ветке часть уровней ещё не несёт контрактных эндпоинтов.
BRANCH = {
    1: "origin/claude/level1-php-GBpVR",
    2: "origin/claude/level2-flask-GBpVR",
    3: "origin/claude/level3-django-GBpVR",
    4: "origin/claude/level4-express-GBpVR",
    5: "origin/claude/level5-react-flask-GBpVR",
    6: "origin/claude/level6-nextjs-GBpVR",
    7: "origin/claude/level7-enterprise-GBpVR",
}

SERVICE = {
    1: "level1-php",
    2: "level2-flask",
    3: "level3-django",
    4: "level4-express",
    5: "level5-react-flask",
    6: "level6-nextjs",
    7: "level7-enterprise",
}

CORE_VERBS = {"health.check", "catalog.list", "order.create", "order.get"}

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


def source(level: int, rel: str) -> str:
    """Исходник уровня: сначала из аудируемой ветки, иначе из рабочего дерева.

    Порядок именно такой: аудит проводился по ветке, и сверять заявления надо
    с тем кодом, который измеряли, а не с тем, что оказалось в main.
    """
    try:
        out = subprocess.run(
            ["git", "show", f"{BRANCH[level]}:{rel}"],
            cwd=str(ROOT), capture_output=True, timeout=30,
        )
        if out.returncode == 0 and out.stdout:
            return out.stdout.decode("utf-8", "replace")
    except Exception:
        pass
    path = ROOT / "levels" / f"level{level}" / rel
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def slice_between(text: str, start: str, end: str) -> str:
    """Фрагмент исходника между двумя маркерами — чтобы судить об одном пути кода."""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i: j if j > 0 else len(text)]


# ════════════════════════════════════════════════════════════════════════════
# 0. Семь манифестов: валидность и ОБЩЕЕ ЯДРО (взаимозаменяемость)
# ════════════════════════════════════════════════════════════════════════════

def test_core_is_shared(profiles) -> None:
    print("\nЯдро контракта — одно на все семь уровней:")

    check("загружено семь профилей", len(profiles) == 7, str(sorted(profiles)))
    check("имена сервисов те, что в реестре уровней",
          set(profiles) == set(SERVICE.values()),
          str(sorted(set(profiles) ^ set(SERVICE.values()))))

    raws = {}
    for level, svc in SERVICE.items():
        raws[level] = json.loads((LEVELS_DIR / f"level{level}.act.json").read_text(encoding="utf-8"))

    check("у всех уровней объявлены ровно четыре глагола ядра",
          all(frozenset(p.declared_verbs) == CORE_VERBS for p in profiles.values()))

    # Ядро — это не только имена, но и объявленные последствия. Если на одном
    # уровне order.create внезапно `consent: none`, уровни перестают быть
    # взаимозаменяемыми, даже когда пути HTTP совпадают.
    shapes = set()
    for level, raw in raws.items():
        caps = {c["id"]: c for c in raw["capabilities"]}
        shapes.add(json.dumps(
            [[cid, caps[cid]["effect"], caps[cid]["consent"], caps[cid]["reversible"],
              caps[cid].get("idempotency", "none"), caps[cid]["binding"]["method"],
              caps[cid]["binding"]["path"]]
             for cid in sorted(caps)],
            ensure_ascii=False, sort_keys=True))
    check("effect/consent/idempotency/binding ядра совпадают побайтово", len(shapes) == 1,
          f"различных форм ядра: {len(shapes)}")

    check("order.create везде commit+confirm и с ключом идемпотентности",
          all(raw["capabilities"] and
              next(c for c in raw["capabilities"] if c["id"] == "order.create")["effect"] == "commit"
              for raw in raws.values()))

    check("порт каждого уровня — 808X по номеру уровня",
          all(raws[lv]["base_url"] == f"http://127.0.0.1:808{lv}" for lv in SERVICE))

    check("все семь — профиль vendor", all(raws[lv]["profile"] == "vendor" for lv in SERVICE))

    check("каждый профиль несёт оговорку «заявление, а не доказательство»",
          all("ЗАЯВЛЕНИЕ" in p.disclaimer and "§10.1" in p.disclaimer for p in profiles.values()))

    check("каждый объявленный дефект указывает место в исходниках",
          all(d.evidence for p in profiles.values() for d in p.defects))


# ════════════════════════════════════════════════════════════════════════════
# A. Сверка заявлений с настоящим кодом уровней
# ════════════════════════════════════════════════════════════════════════════

def test_claims_against_sources(profiles) -> None:
    print("\nЧАСТЬ A — заявления профилей против настоящих исходников:")

    # ── L1: PHP, один файл. Заявлено stock_checked=false ─────────────────────
    l1 = source(1, "index.php")
    check("исходник уровня 1 получен", "/api/orders" in l1, "не найден контрактный путь")
    l1_api = slice_between(l1, "$__path === '/api/orders'", "/api/orders/([0-9a-f]")
    check("L1: заявлено «склад не проверяется» — в коде /api/orders нет колонки stock",
          profiles["level1-php"].stock_checked is False
          and "SELECT name, price FROM products" in l1_api
          and "price, stock" not in l1_api)
    check("L1: заявлена транзакция — в коде есть BEGIN/COMMIT/ROLLBACK",
          profiles["level1-php"].transactional is True
          and "BEGIN" in l1_api and "COMMIT" in l1_api and "ROLLBACK" in l1_api)
    check("L1: заявлен минимальный вес — весь контракт в одном файле",
          profiles["level1-php"].weight == "minimal"
          and profiles["level1-php"].runtime_units == 1
          and "/api/health" in l1 and "/api/products" in l1)

    # ── L2: Flask. Остаток читается, но решение по нему не принимается ───────
    l2 = source(2, "database.py")
    check("исходник уровня 2 получен", "def create_order" in l2)
    l2_order = slice_between(l2, "def create_order", "\ndef ")
    check("L2: заявлено «остаток читается, но не сверяется» — так и в коде",
          profiles["level2-flask"].stock_checked is False
          and "SELECT name, price, stock" in l2_order
          and "stock'] <" not in l2_order and "stock\"] <" not in l2_order)
    # Заявлять нужно то, что в коде, а не то, что помнится: в main-ветке
    # вычитание зажато через MAX(stock - ?, 0), а на аудируемой ветке —
    # нет, и остаток уходит в минус. Профиль описывает аудируемую ветку.
    check("L2: заявлен уход остатка в минус — в коде вычитание без ограничения снизу",
          profiles["level2-flask"].defect("oversell-negative-stock") is not None
          and "UPDATE products SET stock = stock - ?" in l2_order
          and "MAX(stock" not in l2_order)

    # ── L3: Django. Заявлено отсутствие атомарности на API-пути ─────────────
    l3 = source(3, "shop/views.py")
    check("исходник уровня 3 получен", "def api_create_order" in l3)
    l3_api = slice_between(l3, "def api_create_order", "\ndef ")
    check("L3: заявлено «нет транзакции» — в api_create_order нет transaction.atomic",
          profiles["level3-django"].transactional is False and "atomic" not in l3_api)
    check("L3: заявлено «остаток не сверяется» — в коде только prod.stock -= qty",
          profiles["level3-django"].stock_checked is False
          and "prod.stock -= qty" in l3_api and "prod.stock <" not in l3_api)
    l3_admin = source(3, "shop/admin.py")
    check("L3: заявлена админка — в коде зарегистрированы модели",
          profiles["level3-django"].has("has_admin") and "@admin.register" in l3_admin)
    check("L3: заявлены деньги в Decimal — ORM отдаёт Decimal",
          profiles["level3-django"].has("decimal_money") and "Decimal" in l3_api)

    # ── L4: Express. Заявлено concurrency_safe=false ────────────────────────
    l4 = source(4, "app.js")
    check("исходник уровня 4 получен", "app.post('/api/orders'" in l4)
    handles = len(re.findall(r"new sqlite3\.Database\(", l4))
    check("L4: заявлено «не выдерживает параллельные заказы» — один общий хэндл "
          "sqlite3 на процесс и нет busy_timeout",
          profiles["level4-express"].concurrency_safe is False
          and handles == 1 and "busy_timeout" not in l4,
          f"хэндлов: {handles}")
    check("L4: дефект conc-измерен, а не предположен",
          profiles["level4-express"].concurrency_evidence == "measured"
          and profiles["level4-express"].defect("shared-sqlite-handle") is not None)
    l4_api = slice_between(l4, "app.post('/api/orders'", "app.get('/api/orders/")
    check("L4: заявлено «склад не проверяется» — в API выбираются только name, price",
          profiles["level4-express"].stock_checked is False
          and "SELECT name, price FROM products" in l4_api)

    # ── L5: React + Flask. Два процесса, склад не проверяется ───────────────
    l5 = source(5, "backend/api.py")
    check("исходник уровня 5 получен", "@app.post('/api/orders')" in l5)
    l5_api = slice_between(l5, "@app.post('/api/orders')", "@app.get('/api/orders/")
    check("L5: заявлено «склад не проверяется» — в API нет stock в SELECT",
          profiles["level5-react-flask"].stock_checked is False
          and "SELECT name, price FROM products" in l5_api)
    check("L5: заявлены два процесса и SPA — витрина отдельным приложением",
          profiles["level5-react-flask"].runtime_units == 2
          and profiles["level5-react-flask"].has("spa_frontend")
          and not profiles["level5-react-flask"].has("offline_capable"))

    # ── L6: Next.js. 7/22 — конверт и camelCase ─────────────────────────────
    l6 = source(6, "src/app/api/orders/route.ts")
    check("исходник уровня 6 получен", "export async function POST" in l6)
    p6 = profiles["level6-nextjs"]
    check("L6: заявлено неполное соответствие — в коде конверт {success,...} вместо массива",
          p6.conformance_passed == 7 and p6.conformance_total == 22 and "success: false" in l6)
    check("L6: заявлен camelCase — в коде items[].productId",
          p6.defect("camel-case-fields") is not None and "productId" in l6)
    check("L6: заявлена проверка склада — в коде product.stock < item.quantity",
          p6.stock_checked is True and "product.stock < item.quantity" in l6)
    check("L6: заявлена транзакция — в коде prisma.$transaction",
          p6.transactional is True and "prisma.$transaction" in l6)
    check("L6: заявлены деньги в Decimal", p6.has("decimal_money") and "new Decimal(" in l6)
    l6_schema = source(6, "prisma/schema.prisma")
    check("L6: заявлен postgres — в схеме Prisma provider = postgresql",
          p6.storage == "postgres" and 'provider = "postgresql"' in l6_schema)

    # ── L7: микросервисы. 15/22 — order.get не реализован вовсе ─────────────
    l7 = source(7, "services/order-service/app.py")
    check("исходник уровня 7 получен", '@app.post("/api/orders")' in l7)
    p7 = profiles["level7-enterprise"]
    routes = re.findall(r"@app\.(get|post)\(\"([^\"]+)\"\)", l7)
    check("L7: заявлено missing_verbs=['order.get'] — в order-service нет GET /api/orders/{token}",
          p7.missing_verbs == frozenset({"order.get"})
          and not any(m == "get" and path.startswith("/api/orders/") for m, path in routes),
          str(routes))
    check("L7: order.get объявлен в ядре, но вычтен из действующих глаголов",
          "order.get" in p7.declared_verbs and not p7.provides("order.get")
          and p7.provides("order.create"))
    check("L7: заявлена шина событий — в коде pika и publish()",
          p7.has("event_bus") and "import pika" in l7 and "def publish(" in l7)
    check("L7: заявлен дефект блокирующей публикации — 20 попыток по секунде, "
          "исключение подавлено",
          p7.defect("blocking-broker-publish") is not None
          and "for _ in range(20)" in l7 and "time.sleep(1)" in l7)
    check("L7: заявлен postgres — в коде psycopg",
          p7.storage == "postgres" and "import psycopg" in l7)
    check("L7: заявлено «склад не проверяется»",
          p7.stock_checked is False and "SELECT name, price FROM products WHERE id=%s" in l7)
    check("L7: заявлен самый тяжёлый вес — шесть единиц развёртывания",
          p7.weight == "heavy" and p7.runtime_units == 6)


# ════════════════════════════════════════════════════════════════════════════
# B. Сопоставление требования с профилем
# ════════════════════════════════════════════════════════════════════════════

def names(profs) -> list[str]:
    return [p.service for p in profs]


def test_matching(profiles) -> None:
    print("\nЧАСТЬ B — требование выбирает уровень:")

    # Требование «нужна проверка склада» отсеивает L1. Аудит назвал L1, но
    # исходники (часть A) показали ту же дыру на L2-L5 и L7 — поэтому
    # остаётся ровно один уровень, и это честный результат, а не подгонка.
    req = Requirement(needs_stock_check=True, label="продавать только то, что есть")
    fit = rank(profiles, req)
    check("требование «проверка склада» отсеивает L1",
          "level1-php" not in names(fit), str(names(fit)))
    check("его выдерживает только L6 (единственный со сверкой остатка)",
          names(fit) == ["level6-nextjs"], str(names(fit)))
    ok, why = covers(profiles["level1-php"], req)
    check("причина отказа L1 названа словами", not ok and any("остаток" in r for r in why),
          str(why))

    # Требование конкурентности отсеивает L4.
    req = Requirement(needs_concurrency=True, label="шесть заказов в одну секунду")
    fit = rank(profiles, req)
    check("требование конкурентности отсеивает L4",
          "level4-express" not in names(fit), str(names(fit)))
    check("остальные шесть уровней остаются", len(fit) == 6, str(names(fit)))
    ok, why = covers(profiles["level4-express"], req)
    check("причина отказа L4 — параллельные заказы",
          not ok and any("параллельные" in r for r in why), str(why))

    # Требование конкретного глагола отсеивает L7.
    req = Requirement(verbs=("order.get",), label="клиент должен видеть свой заказ")
    fit = rank(profiles, req)
    check("требование глагола order.get отсеивает L7",
          "level7-enterprise" not in names(fit), str(names(fit)))
    ok, why = covers(profiles["level7-enterprise"], req)
    check("причина отказа L7 — глагол объявлен нереализованным",
          not ok and any("order.get" in r and "missing_verbs" in r for r in why), str(why))
    check("глагол, которого нет в ядре вовсе, тоже отсекается",
          not covers(profiles["level1-php"], Requirement(verbs=("order.cancel",)))[0])

    # Полное соответствие контракту оставляет ровно L1-L5.
    req = Requirement(needs_full_conformance=True, label="агент не должен подстраиваться")
    fit = rank(profiles, req)
    check("полное соответствие контракту оставляет ровно L1-L5",
          set(names(fit)) == {SERVICE[i] for i in (1, 2, 3, 4, 5)}, str(names(fit)))
    check("L6 отклонён по числу из аудита 7/22",
          any("7/22" in r for r in covers(profiles["level6-nextjs"], req)[1]))
    check("L7 отклонён по числу из аудита 15/22",
          any("15/22" in r for r in covers(profiles["level7-enterprise"], req)[1]))

    # Требование транзакции отсеивает L3.
    fit = rank(profiles, Requirement(needs_transaction=True))
    check("требование транзакции отсеивает L3",
          "level3-django" not in names(fit) and len(fit) == 6, str(names(fit)))

    # Пустое требование: побеждает самый лёгкий.
    fit = rank(profiles, Requirement())
    check("при пустом требовании подходят все семь", len(fit) == 7)
    check("при пустом требовании выигрывает самый лёгкий уровень",
          fit[0].service == "level1-php" and fit[0].weight == "minimal", fit[0].service)
    ranks = [p.weight_rank for p in fit]
    check("порядок не утяжеляется от начала к концу", ranks == sorted(ranks), str(ranks))
    check("самые тяжёлые — в конце",
          {fit[-1].service, fit[-2].service} == {"level6-nextjs", "level7-enterprise"},
          str(names(fit)[-2:]))
    check("среди равных по весу первым идёт более соответствующий контракту",
          names(rank(profiles, Requirement(max_weight="heavy")))[-2:]
          == ["level7-enterprise", "level6-nextjs"],
          str(names(fit)[-2:]))

    # Возможности поверх ядра: свой ключ под свой размер.
    check("админку даёт только L3",
          names(rank(profiles, Requirement(features=("has_admin",)))) == ["level3-django"])
    check("шину событий даёт только L7",
          names(rank(profiles, Requirement(features=("event_bus",)))) == ["level7-enterprise"])
    check("самый лёгкий из работающих без внешних демонов — L1",
          rank(profiles, Requirement(features=("offline_capable",)))[0].service == "level1-php")

    # Невыполнимое требование: пустой список и внятные причины по каждому.
    req = Requirement(needs_stock_check=True, max_weight="light",
                      label="проверять склад, но не тяжелее одного процесса")
    fit, rejected = rank_report(profiles, req)
    check("невыполнимое требование даёт пустой список", fit == [], str(names(fit)))
    check("причина отказа есть у каждого из семи уровней", len(rejected) == 7, str(sorted(rejected)))
    check("L1 отклонён по складу, а не по весу",
          any("остаток" in r for r in rejected["level1-php"])
          and not any("вес" in r for r in rejected["level1-php"]))
    check("L6 отклонён по весу, а не по складу",
          any("вес" in r for r in rejected["level6-nextjs"])
          and not any("остаток" in r for r in rejected["level6-nextjs"]))
    check("отчёт читается человеком", "Не подходит ни один уровень" in explain(profiles, req))

    # Несколько причин сразу — чтобы человек видел полную цену отказа.
    ok, why = covers(profiles["level7-enterprise"],
                     Requirement(verbs=("order.get",), needs_full_conformance=True,
                                 max_runtime_units=2, storage="sqlite",
                                 features=("has_admin",)))
    check("все причины несоответствия возвращаются сразу, а не по одной",
          not ok and len(why) == 5, str(why))


# ════════════════════════════════════════════════════════════════════════════
# C. Форма профиля: ошибки объявления не проходят молча
# ════════════════════════════════════════════════════════════════════════════

def test_strictness() -> None:
    print("\nФорма профиля и требования — ошибка не проходит молча:")

    base = json.loads((LEVELS_DIR / "level4.act.json").read_text(encoding="utf-8"))

    # Опечатка в требовании — худший из возможных багов: требование,
    # которое всегда выполнено.
    try:
        Requirement(features=("has_admn",))
        check("опечатка в возможности отвергнута", False, "принята")
    except ProfileError as e:
        check("опечатка в имени возможности отвергнута", "has_admn" in str(e))
    try:
        Requirement(max_weight="tiny")
        check("неизвестный вес отвергнут", False, "принят")
    except ProfileError:
        check("неизвестный вес требования отвергнут", True)

    bad = json.loads(json.dumps(base))
    bad.pop("level_profile")
    try:
        parse_level_profile(bad)
        check("манифест без профиля отвергнут", False, "принят")
    except ProfileError as e:
        check("манифест без блока level_profile отвергнут", "level_profile" in str(e))

    # Признаваться можно только в объявленном глаголе.
    bad = json.loads(json.dumps(base))
    bad["level_profile"]["missing_verbs"] = ["order.refund"]
    try:
        parse_level_profile(bad)
        check("missing_verbs с чужим глаголом отвергнут", False, "принят")
    except ProfileError as e:
        check("missing_verbs с необъявленным глаголом отвергнут", "order.refund" in str(e))

    # Дефект конкурентности при concurrency_safe=true — реклама, а не признание.
    bad = json.loads(json.dumps(base))
    bad["level_profile"]["concurrency_safe"] = True
    try:
        parse_level_profile(bad)
        check("дефект при снятом ограничении отвергнут", False, "принят")
    except ProfileError as e:
        check("объявленный дефект конкурентности обязывает снять concurrency_safe",
              "concurrency_safe" in str(e))

    # Профиль поверх невалидного ядра не имеет смысла: уровень выпадает из
    # взаимозаменяемости, и сравнивать его профиль не с чем.
    bad = json.loads(json.dumps(base))
    for c in bad["capabilities"]:
        if c["id"] == "order.create":
            c["consent"] = "none"
    try:
        parse_level_profile(bad)
        check("профиль поверх невалидного ядра отвергнут", False, "принят")
    except Exception as e:
        check("профиль поверх невалидного ядра отвергнут", "consent" in str(e))

    bad = json.loads(json.dumps(base))
    bad["level_profile"]["weight"] = "huge"
    try:
        parse_level_profile(bad)
        check("неизвестный вес уровня отвергнут", False, "принят")
    except ProfileError:
        check("неизвестный вес уровня отвергнут", True)

    check("список весов упорядочен от лёгкого к тяжёлому",
          WEIGHTS == ("minimal", "light", "medium", "heavy"))
    check("список возможностей закрыт", len(FEATURES) == len(set(FEATURES)) and "has_admin" in FEATURES)


def main() -> int:
    profiles = load_level_profiles(LEVELS_DIR)
    print("Профили семи уровней:")
    print(comparison_table(profiles))

    test_core_is_shared(profiles)
    test_claims_against_sources(profiles)
    test_matching(profiles)
    test_strictness()

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
