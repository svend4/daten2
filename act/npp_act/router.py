"""Роутер по возможностям: уровень выбирается под требование, а не «любой из равных».

Зачем этот модуль существует
────────────────────────────
Сегодняшний ai-router в daten2 выбирает бэкенд по латентности и цене — то есть
исходит из того, что уровни взаимозаменяемы. Для ЯДРА контракта это верно:
четыре глагола одинаковы у всех семи (это проверяет `act/tests/test_profile.py`).
Выше ядра равенства нет, и аудит показал цену этой разницы:

  · L1 не смотрит на склад — заказ 99999 роз при остатке 48 проходит с HTTP 201;
  · L4 рассыпается при шести одновременных заказах (один общий хэндл sqlite3);
  · L7 вообще не реализует `order.get`;
  · L6 закрывает перепродажу и считает деньги в Decimal, но держит 7/22 контракта.

Роутер, который этого не знает, обязательно подставит самый быстрый из «равных»
и получит тот, который не умеет нужного. Поэтому здесь выбор строится иначе:

    НЕ «самый быстрый из равных», А «тот, чей объявленный профиль покрывает
    требование задачи»; среди покрывающих — самый дешёвый в развёртывании.

Это и есть метафора владельца, доведённая до кода: ключ подбирается по размеру
гайки, а не по тому, какой ближе лежит.

Главное правило, от которого нельзя отступать
─────────────────────────────────────────────
РОУТЕР НЕ ПОДМЕНЯЕТ УРОВЕНЬ МОЛЧА. Если требование — «проверять склад», а ни
один подходящий уровень не отвечает, это ОТКАЗ С ОБЪЯСНЕНИЕМ, а не тихий выбор
L1. Тихая подмена — ровно тот класс ошибок, ради которого существует весь слой
удержания: она не видна ни в логе, ни в ответе, последствие наступает у клиента
(проданный несуществующий товар), а агент при этом отчитался об успехе. Отказ
дорог один раз и сразу; молчаливая подмена дешева сейчас и дорога потом.

Отсюда три следствия в API:
  1. у каждого отсеянного кандидата есть список причин по-русски — отказ обязан
     быть объяснимым, иначе его начнут обходить;
  2. «не подходит ни один» (`REFUSED`) и «подходящие есть, но не отвечают»
     (`UNREACHABLE`) — РАЗНЫЕ исходы: первое лечится требованием, второе —
     запуском уровня, и путать их нельзя;
  3. fallback идёт по списку ПОДХОДЯЩИХ, а не по всем доступным: живой, но
     непригодный уровень не получает заказ только за то, что он живой.

Граница доверия (SPEC-NPP-ACT.md §10.1): профиль — ЗАЯВЛЕНИЕ уровня о себе.
Роутер сопоставляет заявления с требованием и проверяет по сети только одно —
отвечает ли уровень вообще. Правдивость заявлений проверяется отдельно и
независимо: `act/tests/test_profile.py` сверяет каждое поле с исходниками.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .manifest import Manifest
from .profile import LevelProfile, Requirement, covers, load_level_profiles, rank_report
from .registry import Registry

#: Глагол, которым роутер проверяет живость. Проверять живость ЦЕЛЕВЫМ глаголом
#: нельзя: «проба» уровня через `order.create` оформит заказ. Поэтому проба
#: допустима только read-глаголом, и это требование проверяется в `probe`.
HEALTH_VERB = "health.check"

#: Исходы маршрутизации. Разделение — смысловое, см. шапку модуля.
ROUTED = "routed"            # выбран уровень, покрывающий требование
REFUSED = "refused"          # требование не покрывает ни один уровень
UNREACHABLE = "unreachable"  # покрывающие есть, но ни один не отвечает по HTTP

#: Состояния пробы. «Не проверяли» обязано отличаться от «доступен»: иначе
#: решение, принятое без сети, выглядит как подтверждённое сетью.
NOT_PROBED = "not_probed"
AVAILABLE = "available"
UNAVAILABLE = "unavailable"


class RouterError(ValueError):
    """Роутер собран из несогласованных частей (реестр и профили не бьются)."""


@dataclass(frozen=True)
class Candidate:
    """Один уровень в решении роутера — с приговором и его причиной.

    Кандидат присутствует в решении ВСЕГДА, даже отсеянный: отказ без перечня
    отсеянных нельзя ни проверить, ни оспорить, а значит его начнут обходить
    вручную — и подмена вернётся, только уже вне роутера.
    """

    service: str
    level: int
    weight: str
    fits: bool
    reasons: tuple[str, ...] = ()
    probe: str = NOT_PROBED
    probe_detail: str = ""
    base_url: str = ""

    @property
    def usable(self) -> bool:
        """Пригоден к исполнению: покрывает требование И отвечает по сети."""
        return self.fits and self.probe == AVAILABLE


@dataclass(frozen=True)
class RouteDecision:
    """Решение роутера: что выбрано, почему и кто отсеян.

    Решение намеренно не содержит самого исполнения. Как и у губернатора,
    допуск отделён от действия: решение можно записать в журнал, показать
    человеку и переиграть, не создав последствий.
    """

    requirement: Requirement
    verb: str | None
    verdict: str
    reason: str
    chosen: str | None = None
    chosen_profile: LevelProfile | None = None
    base_url: str | None = None
    candidates: tuple[Candidate, ...] = ()
    skipped_unreachable: tuple[str, ...] = ()
    probed: bool = False
    checks: dict[str, Any] = field(default_factory=dict)

    @property
    def routed(self) -> bool:
        return self.verdict == ROUTED

    @property
    def fitting(self) -> tuple[Candidate, ...]:
        """Подходящие в порядке предпочтения — порядок задаёт `profile.rank_report`."""
        return tuple(c for c in self.candidates if c.fits)

    @property
    def rejected(self) -> dict[str, tuple[str, ...]]:
        return {c.service: c.reasons for c in self.candidates if not c.fits}

    def reasons_for(self, service: str) -> tuple[str, ...]:
        for c in self.candidates:
            if c.service == service:
                return c.reasons
        raise KeyError(f"уровень '{service}' не участвовал в выборе")

    def rejected_service(self, service: str) -> bool:
        return service in self.rejected


class CapabilityRouter:
    """Выбор уровня по профилю возможностей, а не по латентности.

    Реестр и профили разделены сознательно:
      · ПРОФИЛЬ отвечает на вопрос «что уровень умеет» — это заявление,
        проверяемое по исходникам;
      · РЕЕСТР отвечает на вопрос «куда стучаться» — адрес меняется от
        развёртывания к развёртыванию (`Registry.rebind`), и адрес из профиля
        после перепривязки был бы устаревшим.
    Поэтому `base_url` роутер всегда берёт из реестра, а возможности — из
    профиля. Смешивать эти два источника нельзя: именно на таком смешении
    роутер и начинает звонить не туда, куда решал.
    """

    def __init__(
        self,
        registry: Registry,
        profiles: dict[str, LevelProfile],
        *,
        timeout: float = 1.5,
    ) -> None:
        if not profiles:
            raise RouterError("роутеру передан пустой набор профилей уровней")
        self.registry = registry
        self.profiles = dict(profiles)
        self.timeout = timeout

    # ---------- сборка ----------

    @classmethod
    def from_dir(cls, directory: str | Path, *, timeout: float = 1.5) -> "CapabilityRouter":
        """Собрать роутер из каталога манифестов уровней (`act/manifests/levels`)."""
        registry = Registry().load_dir(directory)
        return cls(registry, load_level_profiles(directory), timeout=timeout)

    # ---------- вспомогательное ----------

    def _manifest(self, service: str) -> Manifest | None:
        return self.registry.manifest(service)

    def base_url(self, service: str) -> str:
        man = self._manifest(service)
        if man is None:
            raise RouterError(f"уровень '{service}' есть в профилях, но не зарегистрирован в реестре")
        return man.base_url

    # ---------- проба живости ----------

    def probe(self, service: str) -> tuple[bool, str]:
        """Отвечает ли уровень по HTTP → (да/нет, человекочитаемая деталь).

        Проба — настоящий сетевой вызов read-глагола, а не предположение: в
        решении должно стоять «ответил HTTP 200», а не «порт по идее открыт».

        Два отдельных решения, о которые легко споткнуться:

        · Проба делается ТОЛЬКО read-глаголом `health.check`. Проверять живость
          целевым глаголом соблазнительно (один вызов вместо двух), но для
          `order.create` это означает оформленный заказ ради диагностики —
          последствие вместо проверки. Если уровень не объявил read-глагола для
          пробы, он непроверяем, и это честный ответ, а не повод постучаться
          во что-нибудь другое.

        · Доступным считается только ответ со статусом < 400. Процесс, который
          поднялся и отдаёт 404 на `/api/health`, жив, но контракта за ним нет;
          отправить туда заказ — та же молчаливая подмена, только на уровень,
          которого там нет.
        """
        man = self._manifest(service)
        if man is None:
            return False, "уровень не зарегистрирован в реестре"

        cap = man.verb(HEALTH_VERB)
        if cap is None:
            return False, f"уровень не объявил '{HEALTH_VERB}' — живость непроверяема"
        if cap.effect != "read" or cap.binding.get("method") != "GET":
            return False, (
                f"'{HEALTH_VERB}' на этом уровне — не безопасное чтение "
                f"(effect={cap.effect}, method={cap.binding.get('method')}); "
                f"проба такой пробой создала бы последствие"
            )

        url = man.base_url + cap.binding["path"]
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status >= 400:
                    return False, f"{url} ответил HTTP {resp.status}"
                return True, f"{url} ответил HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            return False, f"{url} ответил HTTP {e.code}"
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            return False, f"{url} недоступен: {reason}"

    # ---------- главный вход ----------

    def route(
        self,
        requirement: Requirement | None = None,
        verb: str | None = None,
        *,
        live: bool = False,
    ) -> RouteDecision:
        """Требование (+ при необходимости конкретный глагол) → решение о уровне.

        `live=False` — чистый выбор по профилям, без сети: решение можно
        получить и показать человеку, ничего не задев. `live=True` добавляет
        пробу и fallback (см. `route_live`).

        `verb` добавляется к требуемым глаголам, а не проверяется отдельно:
        «нужен order.get» — такое же требование к профилю, как «нужен склад»,
        и обязано отсеивать так же (L7 объявил `order.get` в missing_verbs).
        """
        requirement = requirement or Requirement()
        if verb:
            requirement = Requirement(
                verbs=tuple(dict.fromkeys(requirement.verbs + (verb,))),
                needs_transaction=requirement.needs_transaction,
                needs_stock_check=requirement.needs_stock_check,
                needs_concurrency=requirement.needs_concurrency,
                needs_full_conformance=requirement.needs_full_conformance,
                max_weight=requirement.max_weight,
                max_runtime_units=requirement.max_runtime_units,
                storage=requirement.storage,
                features=requirement.features,
                label=requirement.label,
            )

        # Уровень, которого нет в реестре, выбрать нельзя — звонить было бы
        # некуда. Это отсев с причиной, а не исключение: остальные шесть
        # уровней по-прежнему годны, и решение обязано состояться.
        known: list[LevelProfile] = []
        unregistered: list[Candidate] = []
        for svc, prof in self.profiles.items():
            if self._manifest(svc) is None:
                unregistered.append(Candidate(
                    service=svc, level=prof.level, weight=prof.weight, fits=False,
                    reasons=("уровень не зарегистрирован в реестре: адреса для вызова нет",),
                ))
            else:
                known.append(prof)

        fitting, rejected = rank_report(known, requirement)

        candidates: list[Candidate] = [
            Candidate(service=p.service, level=p.level, weight=p.weight, fits=True,
                      base_url=self.base_url(p.service))
            for p in fitting
        ]
        for prof in sorted(known, key=lambda p: p.level):
            if prof.service in rejected:
                candidates.append(Candidate(
                    service=prof.service, level=prof.level, weight=prof.weight,
                    fits=False, reasons=tuple(rejected[prof.service]),
                    base_url=self.base_url(prof.service),
                ))
        candidates.extend(unregistered)

        checks = {
            "levels_total": len(self.profiles),
            "fitting": len(fitting),
            "rejected": len(candidates) - len(fitting),
        }

        if not fitting:
            # Отказ, а не «ну хоть что-нибудь». Причины уже лежат в кандидатах,
            # поэтому человеку видно, какое именно требование стоит дороже
            # всего и что придётся снять, если он решит его снять.
            return RouteDecision(
                requirement=requirement, verb=verb, verdict=REFUSED,
                reason=(f"требование «{requirement.human()}» не покрывает ни один из "
                        f"{len(self.profiles)} уровней; подмена на непригодный уровень "
                        f"запрещена — см. причины по каждому"),
                candidates=tuple(candidates), probed=False, checks=checks,
            )

        if not live:
            winner = fitting[0]
            return RouteDecision(
                requirement=requirement, verb=verb, verdict=ROUTED,
                reason=self._why_winner(winner, fitting),
                chosen=winner.service, chosen_profile=winner,
                base_url=self.base_url(winner.service),
                candidates=tuple(candidates), probed=False, checks=checks,
            )

        return self._route_live(requirement, verb, fitting, candidates, checks)

    def route_live(
        self,
        requirement: Requirement | None = None,
        verb: str | None = None,
    ) -> RouteDecision:
        """То же, что `route(..., live=True)`: выбор с пробой по HTTP и fallback."""
        return self.route(requirement, verb, live=True)

    # ---------- fallback ----------

    def _route_live(
        self,
        requirement: Requirement,
        verb: str | None,
        fitting: list[LevelProfile],
        candidates: list[Candidate],
        checks: dict[str, Any],
    ) -> RouteDecision:
        """Пройти подходящие по порядку предпочтения и взять первый отвечающий.

        Ключевое отличие от старого ai-router: обход идёт ПО СПИСКУ ПОДХОДЯЩИХ.
        Старый роутер при недоступности выбранного брал любой живой — и этим
        превращал сбой развёртывания в подмену возможностей: задача, которой
        нужен склад, молча уезжала на уровень без склада. Здесь непригодный
        уровень не рассматривается даже тогда, когда он единственный живой.
        """
        probed: dict[str, Candidate] = {}
        skipped: list[str] = []
        winner: LevelProfile | None = None

        for prof in fitting:
            ok, detail = self.probe(prof.service)
            probed[prof.service] = Candidate(
                service=prof.service, level=prof.level, weight=prof.weight, fits=True,
                probe=AVAILABLE if ok else UNAVAILABLE, probe_detail=detail,
                base_url=self.base_url(prof.service),
            )
            if ok:
                winner = prof
                break
            skipped.append(prof.service)

        # Подходящие, до которых очередь не дошла, остаются непробованными —
        # и так и помечены: NOT_PROBED. Честнее, чем «доступен по умолчанию».
        merged = tuple(probed.get(c.service, c) for c in candidates)
        checks = dict(checks, probed=len(probed), skipped_unreachable=len(skipped))

        if winner is None:
            return RouteDecision(
                requirement=requirement, verb=verb, verdict=UNREACHABLE,
                reason=(f"требование «{requirement.human()}» покрывают {len(fitting)} уровня(ей), "
                        f"но ни один не ответил по HTTP; непригодные уровни не подставляются "
                        f"даже если они запущены"),
                candidates=merged, skipped_unreachable=tuple(skipped),
                probed=True, checks=checks,
            )

        reason = self._why_winner(winner, fitting)
        if skipped:
            reason += (
                "; fallback: " + ", ".join(skipped) +
                " не ответили по HTTP, перешли к следующему ПОДХОДЯЩЕМУ "
                "(а не к любому отвечающему)"
            )
        return RouteDecision(
            requirement=requirement, verb=verb, verdict=ROUTED, reason=reason,
            chosen=winner.service, chosen_profile=winner,
            base_url=self.base_url(winner.service),
            candidates=merged, skipped_unreachable=tuple(skipped),
            probed=True, checks=checks,
        )

    # ---------- объяснение ----------

    @staticmethod
    def _why_winner(winner: LevelProfile, fitting: list[LevelProfile]) -> str:
        """Почему именно этот — одной строкой, в терминах цены, а не скорости."""
        rivals = [p for p in fitting if p.service != winner.service]
        base = (f"L{winner.level} {winner.service} покрывает требование; "
                f"вес развёртывания '{winner.weight}' "
                f"({winner.runtime_units} ед.), контракт "
                f"{winner.conformance_passed}/{winner.conformance_total}")
        if not rivals:
            return base + "; других покрывающих уровней нет"
        same_weight = [p for p in rivals if p.weight == winner.weight]
        if same_weight:
            return (base + "; при равном весе с " +
                    ", ".join(f"L{p.level}" for p in same_weight) +
                    " выбран по соответствию контракту и младшему номеру уровня")
        return base + "; это самый лёгкий из " + str(len(fitting)) + " покрывающих"

    def explain(self, decision: RouteDecision) -> str:
        """Решение словами — то, что читает человек и что ложится в журнал."""
        head = {
            ROUTED: "ВЫБРАН УРОВЕНЬ",
            REFUSED: "ОТКАЗ: требование не покрыто",
            UNREACHABLE: "ОТКАЗ: покрывающие уровни не отвечают",
        }[decision.verdict]

        lines = [
            f"{head}",
            f"Требование: {decision.requirement.human()}",
        ]
        if decision.verb:
            lines.append(f"Глагол: {decision.verb}")
        if decision.chosen:
            lines.append(f"Выбран: {decision.chosen} → {decision.base_url}")
        lines.append(f"Причина: {decision.reason}")

        fitting = decision.fitting
        if fitting:
            lines.append("Покрывают требование (в порядке предпочтения):")
            for i, c in enumerate(fitting, 1):
                mark = {AVAILABLE: "отвечает", UNAVAILABLE: "не отвечает",
                        NOT_PROBED: "не проверялся"}[c.probe]
                tail = f" — {c.probe_detail}" if c.probe_detail else ""
                lines.append(f"  {i}. L{c.level} {c.service} [{c.weight}] {mark}{tail}")
        else:
            lines.append("Покрывающих уровней нет.")

        if decision.rejected:
            lines.append("Отсеяны:")
            for c in decision.candidates:
                if c.fits:
                    continue
                lines.append(f"  · L{c.level} {c.service}:")
                for r in c.reasons:
                    lines.append(f"      - {r}")

        if decision.verdict != ROUTED:
            lines.append(
                "Подмена уровня, не удовлетворяющего требованию, не выполнена "
                "намеренно: тихая подмена отдаёт последствие клиенту, а агенту "
                "показывает успех."
            )
        return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# Ручной просмотр: «какой ключ под какую гайку». Не часть API.
# ────────────────────────────────────────────────────────────────────────────

def _demo_requirements() -> list[Requirement]:
    return [
        Requirement(label="посмотреть каталог", verbs=("catalog.list",)),
        Requirement(label="приём заказов с проверкой склада", needs_stock_check=True),
        Requirement(label="приём заказов под нагрузкой",
                    needs_concurrency=True, needs_full_conformance=True),
        Requirement(label="выдать клиенту статус заказа", verbs=("order.get",)),
        Requirement(label="склад + полное соответствие контракту",
                    needs_stock_check=True, needs_full_conformance=True),
    ]


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[1] / "manifests" / "levels"
    router = CapabilityRouter.from_dir(here)
    for req in _demo_requirements():
        print("=" * 70)
        print(router.explain(router.route(req)))
    print("=" * 70)
