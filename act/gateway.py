"""HTTP-шлюз рантайма NPP-Act.

Существует ради одного инварианта: внешний оркестратор (n8n, Temporal, cron,
чужой агент) НЕ должен ходить в сервисы напрямую. Прямой вызов обходит
губернатора и журнал, то есть отменяет весь слой удержания. Шлюз — это
единственная дверь, за которой гейт стоит всегда.

Поэтому здесь сознательно НЕТ эндпоинта «выполнить произвольный HTTP-запрос».
Шлюз умеет только то, что объявлено в манифестах.

Запуск:
    python3 -m act.gateway --port 8200 --manifests act/manifests \\
        --ledger /var/lib/npp/anna.jsonl --budget 300 --owner person:anna

Эндпоинты:
    GET  /api/health          живость
    GET  /act/catalog         плоский каталог возможностей (его читает n8n)
    GET  /act/services        список сервисов и их профили
    POST /act/perform         намерение → решение губернатора → (если допущено) исполнение
    POST /act/confirm         зафиксировать согласие на конкретное действие
    GET  /act/ledger          последние записи журнала
    GET  /act/ledger/verify   целостность хэш-цепи
    GET  /act/budget          остаток бюджета
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .npp_act import Budget, Executor, Governor, Ledger, Registry
from .npp_act.executor import ExecutionError


class Runtime:
    """Одно состояние профиля: реестр, журнал, бюджет, губернатор."""

    def __init__(self, manifests: Path, ledger_path: Path, budget: float, owner: str):
        self.registry = Registry().load_dir(manifests)
        levels = manifests / "levels"
        if levels.is_dir():
            self.registry.load_dir(levels)
        self.ledger = Ledger(ledger_path, owner=owner)
        self.governor = Governor(self.registry, self.ledger, Budget(budget))
        self.executor = Executor(self.registry, self.governor, self.ledger)
        self.owner = owner

    def rebind(self, service: str, base_url: str) -> None:
        self.registry.rebind(service, base_url)


class Handler(BaseHTTPRequestHandler):
    runtime: Runtime = None  # подставляется в main()

    def log_message(self, *args) -> None:
        pass

    # ---------- инфраструктура ----------

    def _send(self, status: int, body) -> None:
        raw = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------- чтение ----------

    def do_GET(self) -> None:
        url = urlparse(self.path)
        rt = self.runtime

        if url.path == "/api/health":
            return self._send(200, {
                "ok": True, "runtime": "npp-act", "version": "1.0",
                "owner": rt.owner, "services": len(rt.registry),
            })

        if url.path == "/act/catalog":
            return self._send(200, rt.registry.catalog())

        if url.path == "/act/services":
            out = []
            for name in rt.registry.services():
                man = rt.registry.manifest(name)
                out.append({"service": name, "title": man.title, "profile": man.profile,
                            "base_url": man.base_url, "verbs": len(man.capabilities),
                            "q6": man.q6})
            return self._send(200, out)

        if url.path == "/act/budget":
            b = rt.governor.budget
            return self._send(200, {"limit": b.limit, "spent": b.spent,
                                    "remaining": b.remaining, "currency": b.currency})

        if url.path == "/act/ledger":
            q = parse_qs(url.query)
            limit = int(q.get("limit", ["50"])[0])
            recs = list(rt.ledger)[-limit:]
            return self._send(200, [
                {"seq": r.seq, "ts": r.ts, "kind": r.kind,
                 "payload": r.payload, "hash": r.hash[:16]} for r in recs
            ])

        if url.path == "/act/ledger/verify":
            try:
                ok = rt.ledger.verify()
                return self._send(200, {"ok": ok, "records": len(rt.ledger),
                                        "head": rt.ledger.head[:16]})
            except Exception as e:
                return self._send(409, {"ok": False, "error": str(e)})

        return self._send(404, {"error": "неизвестный маршрут"})

    # ---------- действие ----------

    def do_POST(self) -> None:
        url = urlparse(self.path)
        rt = self.runtime
        body = self._body()

        if url.path == "/act/confirm":
            service = body.get("service")
            verb = body.get("verb")
            key = body.get("idempotency_key", "")
            if not service or not verb:
                return self._send(400, {"error": "service и verb обязательны"})
            rt.governor.confirm(f"{service}:{verb}:{key}")
            return self._send(200, {"confirmed": True,
                                    "scope": f"{service}:{verb}:{key}"})

        if url.path == "/act/perform":
            service = body.get("service")
            verb = body.get("verb")
            if not service or not verb:
                return self._send(400, {"error": "service и verb обязательны"})

            payload = body.get("payload") or {}
            key = body.get("idempotency_key")
            hold = body.get("hold")
            dry_run = bool(body.get("dry_run"))

            # dry_run спрашивает губернатора и НЕ исполняет: это главный режим
            # для оркестратора, который хочет показать человеку, что произойдёт.
            if dry_run:
                d = rt.governor.evaluate(service, verb, payload, key, hold)
                return self._send(200, {
                    "dry_run": True,
                    "decision": {"verdict": d.verdict, "reason": d.reason,
                                 "alternative": d.alternative, "checks": d.checks},
                    "executed": False,
                })

            try:
                decision, result = rt.executor.perform(service, verb, payload, key, hold)
            except ExecutionError as e:
                return self._send(502, {"error": str(e)})

            out = {
                "dry_run": False,
                "decision": {"verdict": decision.verdict, "reason": decision.reason,
                             "alternative": decision.alternative, "checks": decision.checks},
                "executed": result is not None,
                "budget_remaining": rt.governor.budget.remaining,
            }
            if result is not None:
                out["result"] = {"ok": result.ok, "status": result.status, "body": result.body}
            # Отказ губернатора — это не ошибка шлюза: 200 с объяснением,
            # чтобы оркестратор мог ветвиться по verdict, а не ловить исключение.
            return self._send(200, out)

        return self._send(404, {"error": "неизвестный маршрут"})


def main() -> None:
    ap = argparse.ArgumentParser(description="HTTP-шлюз рантайма NPP-Act")
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--manifests", default="act/manifests")
    ap.add_argument("--ledger", default="/tmp/npp_act_gateway.jsonl")
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--owner", default="person:anna")
    ap.add_argument("--rebind", action="append", default=[],
                    help="service=http://host:port (можно несколько раз)")
    args = ap.parse_args()

    rt = Runtime(Path(args.manifests), Path(args.ledger), args.budget, args.owner)
    for pair in args.rebind:
        service, _, base = pair.partition("=")
        rt.rebind(service, base)

    Handler.runtime = rt
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"шлюз NPP-Act на http://127.0.0.1:{args.port}  "
          f"(профиль {args.owner}, сервисов {len(rt.registry)}, журнал {args.ledger})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
