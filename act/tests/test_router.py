"""Роутер по возможностям: выбор уровня под требование + настоящий fallback по HTTP.

Запуск:  python3 -m act.tests.test_router

Почему тест построен именно так
───────────────────────────────
Главный способ обмануть себя, найденный при аудите экосистемы: проверять модуль
против мока, написанного под те же допущения. `plugin-marketplace` имеет 14/14
зелёных и при этом отвергает все настоящие бэкенды — его мок проверяет не то,
что проверяет контракт.

Поэтому здесь нет ни одного выдуманного профиля в основной части:

  ЧАСТЬ A. Выбор проверяется на НАСТОЯЩИХ семи манифестах уровней
           (`act/manifests/levels/*.act.json`) — тех же, что сверены с
           исходниками уровней в `act/tests/test_profile.py`. Если манифест
           разъедется с кодом уровня, первым покраснеет тот тест, а не этот.

  ЧАСТЬ B. Недоступность уровня моделируется ЧЕСТНО: заведомо закрытый порт
           (взят у ядра и сразу освобождён), а доступность — НАСТОЯЩИЙ
           процесс-сервис NPP-Act, поднятый на своём порту и отвечающий по
           сети. Метод `probe` не подменяется заглушкой: иначе тест проверял бы
           собственное представление о сети, а не сеть. Именно так прошлый
           ai-router и выглядел «работающим».

  ЧАСТЬ C. Строгость формы: роутер обязан ломаться на несогласованных частях,
           а не выбирать наугад.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act.manifest import parse_manifest  # noqa: E402
from act.npp_act.profile import (  # noqa: E402
    ProfileError,
    Requirement,
    load_level_profiles,
    parse_level_profile,
)
from act.npp_act.registry import Registry  # noqa: E402
from act.npp_act.router import (  # noqa: E402
    AVAILABLE,
    NOT_PROBED,
    REFUSED,
    ROUTED,
    UNAVAILABLE,
    UNREACHABLE,
    CapabilityRouter,
    RouterError,
)

LEVELS_DIR = ROOT / "act/manifests/levels"

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


def closed_port() -> int:
    """Порт, который заведомо никто не слушает.

    Берём у ядра свободный порт и сразу отпускаем: так номер не угадан и не
    зашит, а получен от системы. Заглушку вместо сетевого отказа ставить
    нельзя — тогда проверялась бы не недоступность, а наше мнение о ней.
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_is_closed(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def wait_up(url: str, attempts: int = 50) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def fresh_router() -> CapabilityRouter:
    """Роутер на настоящих семи манифестах, адреса — как в манифестах."""
    return CapabilityRouter.from_dir(LEVELS_DIR, timeout=1.0)


# ────────────────────────────────────────────────────────────────────────────
# ЧАСТЬ A. Выбор на настоящих семи профилях, без сети
# ────────────────────────────────────────────────────────────────────────────

def test_setup() -> None:
    print("\nA1. Роутер собран из настоящих манифестов уровней:")
    router = fresh_router()
    check("загружено семь профилей", len(router.profiles) == 7, str(len(router.profiles)))
    check("все семь зарегистрированы в реестре", len(router.registry) == 7)
    check("адрес берётся из реестра", router.base_url("level1-php") == "http://127.0.0.1:8081",
          router.base_url("level1-php"))

    dec = router.route()
    check("пустое требование решается без сети", dec.probed is False)
    check("без сети ни один кандидат не помечен доступным",
          all(c.probe == NOT_PROBED for c in dec.candidates))
    check("пустое требование → самый лёгкий уровень (L1)", dec.chosen == "level1-php", str(dec.chosen))
    check("решение содержит все семь кандидатов", len(dec.candidates) == 7,
          str(len(dec.candidates)))


def test_stock_requirement() -> None:
    print("\nA2. Требование «проверять склад» отсеивает L1:")
    router = fresh_router()
    dec = router.route(Requirement(needs_stock_check=True, label="приём заказов со складом"))

    check("L1 отсеян", dec.rejected_service("level1-php"))
    reasons = dec.reasons_for("level1-php")
    check("причина отсева L1 названа", bool(reasons), "причин нет")
    check("причина — именно непроверяемый склад",
          any("склад" in r for r in reasons), str(reasons))
    check("L1 не попал в число подходящих",
          "level1-php" not in [c.service for c in dec.fitting])
    # Склад закрыт только у L6 (Decimal + защита от перепродажи, 7/22 контракта).
    check("выбран единственный уровень со складом — L6", dec.chosen == "level6-nextjs", str(dec.chosen))
    check("подходящий ровно один", len(dec.fitting) == 1, str(len(dec.fitting)))
    check("объяснение по-русски упоминает склад", "склад" in router.explain(dec))


def test_concurrency_requirement() -> None:
    print("\nA3. Требование «параллельные заказы» отсеивает L4:")
    router = fresh_router()
    dec = router.route(Requirement(needs_concurrency=True, label="заказы под нагрузкой"))

    check("L4 отсеян", dec.rejected_service("level4-express"))
    check("причина — параллельные заказы",
          any("параллельн" in r for r in dec.reasons_for("level4-express")),
          str(dec.reasons_for("level4-express")))
    check("L4 не среди подходящих",
          "level4-express" not in [c.service for c in dec.fitting])
    check("выбран L1 — самый лёгкий из оставшихся", dec.chosen == "level1-php", str(dec.chosen))
    check("остальные шесть уровней подходят", len(dec.fitting) == 6, str(len(dec.fitting)))


def test_verb_requirement() -> None:
    print("\nA4. Требование глагола order.get отсеивает L7:")
    router = fresh_router()

    dec = router.route(Requirement(verbs=("order.get",), label="показать клиенту заказ"))
    check("L7 отсеян", dec.rejected_service("level7-enterprise"))
    check("причина — объявленный missing_verbs",
          any("order.get" in r and "missing_verbs" in r
              for r in dec.reasons_for("level7-enterprise")),
          str(dec.reasons_for("level7-enterprise")))
    check("подходят шесть уровней", len(dec.fitting) == 6, str(len(dec.fitting)))

    # Тот же отсев обязан работать и через аргумент verb: «нужен глагол» —
    # такое же требование к профилю, как «нужен склад».
    dec2 = router.route(verb="order.get")
    check("verb= даёт тот же отсев L7", dec2.rejected_service("level7-enterprise"))
    check("verb= попал в требование", "order.get" in dec2.requirement.verbs)
    check("verb= сохранён в решении", dec2.verb == "order.get")

    dec3 = router.route(Requirement(needs_concurrency=True), verb="order.get")
    check("verb= складывается с остальным требованием",
          dec3.rejected_service("level7-enterprise") and dec3.rejected_service("level4-express"))


def test_refusal_is_not_substitution() -> None:
    print("\nA5. Невыполнимое требование — отказ с причинами, а не произвольный выбор:")
    router = fresh_router()
    dec = router.route(Requirement(
        needs_stock_check=True, needs_full_conformance=True,
        label="склад и полное соответствие контракту",
    ))

    check("вердикт — отказ", dec.verdict == REFUSED, dec.verdict)
    check("уровень не выбран", dec.chosen is None, str(dec.chosen))
    check("подмены на L1 не произошло", dec.chosen != "level1-php")
    check("подходящих нет", dec.fitting == ())
    check("причина названа по каждому из семи уровней", len(dec.rejected) == 7,
          str(len(dec.rejected)))
    check("у каждого отсеянного есть хотя бы одна причина",
          all(len(r) >= 1 for r in dec.rejected.values()))
    check("у L6 причина — неполное соответствие контракту (7/22)",
          any("7/22" in r for r in dec.reasons_for("level6-nextjs")),
          str(dec.reasons_for("level6-nextjs")))
    check("у L1 причина — склад",
          any("склад" in r for r in dec.reasons_for("level1-php")))

    text = router.explain(dec)
    check("объяснение заявляет отказ", "ОТКАЗ" in text)
    check("объяснение говорит, что подмена не выполнена намеренно",
          "подмена" in text or "подмены" in text)
    check("объяснение перечисляет отсеянные уровни", text.count("level") >= 7)


def test_cheapest_among_equals() -> None:
    print("\nA6. Среди подходящих выбирается самый дешёвый в развёртывании:")
    router = fresh_router()

    dec = router.route(Requirement(max_runtime_units=1, label="одна единица развёртывания"))
    order = [c.service for c in dec.fitting]
    check("подходят ровно L1-L4 (по одной единице развёртывания)",
          set(order) == {"level1-php", "level2-flask", "level3-django", "level4-express"},
          str(order))
    check("первым идёт minimal-уровень", order[0] == "level1-php", str(order))
    check("light-уровни раньше medium",
          order.index("level2-flask") < order.index("level3-django") and
          order.index("level4-express") < order.index("level3-django"), str(order))
    check("при равном весе и равном контракте — младший номер уровня",
          order.index("level2-flask") < order.index("level4-express"), str(order))

    # Два кандидата одного веса и одного соответствия: выбор обязан быть
    # детерминированным, иначе «самый лёгкий» каждый раз разный.
    dec2 = router.route(Requirement(max_weight="light", needs_concurrency=True))
    check("вес 'light' и конкурентность оставляют L1 и L2",
          [c.service for c in dec2.fitting] == ["level1-php", "level2-flask"],
          str([c.service for c in dec2.fitting]))
    check("выбран самый лёгкий из двух", dec2.chosen == "level1-php", str(dec2.chosen))
    check("повторный вызов даёт тот же выбор",
          router.route(Requirement(max_weight="light", needs_concurrency=True)).chosen == dec2.chosen)

    dec3 = router.route(Requirement(max_weight="minimal", needs_stock_check=True))
    check("несовместимые требования (minimal + склад) → отказ", dec3.verdict == REFUSED)


def test_registry_is_address_authority() -> None:
    print("\nA7. Адрес вызова берётся из реестра, а не из профиля:")
    router = fresh_router()
    router.registry.rebind("level1-php", "http://127.0.0.1:19081")
    dec = router.route()
    check("выбран по-прежнему L1", dec.chosen == "level1-php")
    check("в решении — перепривязанный адрес", dec.base_url == "http://127.0.0.1:19081",
          str(dec.base_url))
    check("профиль остался с исходным адресом (профиль — не адресная книга)",
          router.profiles["level1-php"].base_url == "http://127.0.0.1:8081")

    # Профиль без манифеста выбрать нельзя: звонить некуда. Это отсев
    # с причиной, а не падение — остальные шесть уровней годны.
    partial = Registry()
    for path in sorted(LEVELS_DIR.glob("*.act.json")):
        if "level7" not in path.name:
            partial.add_file(path)
    router2 = CapabilityRouter(partial, load_level_profiles(LEVELS_DIR), timeout=1.0)
    dec2 = router2.route()
    check("незарегистрированный уровень отсеян, а не выбран",
          dec2.rejected_service("level7-enterprise"))
    check("причина — отсутствие адреса",
          any("реестре" in r for r in dec2.reasons_for("level7-enterprise")),
          str(dec2.reasons_for("level7-enterprise")))
    check("решение всё равно состоялось", dec2.verdict == ROUTED and dec2.chosen == "level1-php")


# ────────────────────────────────────────────────────────────────────────────
# ЧАСТЬ B. Настоящая сеть: проба живости и fallback по подходящим
# ────────────────────────────────────────────────────────────────────────────

def test_probe_is_real(live_port: int) -> None:
    print("\nB1. Проба живости — настоящий HTTP, а не предположение:")
    router = fresh_router()
    dead = closed_port()
    check("взятый порт действительно закрыт", port_is_closed(dead), str(dead))

    router.registry.rebind("level2-flask", f"http://127.0.0.1:{live_port}")
    ok, detail = router.probe("level2-flask")
    check("живой сервис признан доступным", ok, detail)
    check("деталь содержит реальный код ответа", "HTTP 200" in detail, detail)

    router.registry.rebind("level1-php", f"http://127.0.0.1:{dead}")
    ok2, detail2 = router.probe("level1-php")
    check("закрытый порт признан недоступным", not ok2, detail2)
    check("деталь называет причину отказа соединения", "недоступен" in detail2, detail2)

    ok3, detail3 = router.probe("level-which-does-not-exist")
    check("проба незарегистрированного уровня — отказ с причиной",
          not ok3 and "реестре" in detail3, detail3)


def test_fallback_goes_to_next_fitting(live_port: int) -> None:
    print("\nB2. Fallback переходит к следующему ПОДХОДЯЩЕМУ:")
    router = fresh_router()
    dead = closed_port()
    router.registry.rebind("level1-php", f"http://127.0.0.1:{dead}")
    router.registry.rebind("level2-flask", f"http://127.0.0.1:{live_port}")

    dec = router.route_live()
    check("вердикт — выбран уровень", dec.verdict == ROUTED, dec.verdict)
    check("решение опирается на пробу", dec.probed is True)
    check("первый по предпочтению (L1) пропущен как недоступный",
          dec.skipped_unreachable == ("level1-php",), str(dec.skipped_unreachable))
    check("выбран следующий подходящий — L2", dec.chosen == "level2-flask", str(dec.chosen))
    check("выбранный помечен доступным",
          [c.probe for c in dec.candidates if c.service == "level2-flask"] == [AVAILABLE])
    check("пропущенный помечен недоступным",
          [c.probe for c in dec.candidates if c.service == "level1-php"] == [UNAVAILABLE])
    check("до остальных подходящих очередь не дошла — они не пробованы",
          all(c.probe == NOT_PROBED for c in dec.fitting
              if c.service not in ("level1-php", "level2-flask")))
    check("fallback записан в объяснение", "fallback" in dec.reason, dec.reason)
    check("объяснение подчёркивает «а не к любому отвечающему»",
          "не к любому" in router.explain(dec))


def test_fallback_never_substitutes(live_port: int) -> None:
    print("\nB3. Живой, но непригодный уровень не получает заказ:")
    # L4 — единственный запущенный, и он же единственный отсеянный требованием
    # конкурентности. Старый ai-router в этой ситуации выбрал бы его как
    # «любой живой» и молча отдал бы заказы уровню, который их теряет.
    router = fresh_router()
    router.registry.rebind("level4-express", f"http://127.0.0.1:{live_port}")
    for svc in ("level1-php", "level2-flask", "level3-django", "level5-react-flask",
                "level6-nextjs", "level7-enterprise"):
        router.registry.rebind(svc, f"http://127.0.0.1:{closed_port()}")

    dec = router.route_live(Requirement(needs_concurrency=True, label="заказы под нагрузкой"))
    check("вердикт — недоступность, а не отказ по требованию",
          dec.verdict == UNREACHABLE, dec.verdict)
    check("уровень не выбран", dec.chosen is None, str(dec.chosen))
    check("единственный живой L4 НЕ выбран", dec.chosen != "level4-express")
    check("L4 отсеян по требованию, а не по сети", dec.rejected_service("level4-express"))
    check("L4 даже не пробовался по сети",
          [c.probe for c in dec.candidates if c.service == "level4-express"] == [NOT_PROBED])
    check("все подходящие признаны недоступными",
          len(dec.skipped_unreachable) == len(dec.fitting) == 6,
          f"{dec.skipped_unreachable} / {len(dec.fitting)}")
    text = router.explain(dec)
    check("объяснение отличает недоступность от непригодности",
          "не ответил" in text and "не выдерживает параллельные заказы" in text)

    # А теперь поднимаем подходящий уровень — и он выигрывает, минуя живой L4.
    router.registry.rebind("level2-flask", f"http://127.0.0.1:{live_port}")
    dec2 = router.route_live(Requirement(needs_concurrency=True))
    check("с запуском подходящего уровня решение состоялось", dec2.verdict == ROUTED, dec2.verdict)
    check("выбран подходящий L2, а не живой L4", dec2.chosen == "level2-flask", str(dec2.chosen))
    check("L1 пропущен как недоступный", "level1-php" in dec2.skipped_unreachable,
          str(dec2.skipped_unreachable))

    # Требование, которое не покрывает никто: сеть тут ничего не меняет.
    dec3 = router.route_live(Requirement(needs_stock_check=True, needs_full_conformance=True))
    check("невыполнимое требование и при живом сервисе даёт отказ",
          dec3.verdict == REFUSED and dec3.chosen is None, dec3.verdict)
    check("при отказе по требованию сеть не опрашивается вовсе", dec3.probed is False)


# ────────────────────────────────────────────────────────────────────────────
# ЧАСТЬ C. Строгость формы: роутер ломается, а не угадывает
# ────────────────────────────────────────────────────────────────────────────

def test_strictness(live_port: int) -> None:
    print("\nC. Строгость формы:")
    try:
        CapabilityRouter(Registry(), {})
        check("пустой набор профилей отвергнут", False, "принят")
    except RouterError:
        check("пустой набор профилей отвергнут", True)

    router = fresh_router()
    try:
        router.base_url("level0-unknown")
        check("адрес неизвестного уровня — ошибка", False, "вернулся адрес")
    except RouterError:
        check("адрес неизвестного уровня — ошибка", True)

    try:
        router.route(Requirement(features=("has_admn",)))
        check("опечатка в возможности отвергнута", False, "принята")
    except ProfileError as e:
        check("опечатка в возможности отвергнута", "has_admn" in str(e))

    try:
        router.route().reasons_for("level0-unknown")
        check("причины по неучаствовавшему уровню — ошибка", False, "вернулись")
    except KeyError:
        check("причины по неучаствовавшему уровню — ошибка", True)

    base = json.loads((LEVELS_DIR / "level1.act.json").read_text(encoding="utf-8"))

    # Проба обязана быть безопасным чтением: «проверить живость» через POST —
    # это уже действие, а для order.create это был бы оформленный заказ.
    mutated = json.loads(json.dumps(base))
    for cap in mutated["capabilities"]:
        if cap["id"] == "health.check":
            cap["binding"]["method"] = "POST"
    mutated["base_url"] = f"http://127.0.0.1:{live_port}"
    r2 = CapabilityRouter(
        Registry().add(parse_manifest(mutated)),
        {mutated["service"]: parse_level_profile(mutated)},
        timeout=1.0,
    )
    ok, detail = r2.probe("level1-php")
    check("проба не-GET глаголом отклонена, несмотря на живой сервис", not ok, detail)
    check("причина названа прямо", "последствие" in detail, detail)
    dec = r2.route_live()
    check("непроверяемый уровень не выбирается по сети", dec.verdict == UNREACHABLE, dec.verdict)

    # Уровень без read-глагола для пробы непроверяем — и это честный ответ.
    without = json.loads(json.dumps(base))
    without["capabilities"] = [c for c in without["capabilities"] if c["id"] != "health.check"]
    without["base_url"] = f"http://127.0.0.1:{live_port}"
    r3 = CapabilityRouter(
        Registry().add(parse_manifest(without)),
        {without["service"]: parse_level_profile(without)},
        timeout=1.0,
    )
    ok3, detail3 = r3.probe("level1-php")
    check("уровень без health.check признан непроверяемым",
          not ok3 and "непроверяема" in detail3, detail3)
    check("требование health.check отсеивает такой уровень",
          r3.route(verb="health.check").verdict == REFUSED)

    # Вердикты — три разных исхода, и путать их нельзя.
    check("вердикты различны", len({ROUTED, REFUSED, UNREACHABLE}) == 3)
    check("состояния пробы различны", len({NOT_PROBED, AVAILABLE, UNAVAILABLE}) == 3)


def main() -> int:
    port = closed_port()  # свободный порт у ядра — для настоящего сервиса
    db = Path(tempfile.gettempdir()) / "npp_act_router_test.db"
    if db.exists():
        db.unlink()
    proc = subprocess.Popen(
        [sys.executable, "-m", "act.services.venue.server",
         "--port", str(port), "--db", str(db), "--reset"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_up(f"http://127.0.0.1:{port}/api/health"):
            print("✗ настоящий сервис для пробы не поднялся")
            return 1
        print(f"Настоящий NPP-Act-сервис поднят на :{port} — он играет роль живого уровня")

        test_setup()
        test_stock_requirement()
        test_concurrency_requirement()
        test_verb_requirement()
        test_refusal_is_not_substitution()
        test_cheapest_among_equals()
        test_registry_is_address_authority()
        test_probe_is_real(port)
        test_fallback_goes_to_next_fitting(port)
        test_fallback_never_substitutes(port)
        test_strictness(port)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
