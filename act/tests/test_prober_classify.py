"""Классификаторы измерителя — на ЭТАЛОННЫХ стендах (этап 25, §10.1).

Зачем этот набор
────────────────
Классификатор, который выдаёт «склад проверен» или «маршрута нет», обязан
проверяться на ответах, поведение которых задано ЯВНО и написано отдельно от
него. Иначе это самосертификация: проба сама решила, каким должен быть ответ,
и сама же его оценила.

Поэтому стенды здесь — крошечные HTTP-серверы на http.server. Каждый получает
таблицу поведения, написанную в тесте (статус и тело на каждый запрос), и ни
один её ответ не выведен из prober.py. Стенд сам записывает, что к нему
пришло, — это независимое свидетельство для проверок теста. Например, что
завышенный заказ действительно ушёл с quantity=1000000, и что повторный GET
шёл с ТЕМ номером, который стенд сам же выдал.

Что это за проверка. Это проверка КЛАССИФИКАТОРА на эталонных ответах, а не
утверждение о системе. Ни один тест не говорит, что магазин daten2 ведёт себя
так или иначе: стенд изображает ответ, а тест проверяет, что проба его понимает
правильно.

Порты — свободные и двойной проверкой: молчит по HTTP и свободен для bind.
Номера не фиксированы: их выбирает ОС, а занятый порт отсекается проверкой.
Набор не пишет файлов и не создаёт временных каталогов: стенды живут в памяти
процесса и на локальных портах.

Запуск:  python3 -m act.tests.test_prober_classify
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act.manifest import parse_manifest  # noqa: E402
from act.npp_act.profile import parse_level_profile  # noqa: E402
from act.npp_act.prober import (  # noqa: E402
    ABSURD_QUANTITY, EMBELLISHED, INCOMPARABLE, UNVERIFIABLE,
    Prober, compare, embellishments, measure, report,
)

PASSED = 0
FAILED = 0

#: Заглушка базового адреса в манифесте. Настоящий адрес передаётся пробе явно.
DUMMY_BASE = "http://127.0.0.1:1"


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def stand_says(text: str) -> None:
    """Печатает эталон стенда: что ему задано. Это не выведено из пробы."""
    print(f"    эталон стенда: {text}")


# ────────────────────────────────────────────────────────────────────────────
# Порты: свободные, двойная проверка
# ────────────────────────────────────────────────────────────────────────────

def _answers_http(port: int) -> bool:
    """Отвечает ли что-то на порту по HTTP (любым кодом). Ответ кодом — тоже занятость."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.4):
            return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _bindable(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_free_port() -> int:
    """Порт, который и молчит по HTTP, и действительно свободен для bind.

    Двух проверок по отдельности мало: молчащий порт может держать чужой процесс,
    который на HTTP пока не отвечает, а удачный bind ничего не говорит о том, кто
    ответит на следующий запрос. Номер выбирает ОС, фиксированного нет.
    """
    for _ in range(100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if not _answers_http(port) and _bindable(port):
            return port
    raise RuntimeError("свободный порт не найден")


# ────────────────────────────────────────────────────────────────────────────
# Стенд
# ────────────────────────────────────────────────────────────────────────────

class Text(str):
    """Тело, которое стенд отдаёт как text/plain, а не как JSON."""


class Stand:
    """Крошечный HTTP-стенд на http.server.

    `behave(метод, путь, тело)` → (статус, ответ). Таблица поведения — в тесте.
    Стенд пишет журнал «что пришло и что ушло»: проверки теста сверяются с ним,
    а не с тем, что сообщила проба.
    """

    def __init__(self, behave: Callable[[str, str, Any], tuple[int, Any]]) -> None:
        self.behave = behave
        self.log: list[dict[str, Any]] = []
        self.port = 0
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def gets(self) -> list[str]:
        return [e["path"] for e in self.log if e["method"] == "GET"]

    def posts(self) -> list[dict[str, Any]]:
        return [e for e in self.log if e["method"] == "POST"]

    def __enter__(self) -> "Stand":
        stand = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                body: Any = None
                if raw:
                    try:
                        body = json.loads(raw)
                    except json.JSONDecodeError:
                        body = raw
                status, reply = stand.behave(self.command, self.path, body)
                if isinstance(reply, Text):
                    data, ctype = reply.encode("utf-8"), "text/plain; charset=utf-8"
                else:
                    data = json.dumps(reply, ensure_ascii=False).encode("utf-8")
                    ctype = "application/json; charset=utf-8"
                # Журнал пишется ДО ответа: к моменту, когда проба получила ответ,
                # запись уже есть.
                with stand._lock:
                    stand.log.append({"method": self.command, "path": self.path,
                                      "body": body, "status": status, "reply": reply})
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = _serve
            do_POST = _serve

            def log_message(self, fmt: str, *args: Any) -> None:
                return  # тишина в выводе набора

        for _ in range(20):
            port = pick_free_port()
            try:
                self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            except OSError:
                continue  # между проверкой и bind порт успели занять — берём другой
            self.port = port
            break
        else:
            raise RuntimeError("стенд не поднялся ни на одном свободном порту")
        threading.Thread(target=self._server.serve_forever,
                         kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


# ────────────────────────────────────────────────────────────────────────────
# Манифесты и профили стендов
# ────────────────────────────────────────────────────────────────────────────

def read_verb(vid: str, path: str, *, inputs: dict | None = None,
              output: dict | None = None) -> dict:
    return {"id": vid, "title": vid, "effect": "read", "reversible": False,
            "cost": {"money": 0, "time_s": 0.1}, "consent": "none",
            "binding": {"protocol": "http", "method": "GET", "path": path},
            "input": inputs or {}, "output": output or {}}


def commit_verb(vid: str, path: str, *, inputs: dict, output: dict) -> dict:
    """Необратимое обязательство с объявленной идемпотентностью, как у L1 daten2."""
    return {"id": vid, "title": vid, "effect": "commit", "reversible": False,
            "cost": {"money": "variable", "currency": "EUR", "time_s": 0.3},
            "consent": "confirm", "idempotency": "field:client_token",
            "binding": {"protocol": "http", "method": "POST", "path": path},
            "input": inputs, "output": output}


def manifest(service: str, profile: str, verbs: list[dict],
             level: dict | None = None) -> dict:
    raw: dict[str, Any] = {"npp_act": "1.0", "service": service, "title": service,
                           "base_url": DUMMY_BASE, "profile": profile,
                           "capabilities": verbs}
    if level is not None:
        raw["level_profile"] = level
    return raw


def level_block(passed: int, total: int, *, stock: bool = False,
                missing: tuple[str, ...] = ()) -> dict:
    """Заявленный профиль уровня. Поля, которые тестам не нужны, — нейтральные."""
    return {"level": 4, "stack": "стенд", "language": "python", "storage": "sqlite",
            "weight": "minimal", "runtime_units": 1, "transactional": True,
            "stock_checked": stock, "concurrency_safe": False,
            "concurrency_evidence": "not_measured",
            "contract_conformance": {"passed": passed, "total": total},
            "missing_verbs": list(missing), "features": {"offline_capable": True}}


# ────────────────────────────────────────────────────────────────────────────
# Склад: магазин-стенд (проверки 1–4, 8, 9)
# ────────────────────────────────────────────────────────────────────────────

TRACEBACK_500 = (
    "Traceback (most recent call last):\n"
    "  File \"shop.py\", line 88, in create_order\n"
    "    cur.execute(\"UPDATE products SET stock = stock - ?\", (qty,))\n"
    "sqlite3.IntegrityError: CHECK constraint failed: stock >= 0"
)


def shop_behave(order_reply: Callable[[Any], tuple[int, Any]]):
    """Магазин-стенд: один товар в каталоге, а ответ на заказ задаёт тест."""
    def behave(method: str, path: str, body: Any) -> tuple[int, Any]:
        if method == "GET" and path == "/api/products":
            return 200, [{"id": 7, "name": "роза"}]
        if method == "POST" and path == "/api/orders":
            return order_reply(body)
        return 404, {"error": "нет такого маршрута"}
    return behave


def shop_verbs() -> list[dict]:
    return [
        read_verb("catalog.list", "/api/products", output={"": "array of product"}),
        commit_verb("order.create", "/api/orders",
                    inputs={"name": "string", "items": "array of {product_id, quantity}"},
                    output={"order_number": "string"}),
    ]


def run_stock(order_reply: Callable[[Any], tuple[int, Any]]) -> tuple[Any, Stand]:
    """Прогнать складскую пробу против магазина-стенда. Вернуть результат и журнал."""
    with Stand(shop_behave(order_reply)) as stand:
        prober = Prober(parse_manifest(manifest("stand-shop", "vendor", shop_verbs())),
                        base_url=stand.base)
        result = prober.stock_probe()
    return result, stand


def sent_quantity(stand: Stand) -> Any:
    """Количество из ЖУРНАЛА стенда: что реально пришло, а не что сообщила проба."""
    posts = stand.posts()
    if not posts:
        return None
    return posts[0]["body"]["items"][0]["quantity"]


# ────────────────────────────────────────────────────────────────────────────
# [1] — [4]: склад
# ────────────────────────────────────────────────────────────────────────────

def test_stock_accepted() -> None:
    print("\n[1] стенд принимает заказ сверх склада (200) → stock_checked False")
    stand_says("POST /api/orders отвечает 200 и номером заказа на ЛЮБОЙ объём; "
               "склад не читается. Это задано здесь, а не выведено из пробы.")
    result, stand = run_stock(lambda body: (200, {"order_number": "a1f3c9"}))
    check("стенд действительно получил заказ сверх склада (журнал стенда)",
          sent_quantity(stand) == ABSURD_QUANTITY, f"quantity={sent_quantity(stand)}")
    check("принятие 200 → stock_checked = False", result.ok is False, f"ok={result.ok!r}")
    check("наблюдение называет принятие", "ПРИНЯТ" in result.evidence, result.evidence)


def test_stock_server_failure() -> None:
    print("\n[2] стенд отвечает 500 с трассировкой на заказ сверх склада → НЕ True")
    stand_says("POST /api/orders отвечает 500 и трассировкой CHECK constraint failed: "
               "stock >= 0. Это падение базы, в нём есть складские слова, но решения "
               "склада нет.")
    result, stand = run_stock(lambda body: (500, {"error": TRACEBACK_500}))
    check("стенд получил заказ сверх склада (журнал стенда)",
          sent_quantity(stand) == ABSURD_QUANTITY, f"quantity={sent_quantity(stand)}")
    check("500 не записан как проверка склада: stock_checked не True",
          result.ok is not True, f"ok={result.ok!r}")
    check("вердикт — «не проверено» (None)", result.ok is None, f"ok={result.ok!r}")
    check("наблюдение называет 500 и склад НЕ ПРОВЕРЕН",
          "500" in result.evidence and "НЕ ПРОВЕРЕН" in result.evidence, result.evidence)


def test_stock_refusal_names_stock() -> None:
    print("\n[3] стенд отвечает 400 «недостаточно товара на складе» (JSON, без трассировки) → True")
    stand_says("POST /api/orders отвечает 400 и JSON-объектом с сообщением «недостаточно "
               "товара на складе». Трассировки и слов сбоя нет: это настоящий складской отказ.")
    result, stand = run_stock(
        lambda body: (400, {"error": "недостаточно товара на складе", "available": 48}))
    check("стенд получил заказ сверх склада (журнал стенда)",
          sent_quantity(stand) == ABSURD_QUANTITY, f"quantity={sent_quantity(stand)}")
    check("отказ 400 по складу в JSON-объекте → stock_checked = True",
          result.ok is True, f"ok={result.ok!r}")
    check("наблюдение цитирует складское сообщение",
          "недостаточно товара на складе" in result.evidence, result.evidence)


def test_stock_refusal_other_reason() -> None:
    print("\n[4] стенд отвечает 400 «Ошибка» без слов о складе → None")
    stand_says("POST /api/orders отвечает 400 и JSON-объектом {error: 'Ошибка'}. "
               "Слов о складе нет, значит по причине отказа ничего не известно.")
    result, stand = run_stock(lambda body: (400, {"error": "Ошибка"}))
    check("стенд получил заказ сверх склада (журнал стенда)",
          sent_quantity(stand) == ABSURD_QUANTITY, f"quantity={sent_quantity(stand)}")
    check("400 без складского сообщения → None, а не True", result.ok is None,
          f"ok={result.ok!r}")
    check("наблюдение: сообщение не о складе, склад НЕ ПРОВЕРЕН",
          "не о складе" in result.evidence and "НЕ ПРОВЕРЕН" in result.evidence,
          result.evidence)


# ────────────────────────────────────────────────────────────────────────────
# [5] — [7]: маршрут и единицы
# ────────────────────────────────────────────────────────────────────────────

def order_service_behave(issue_token: bool) -> Callable[[str, str, Any], tuple[int, Any]]:
    """Сервис заказов. POST идемпотентен по client_token; GET всегда 404 (маршрута нет)."""
    issued: dict[str, str] = {}

    def behave(method: str, path: str, body: Any) -> tuple[int, Any]:
        if method == "POST" and path == "/api/orders":
            key = (body or {}).get("client_token", "")
            if issue_token:
                return 201, {"order_number": issued.setdefault(key, uuid.uuid4().hex)}
            return 201, {"status": "confirmed"}
        if method == "GET" and path.startswith("/api/orders/"):
            return 404, {"error": "не найдено"}
        return 404, {"error": "нет такого маршрута"}
    return behave


def order_verbs_with_token() -> list[dict]:
    return [
        commit_verb("order.create", "/api/orders", inputs={"name": "string"},
                    output={"order_number": "string"}),
        read_verb("order.get", "/api/orders/{order_number}",
                  inputs={"order_number": "string"}, output={"order": "object"}),
    ]


def order_verbs_without_token() -> list[dict]:
    return [
        commit_verb("order.create", "/api/orders", inputs={"name": "string"},
                    output={"status": "string"}),
        read_verb("order.get", "/api/orders/{token}", inputs={"token": "string"},
                  output={"order": "object"}),
    ]


def test_route_real_identifier() -> None:
    print("\n[5] 404 по РЕАЛЬНОМУ номеру, который выдал сам order.create → order.get в missing_verbs")
    stand_says("POST /api/orders выдаёт order_number (32 hex) и идемпотентен по client_token. "
               "GET /api/orders/* отвечает 404 на ЛЮБОЙ путь: маршрута чтения нет, как у L7 daten2.")
    raw = manifest("stand-orders", "vendor", order_verbs_with_token())
    with Stand(order_service_behave(issue_token=True)) as stand:
        contract = Prober(parse_manifest(raw), base_url=stand.base).contract_probe()
        issued = stand.posts()[0]["reply"]["order_number"] if stand.posts() else ""
        gets_before_measure = stand.gets()
        measured = measure(raw, base_url=stand.base, concurrency=2, repeats=2)
    check("order.get попал в missing_verbs: 404 по номеру, который сервис сам выдал",
          contract.data["missing_verbs"] == ["order.get"],
          str(contract.data["missing_verbs"]))
    check("order.get не записан как «не выяснено»",
          "order.get" not in contract.data["unresolved"], str(contract.data["unresolved"]))
    check("журнал стенда: GET шёл ровно с номером, который стенд сам выдал",
          bool(issued) and gets_before_measure == [f"/api/orders/{issued}"],
          f"GET {gets_before_measure}, выдано {issued!r}")
    check("вердикт контракта — не пройден (глагол провален по маршруту)",
          contract.ok is False, f"ok={contract.ok!r}")

    # Тот же факт — на языке профиля: уровень, который заявляет order.get, лжёт.
    declared = parse_level_profile(manifest("stand-orders", "vendor",
                                            order_verbs_with_token(), level_block(2, 2)))
    gaps = compare(declared, measured)
    lie = [d for d in gaps if d.field == "missing_verbs"]
    check("сверка: заявлено «маршрут есть», измерено «маршрута нет» → приукрашивание, critical",
          bool(lie) and lie[0].direction == EMBELLISHED and lie[0].severity == "critical"
          and "order.get" in lie[0].detail, str(lie))


def test_route_no_identifier() -> None:
    print("\n[6] 404 БЕЗ реального номера → «не выяснено», не missing_verbs")
    stand_says("POST /api/orders отвечает 201 и никакого идентификатора не выдаёт. "
               "GET /api/orders/* — 404. Путь с параметром {token}: ручки у пробы нет, "
               "она подставляет заглушку, и 404 по заглушке ничего не доказывает.")
    raw = manifest("stand-orders-b", "vendor", order_verbs_without_token())
    with Stand(order_service_behave(issue_token=False)) as stand:
        contract = Prober(parse_manifest(raw), base_url=stand.base).contract_probe()
        issued_identifiers = [k for p in stand.posts() for k in (p["reply"] or {})
                              if k != "status"]
        measured = measure(raw, base_url=stand.base, concurrency=2, repeats=2)
    check("стенд действительно не выдал ни одного идентификатора (журнал стенда)",
          issued_identifiers == [], str(issued_identifiers))
    check("order.get НЕ в missing_verbs: отсутствие маршрута не доказано",
          "order.get" not in contract.data["missing_verbs"],
          str(contract.data["missing_verbs"]))
    check("order.get помечен «не выяснено» и назван причиной",
          "order.get" in contract.data["unresolved"]
          and "реального идентификатора" in contract.data["unresolved"]["order.get"]["reason"],
          str(contract.data["unresolved"]))
    check("не выяснено выведено из итога: order.get не в verbs",
          "order.get" not in contract.data["verbs"], str(sorted(contract.data["verbs"])))
    check("вердикт контракта — None (всё известное совпало, полной картины нет)",
          contract.ok is None, f"ok={contract.ok!r}")
    check("в наблюдении сказано «НЕ ВЫЯСНЕН»", "НЕ ВЫЯСНЕН" in contract.evidence,
          contract.evidence)

    declared = parse_level_profile(manifest("stand-orders-b", "vendor",
                                            order_verbs_without_token(), level_block(2, 2)))
    gaps = compare(declared, measured)
    by_field = {d.field: d for d in gaps}
    check("сверка: «не выяснено» видно как непроверяемое, а не как ложь",
          "unresolved_verbs" in by_field
          and by_field["unresolved_verbs"].direction == UNVERIFIABLE
          and "order.get" in by_field["unresolved_verbs"].measured,
          str(by_field.get("unresolved_verbs")))
    check("ни одного приукрашивания из-за нерешённого маршрута",
          all(d.field != "missing_verbs" for d in embellishments(gaps)),
          str([d.field for d in embellishments(gaps)]))


def contract_behave() -> Callable[[str, str, Any], tuple[int, Any]]:
    """Четыре глагола контракта, все отвечают по своей output-схеме.

    Склад принимает любой заказ (201), идемпотентность по client_token честная.
    """
    issued: dict[str, str] = {}

    def behave(method: str, path: str, body: Any) -> tuple[int, Any]:
        if method == "GET" and path == "/api/health":
            return 200, {"ok": True, "level": 1, "stack": "стенд"}
        if method == "GET" and path == "/api/products":
            return 200, [{"id": 7, "name": "роза"}]
        if method == "POST" and path == "/api/orders":
            key = (body or {}).get("client_token", "")
            return 201, {"order_number": issued.setdefault(key, uuid.uuid4().hex)}
        if method == "GET" and path.startswith("/api/orders/"):
            token = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            if token in issued.values():
                return 200, {"order": {"order_number": token}, "items": []}
            return 404, {"error": "нет такого заказа"}
        return 404, {"error": "нет такого маршрута"}
    return behave


def four_verbs() -> list[dict]:
    return [
        read_verb("health.check", "/api/health",
                  output={"ok": "boolean", "level": "integer", "stack": "string"}),
        read_verb("catalog.list", "/api/products", output={"": "array of product"}),
        commit_verb("order.create", "/api/orders",
                    inputs={"name": "string", "items": "array of {product_id, quantity}"},
                    output={"order_number": "string"}),
        read_verb("order.get", "/api/orders/{order_number}",
                  inputs={"order_number": "string"}, output={"order": "object", "items": "array"}),
    ]


def test_units() -> None:
    print("\n[7] заявление в ДРУГИХ единицах (22 проверки при 4 глаголах) → «несопоставимо»")
    stand_says("четыре глагола, все отвечают по своей output-схеме; склад принимает любой "
               "заказ (201); идемпотентность честная. Измеритель видит 4 из 4 глаголов.")
    raw = manifest("stand-four", "vendor", four_verbs())
    with Stand(contract_behave()) as stand:
        measured = measure(raw, base_url=stand.base, concurrency=2, repeats=3)
    check("измерено 4/4 глаголов (единица измерителя — глагол)",
          measured.conformance == (4, 4), str(measured.conformance))

    claimed = parse_level_profile(manifest("stand-four", "vendor", four_verbs(),
                                           level_block(22, 22)))
    gaps = compare(claimed, measured)
    by_field = {d.field: d for d in gaps}
    cc = by_field.get("contract_conformance")
    check("заявлено 22/22 при 4 глаголах → вердикт «несопоставимо»",
          cc is not None and cc.direction == INCOMPARABLE and cc.severity == "warning",
          str(cc))
    check("несопоставимое — не приукрашивание и не совпадение",
          cc is not None and cc not in embellishments(gaps), str(cc))
    rep = report(measured, claimed)
    check("отчёт не утверждает «совпало» (фраза «расхождений нет» здесь неверна)",
          "совпал с измеренным" not in rep, rep)
    check("в отчёте стоит «несопоставимо» с объяснением единиц",
          "несопоставимо" in rep and "знаменатель 22" in rep, rep)

    honest = parse_level_profile(manifest("stand-four", "vendor", four_verbs(),
                                          level_block(4, 4)))
    control = compare(honest, measured)
    check("контроль: тот же стенд против 4/4 — единицы совпали, расхождений нет",
          control == [], str([(d.field, d.direction) for d in control]))


# ────────────────────────────────────────────────────────────────────────────
# [8] — [10]: дополнительные границы правил
# ────────────────────────────────────────────────────────────────────────────

def test_stock_plain_text_is_not_a_verdict() -> None:
    print("\n[8] складская фраза в text/plain — не JSON-объект → None")
    stand_says("POST /api/orders отвечает 400 с text/plain «недостаточно товара на складе». "
               "Тело — не JSON-объект, и сообщение по форме не разобрать.")
    result, stand = run_stock(lambda body: (400, Text("недостаточно товара на складе")))
    check("стенд получил заказ сверх склада (журнал стенда)",
          sent_quantity(stand) == ABSURD_QUANTITY, f"quantity={sent_quantity(stand)}")
    check("text/plain с складской фразой → None, а не True", result.ok is None,
          f"ok={result.ok!r}")


def test_stock_failure_words_beat_stock_words() -> None:
    print("\n[9] складская фраза рядом со словом сбоя в JSON-объекте → None")
    stand_says("POST /api/orders отвечает 400 JSON-объектом, где складская фраза стоит рядом "
               "со словом сбоя CheckViolation. Признак сбоя побеждает складское слово.")
    result, stand = run_stock(
        lambda body: (400, {"error": "CheckViolation: недостаточно товара на складе"}))
    check("стенд получил заказ сверх склада (журнал стенда)",
          sent_quantity(stand) == ABSURD_QUANTITY, f"quantity={sent_quantity(stand)}")
    check("признак сбоя в теле → None, даже при складских словах",
          result.ok is None, f"ok={result.ok!r}")


def test_route_path_less() -> None:
    print("\n[10] путь без параметров: 404 без входа = маршрута нет; 404 с входом = не выяснено")
    stand_says("GET /api/slots (с обязательным day) и GET /api/slots/audit отвечают 404 на "
               "всё. Для /api/slots 404 может быть пустой выборкой по фильтру; для "
               "/api/slots/audit — отсутствием пути. Различить это по коду нельзя.")
    verbs = [
        read_verb("slot.list", "/api/slots", inputs={"day": "string"},
                  output={"": "array of slot"}),
        read_verb("slot.audit", "/api/slots/audit", output={"audited": "boolean"}),
    ]
    with Stand(lambda method, path, body: (404, {"error": "не найдено"})) as stand:
        contract = Prober(parse_manifest(manifest("stand-slots", "venue", verbs)),
                          base_url=stand.base).contract_probe()
        gets = stand.gets()
    check("путь без входа с 404 → маршрута нет (старое правило сохранено)",
          contract.data["missing_verbs"] == ["slot.audit"],
          str(contract.data["missing_verbs"]))
    check("путь без параметров, но с входом, с 404 → не выяснено, а не missing",
          "slot.list" in contract.data["unresolved"]
          and "slot.list" not in contract.data["missing_verbs"],
          str(contract.data["unresolved"]))
    check("журнал стенда: фильтр действительно ушёл в запрос",
          any(path.startswith("/api/slots?day=") for path in gets), str(gets))
    check("вердикт контракта — не пройден (один провален, один не выяснен)",
          contract.ok is False, f"ok={contract.ok!r}")


# ────────────────────────────────────────────────────────────────────────────

def test_html_on_success_is_not_a_crash() -> None:
    print("\n[11] 200 с HTML вместо JSON → проба не падает, глагол не сходится со схемой")
    stand_says("GET /api/health отвечает 200 и HTML-страницей, как страница обслуживания. "
               "Тело не JSON-объект, значит по объявленной схеме оно не сходится.")
    raw = manifest("stand-html", "venue",
                   [read_verb("health.check", "/api/health", output={"ok": "boolean"})])
    with Stand(lambda method, path, body: (200, Text("<html>maintenance</html>"))) as stand:
        contract = Prober(parse_manifest(raw), base_url=stand.base).contract_probe()
    check("проба дошла до вердикта, а не упала на разборе JSON",
          contract.applicable and contract.data["total"] == 1, contract.evidence)
    check("HTML вместо объявленной схемы — 0 из 1 по своей схеме",
          contract.data["passed"] == 0, str(contract.data["verbs"]))
    check("вердикт контракта — не пройден", contract.ok is False, f"ok={contract.ok!r}")


CASES: tuple[Callable[[], None], ...] = (
    test_stock_accepted,                          # [1]
    test_stock_server_failure,                    # [2]
    test_stock_refusal_names_stock,               # [3]
    test_stock_refusal_other_reason,              # [4]
    test_route_real_identifier,                   # [5]
    test_route_no_identifier,                     # [6]
    test_units,                                   # [7]
    test_stock_plain_text_is_not_a_verdict,       # [8]
    test_stock_failure_words_beat_stock_words,    # [9]
    test_route_path_less,                         # [10]
    test_html_on_success_is_not_a_crash,          # [11]
)


def main() -> int:
    global FAILED
    for case in CASES:
        # Каждый случай изолирован: исключение в одном (стенд не поднялся, проба
        # упала на неожиданной форме ответа) — провал ЭТОГО случая, а не обрыв
        # набора. Иначе один сбой спрятал бы результаты остальных девяти.
        try:
            case()
        except Exception as e:
            FAILED += 1
            print(f"  ✗ случай {case.__name__} прерван исключением: "
                  f"{type(e).__name__}: {e}")

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
