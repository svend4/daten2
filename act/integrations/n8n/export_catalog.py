"""Экспорт каталога возможностей NPP-Act в форму, пригодную для n8n.

Зачем отдельный экспортёр, если у реестра уже есть `Registry.catalog()`.
Каталог реестра — короткая сводка для человека: сервис, глагол, эффект, согласие.
Оркестратору этого мало. Чтобы n8n мог построить узел, ему нужны ещё три вещи:

  1. схема входа (`input`) — иначе нечего подставить в поля узла;
  2. способ идемпотентности — иначе узел не знает, что ключ обязателен
     (а для `commit`/`money` он обязателен, см. SPEC §4.5);
  3. адрес шлюза и форма запроса к нему — иначе узел пойдёт в сервис напрямую,
     минуя губернатора, и весь слой удержания перестанет существовать.

Последнее — главное. Экспорт сознательно НЕ отдаёт `base_url` сервиса как адрес
вызова: он отдаёт `binding` только как справку о форме и отдельно — единственный
допустимый адрес действия, эндпоинт шлюза `/act/perform`. Каталог описывает
последствия; исполнять их вправе только рантайм.

Запуск (оба способа равноправны):
    python3 -m act.integrations.n8n.export_catalog --format table
    python3 act/integrations/n8n/export_catalog.py --format json --out /tmp/catalog.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from act.npp_act import Capability, Manifest, Registry  # noqa: E402
from act.npp_act.manifest import ManifestError  # noqa: E402

#: Эндпоинт рантайма, через который узел обязан ходить. Не адрес сервиса.
PERFORM_ENDPOINT = "/act/perform"
CATALOG_ENDPOINT = "/act/catalog"
CONFIRM_ENDPOINT = "/act/confirm"

#: Разделение ролей — печатается в сам каталог, чтобы его нельзя было прочитать
#: как «список HTTP-вызовов, которые можно сделать».
ROLES = {
    "catalog": "Наутилус — что существует и что с чем совместимо",
    "consequence": "NPP-Act — что произойдёт, если это вызвать",
    "execution": "n8n — как это вызвать и связать в цепочку",
    "restraint": "губернатор + журнал — вправе ли агент это вызывать",
}


def operation(manifest: Manifest, cap: Capability) -> dict[str, Any]:
    """Одна операция каталога: последствие + то, что нужно узлу для построения формы."""
    slot = cap.idempotency_slot()
    return {
        "service": manifest.service,
        "service_title": manifest.title,
        "profile": manifest.profile,
        "q6": manifest.q6,
        "verb": cap.id,
        "title": cap.title,
        "description": cap.description,
        # ── последствие ─────────────────────────────────────────────
        "effect": cap.effect,
        "severity": cap.severity,
        "reversible": cap.reversible,
        "reverse": cap.reverse,
        "expires_s": cap.expires_s,
        "money": cap.cost.get("money"),
        "currency": cap.cost.get("currency"),
        "time_s": cap.cost.get("time_s"),
        "consent": cap.consent,
        "idempotency": cap.idempotency,
        "idempotency_in": slot[0] if slot else None,
        "idempotency_name": slot[1] if slot else None,
        # ── что из этого следует для узла ───────────────────────────
        "requires_human": cap.consent in ("confirm", "two_party"),
        "requires_idempotency_key": cap.is_committing,
        "requires_money_ceiling": cap.money_is_variable,
        "recommended_dry_run": cap.effect != "read",
        # ── форма вызова: справочно, исполняет её рантайм, не узел ──
        "binding": {
            "protocol": cap.binding.get("protocol"),
            "method": cap.binding.get("method"),
            "path": cap.binding.get("path"),
            "note": "форма вызова внутри рантайма; узел n8n вызывает "
                    f"POST {PERFORM_ENDPOINT}, а не этот путь",
        },
        "input": cap.input,
        "output": cap.output,
    }


def build(registry: Registry, gateway_url: str) -> dict[str, Any]:
    """Собрать каталог целиком, включая контракт шлюза и сводку по эффектам."""
    ops: list[dict[str, Any]] = []
    for service in registry.services():
        man = registry.manifest(service)
        for cap in man:
            ops.append(operation(man, cap))

    by_effect: dict[str, int] = {}
    for op in ops:
        by_effect[op["effect"]] = by_effect.get(op["effect"], 0) + 1

    return {
        "npp_act": "1.0",
        "generated_by": "act.integrations.n8n.export_catalog",
        "roles": ROLES,
        "gateway": {
            "base_url": gateway_url.rstrip("/"),
            "perform": PERFORM_ENDPOINT,
            "catalog": CATALOG_ENDPOINT,
            "confirm": CONFIRM_ENDPOINT,
            "request": {
                "service": "<service>",
                "verb": "<verb>",
                "payload": {},
                "idempotency_key": "<ключ или null>",
                "dry_run": True,
            },
            "note": "единственная дверь действия: прямой вызов сервиса обходит "
                    "губернатора и журнал и потому запрещён",
        },
        "services": [
            {
                "value": name,
                "name": registry.manifest(name).title,
                "profile": registry.manifest(name).profile,
                "verbs": len(registry.manifest(name).capabilities),
            }
            for name in registry.services()
        ],
        "counts": {"services": len(registry), "operations": len(ops), "by_effect": by_effect},
        "operations": ops,
    }


def table(catalog: dict[str, Any]) -> str:
    """Таблица для глаза: в первую очередь видно последствие, а не путь."""
    head = ("СЕРВИС", "ГЛАГОЛ", "ЭФФЕКТ", "СОГЛАСИЕ", "ОБРАТИМ", "ДЕНЬГИ", "ИДЕМПОТЕНТНОСТЬ")
    rows = [
        (
            op["service"],
            op["verb"],
            op["effect"],
            op["consent"],
            "да" if op["reversible"] else "нет",
            "переменная" if op["money"] == "variable" else str(op["money"]),
            op["idempotency"],
        )
        for op in catalog["operations"]
    ]
    width = [max(len(str(r[i])) for r in (head, *rows)) for i in range(len(head))]
    line = "  ".join("─" * w for w in width)
    out = [
        "  ".join(str(h).ljust(width[i]) for i, h in enumerate(head)),
        line,
        *("  ".join(str(c).ljust(width[i]) for i, c in enumerate(r)) for r in rows),
        line,
    ]
    counts = catalog["counts"]
    effects = ", ".join(f"{k}={v}" for k, v in sorted(counts["by_effect"].items()))
    out.append(f"сервисов {counts['services']}, операций {counts['operations']} ({effects})")
    out.append(f"действие исполняется только через POST "
               f"{catalog['gateway']['base_url']}{PERFORM_ENDPOINT}")
    return "\n".join(out)


def load(manifests: Path, levels: bool) -> Registry:
    """Загрузить манифесты так же, как это делает рантайм (включая подкаталог levels)."""
    registry = Registry().load_dir(manifests)
    sub = manifests / "levels"
    if levels and sub.is_dir():
        registry.load_dir(sub)
    return registry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="export_catalog",
        description="Экспорт каталога глаголов NPP-Act для n8n",
    )
    ap.add_argument("--manifests", default=str(ROOT / "act" / "manifests"),
                    help="каталог с *.act.json (по умолчанию act/manifests)")
    ap.add_argument("--no-levels", action="store_true",
                    help="не подхватывать manifests/levels (семь уровней daten2)")
    ap.add_argument("--gateway", default="http://127.0.0.1:8200",
                    help="адрес рантайм-шлюза NPP-Act")
    ap.add_argument("--format", choices=("json", "table"), default="json")
    ap.add_argument("--out", help="записать в файл вместо вывода на stdout")
    ap.add_argument("--service", action="append", default=[],
                    help="оставить только эти сервисы (можно повторять)")
    ap.add_argument("--effect", action="append", default=[],
                    help="оставить только эти эффекты (read/reserve/commit/money/destroy)")
    ap.add_argument("--indent", type=int, default=2)
    args = ap.parse_args(argv)

    path = Path(args.manifests)
    if not path.is_dir():
        print(f"нет каталога манифестов: {path}", file=sys.stderr)
        return 2

    try:
        registry = load(path, not args.no_levels)
    except (ManifestError, OSError, json.JSONDecodeError) as e:
        # Невалидный манифест — отказ, а не частичный каталог: половина объявленных
        # последствий хуже, чем их отсутствие.
        print(f"манифест отвергнут: {e}", file=sys.stderr)
        return 2

    if not len(registry):
        print(f"в {path} не нашлось ни одного манифеста *.act.json", file=sys.stderr)
        return 2

    catalog = build(registry, args.gateway)

    if args.service:
        keep = set(args.service)
        catalog["operations"] = [o for o in catalog["operations"] if o["service"] in keep]
        catalog["services"] = [s for s in catalog["services"] if s["value"] in keep]
    if args.effect:
        keep_e = set(args.effect)
        catalog["operations"] = [o for o in catalog["operations"] if o["effect"] in keep_e]
    if args.service or args.effect:
        by_effect: dict[str, int] = {}
        for op in catalog["operations"]:
            by_effect[op["effect"]] = by_effect.get(op["effect"], 0) + 1
        catalog["counts"] = {
            "services": len(catalog["services"]),
            "operations": len(catalog["operations"]),
            "by_effect": by_effect,
        }

    text = (json.dumps(catalog, ensure_ascii=False, indent=args.indent)
            if args.format == "json" else table(catalog))

    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"каталог записан: {args.out} "
              f"(операций {catalog['counts']['operations']}, "
              f"сервисов {catalog['counts']['services']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
