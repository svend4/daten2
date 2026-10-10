"""Живое измерение склада на НАСТОЯЩЕМ магазине daten2 — уровень 1 из своей ветки.

Зачем этот набор существует отдельно от test_prober
───────────────────────────────────────────────────
`test_prober` проверяет сам измеритель и делает это на `act.services.venue` —
живом, но НАШЕМ сервисе. Этого достаточно, чтобы доказать, что проба работает,
и недостаточно, чтобы доказать главный факт проекта:

    «проверку остатка перед заказом делает только уровень 6,
     остальные шесть принимают заказ сверх склада»

Этот факт до сих пор был установлен ЧТЕНИЕМ исходников семи уровней. Чтение —
законный способ узнать, как устроен код, но оно не измерение: читающий видит то,
что написано, а не то, что происходит. Ровно на этой разнице живёт болезнь
`plugin-marketplace` из daten2 — 14/14 зелёных против собственного мока и
отвергнутые настоящие бэкенды. Поэтому здесь поднимается настоящий уровень 1 из
своей ветки (`origin/claude/level1-php-GBpVR`, PHP 8 + SQLite), и факт
подтверждается ИЗМЕРЕНИЕМ по HTTP.

Что здесь считается внешним эталоном
────────────────────────────────────
Ни одна проверка не верит измерителю на слово:

  · вердикт `stock_probe` сверяется с собственными запросами теста
    (urllib, без участия `prober.py`) — остаток до, остаток после, заказ;
  · вердикт `idempotency_probe` сверяется с двумя POST-ами теста, посланными
    с одним и тем же `client_token`;
  · причина, по которой остаток не сдвинулся, читается из stderr живого
    php-процесса, а не домысливается;
  · заявленный профиль берётся из `act/manifests/levels/level1.act.json`, а
    измеренный — из живого сервиса; совпадение по складу и контракту и есть
    подтверждение того, что профиль писался по настоящим исходникам.

Сервис, которого тест не поднимал, измерять нельзя
──────────────────────────────────────────────────
Порт подбирается двойной проверкой (молчит по HTTP И свободен для bind), и
этого всё равно мало: молчавший порт мог занять чужой процесс в зазоре между
проверкой и запуском. Поэтому перед измерением тест кладёт в корень магазина
файл со случайным именем и содержимым и требует вернуть его дословно. Чужой
сервис такого файла не отдаст. Один раз в этом каталоге тест уже молча измерил
ЧУЖОЙ сервис и отчитался зелёным — опознание обязательно.

Чего этот набор НЕ измеряет и почему это написано, а не замолчано
────────────────────────────────────────────────────────────────
Из семи уровней в этом окружении поднимается один — первый. Остальные шесть
требуют того, чего здесь нет (flask, django, node_modules, postgres, rabbit), и
это проверено, а не предположено: см. фазу [7]. Их строки в профилях остаются
подтверждёнными только чтением исходников, и тест говорит об этом прямо. Выдать
шесть прочитанных уровней за шесть измеренных значило бы совершить ту самую
подмену, против которой написан `prober.py`.

АБЗАЦ ДЛЯ СПЕЦИФИКАЦИИ (§10.1, координатору — перенести в SPEC-NPP-ACT.md)
─────────────────────────────────────────────────────────────────────────
    Измерение профиля (§10.1) ДОЛЖНО проводиться против того экземпляра
    сервиса, который измеряющая сторона подняла сама и опознала: совпадения
    адреса и ответа `/api/health` НЕДОСТАТОЧНО, потому что по тому же адресу
    может отвечать посторонний процесс, а измерение чужого сервиса неотличимо
    от измерения своего по виду отчёта. Измеритель ДОЛЖЕН различать «сервис
    отверг заказ сверх остатка» и «сервис принял заказ, но списание остатка у
    него не состоялось»: второе — не проверка склада, а расхождение заказа со
    складом, и для потребителя оно опаснее первого, так как обязательство
    принято, а товара нет. Отрицательный вердикт пробы ДОЛЖЕН подтверждаться
    наблюдением за состоянием мира ДО и ПОСЛЕ вызова, а не только кодом
    ответа: уровень 1 daten2 отвечает на заказ 1 000 000 роз при остатке 50
    кодом 201 и оставляет остаток равным 50 — ни отказа, ни списания. Наконец,
    объявление `idempotency` в манифесте (§4.5) НЕ ДОЛЖНО приниматься без
    пробы: уровень 1 объявляет `field:client_token` и не читает это поле ни
    одной строкой кода, поэтому повтор создаёт второе обязательство.

Запуск:  python3 -m act.tests.test_stock_live
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act.manifest import load_manifest  # noqa: E402
from act.npp_act.profile import load_level_profile  # noqa: E402
from act.npp_act.prober import (  # noqa: E402
    ABSURD_QUANTITY, CONTRACT, EMBELLISHED, IDEMPOTENCY, LATENCY, STOCK,
    UNVERIFIABLE, Prober, compare, embellishments, measure, report,
)

#: Ветка с настоящим контрактом. В рабочем дереве `levels/level1` лежит старая
#: доконтрактная версия без /api/* — измерять её бессмысленно.
BRANCH = "origin/claude/level1-php-GBpVR"
LEVEL1_MANIFEST = ROOT / "act/manifests/levels/level1.act.json"

#: Товар, по которому ведём счёт. Выбран не по имени, а по месту: уровень 1
#: отдаёт каталог отсортированным, и первая позиция — та же, которую возьмёт
#: складская проба (она берёт `id` из первого элемента списка).
ROSE_SLUG = "red-rose"

BASE_PORT = 8930
_PORT_CURSOR = [BASE_PORT]

PASSED = 0
FAILED = 0
SKIPPED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {label}")
    else:
        FAILED += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def note(text: str) -> None:
    """Наблюдение в отчёт. Не проверка: число в итоге оно не увеличивает."""
    print(f"    · {text}")


def skip(reason: str) -> None:
    """Пропуск печатается явно и НЕ считается пройденной проверкой."""
    SKIPPED.append(reason)
    print(f"  ⊘ ПРОПУЩЕНО: {reason}")


# ────────────────────────────────────────────────────────────────────────────
# HTTP теста — независимый от prober.py
# ────────────────────────────────────────────────────────────────────────────

def http(method: str, url: str, payload: dict | None = None,
         timeout: float = 5.0) -> tuple[int, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:200]}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return 0, {"error": str(e)}


def raw(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """Сырое тело без JSON — нужно для файла-опознавателя."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, ""


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.6):
            return True
    except urllib.error.HTTPError:
        return True          # ответил кодом ошибки — значит порт ЗАНЯТ
    except Exception:
        return False


def pick_port() -> int:
    """Порт, который и молчит по HTTP, и действительно свободен для bind.

    Двух проверок мало по отдельности: молчащий порт может быть занят чужим
    процессом, не отвечающим на HTTP, а успешный bind ничего не говорит о том,
    кто ответит на запрос. Нужны обе — и даже их недостаточно, поэтому ниже
    есть ещё опознание поднятого экземпляра по файлу-метке.
    """
    while _PORT_CURSOR[0] < BASE_PORT + 400:
        port = _PORT_CURSOR[0]
        _PORT_CURSOR[0] += 1
        if answers(f"http://127.0.0.1:{port}/api/health"):
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("свободных портов для магазина не нашлось")


# ────────────────────────────────────────────────────────────────────────────
# Настоящий уровень 1: достать из ветки и поднять
# ────────────────────────────────────────────────────────────────────────────

class Unavailable(RuntimeError):
    """Поднять настоящий уровень в этом окружении нельзя — это причина скипа."""


def unpack_level1(dest: Path) -> Path:
    """Выложить содержимое ветки уровня 1 в каталог. Ошибка → Unavailable."""
    if shutil.which("php") is None:
        raise Unavailable("в окружении нет php — поднять настоящий уровень 1 нечем")
    if shutil.which("git") is None or shutil.which("tar") is None:
        raise Unavailable("нет git или tar — ветку с контрактом не достать")
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest.parent / "level1.tar"
    with open(archive, "wb") as fh:
        git = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", BRANCH],
                             stdout=fh, stderr=subprocess.PIPE)
    if git.returncode != 0:
        raise Unavailable(f"git archive {BRANCH} не удался: "
                          f"{git.stderr.decode('utf-8', 'replace').strip()[:160]}")
    tar = subprocess.run(["tar", "-x", "-C", str(dest), "-f", str(archive)],
                         capture_output=True)
    if tar.returncode != 0:
        raise Unavailable("tar не распаковал архив ветки: "
                          f"{tar.stderr.decode('utf-8', 'replace').strip()[:160]}")
    archive.unlink(missing_ok=True)
    if not (dest / "index.php").exists():
        raise Unavailable(f"в ветке {BRANCH} нет index.php")
    return dest


class Shop:
    """Свежий экземпляр настоящего уровня 1: свой каталог, своя БД, свой порт.

    Свежий на каждую фазу — не чистоплюйство. Магазин торгует ШТУКАМИ, и
    списанный остаток обратно не появляется: один общий экземпляр сделал бы
    числа в отчёте зависимыми от порядка фаз, а именно числа здесь и есть
    результат. Общая БД превратила бы «остаток 50» в «остаток сколько-то».
    """

    def __init__(self, source: Path, label: str) -> None:
        self.source = source
        self.label = label
        self.dir = source.parent / f"inst-{label}"
        self.port = 0
        self.proc: subprocess.Popen | None = None
        self.log = source.parent / f"{label}.log"
        self.nonce = uuid.uuid4().hex
        self.marker = f"nonce-{self.nonce}.txt"

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "Shop":
        shutil.copytree(self.source, self.dir)
        (self.dir / "flowers.db").unlink(missing_ok=True)
        (self.dir / self.marker).write_text(self.nonce, encoding="utf-8")
        init = subprocess.run(["php", "init_db.php"], cwd=self.dir, capture_output=True)
        if init.returncode != 0:
            raise Unavailable("php init_db.php не создал БД: "
                              f"{init.stderr.decode('utf-8', 'replace').strip()[:200]}")
        self.port = pick_port()
        handle = open(self.log, "wb")
        self.proc = subprocess.Popen(
            ["php", "-S", f"127.0.0.1:{self.port}"],
            cwd=self.dir, stdout=handle, stderr=subprocess.STDOUT,
        )
        for _ in range(150):
            if self.proc.poll() is not None:
                raise Unavailable(f"php -S умер сразу: {self.stderr()[-200:]}")
            status, body = http("GET", f"{self.base}/api/health", timeout=0.5)
            if status == 200 and isinstance(body, dict) and body.get("level") == 1:
                return self
            time.sleep(0.1)
        raise Unavailable(f"уровень 1 не ответил на {self.base}/api/health")

    def __exit__(self, *exc: Any) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None

    def stderr(self) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def is_mine(self) -> bool:
        """Отвечает ли по этому порту именно тот экземпляр, который мы подняли."""
        status, text = raw(f"{self.base}/{self.marker}")
        return status == 200 and text.strip() == self.nonce

    # ---------- измерения теста, без participation prober.py ----------

    def catalog(self) -> list[dict]:
        status, body = http("GET", f"{self.base}/api/products")
        return body if status == 200 and isinstance(body, list) else []

    def stock_of(self, slug: str) -> int | None:
        for item in self.catalog():
            if item.get("slug") == slug:
                return int(item["stock"])
        return None

    def product_id(self, slug: str) -> int | None:
        for item in self.catalog():
            if item.get("slug") == slug:
                return int(item["id"])
        return None

    def order(self, product_id: int, quantity: int,
              token: str | None = None) -> tuple[int, Any]:
        payload: dict[str, Any] = {
            "name": "измерение NPP-Act",
            "items": [{"product_id": product_id, "quantity": quantity}],
        }
        if token is not None:
            payload["client_token"] = token
        return http("POST", f"{self.base}/api/orders", payload)


# ────────────────────────────────────────────────────────────────────────────
# [1] уровень 1 поднят из ветки и опознан
# ────────────────────────────────────────────────────────────────────────────

def test_live_source(source: Path, shop: Shop) -> None:
    print("\n[1] настоящий уровень 1 поднят из ветки и опознан")
    text = (source / "index.php").read_text(encoding="utf-8", errors="replace")
    check("из ветки распакован контракт, а не доконтрактная версия",
          "/api/orders" in text and "/api/products" in text and "/api/health" in text)

    working = ROOT / "levels/level1/index.php"
    if working.exists():
        old = working.read_text(encoding="utf-8", errors="replace")
        check("рабочее дерево levels/level1 действительно без /api/* — "
              "мерить его было бы мерить не то",
              "/api/" not in old, "в рабочем дереве нашёлся /api/")
    else:
        note("levels/level1/index.php в рабочем дереве нет — сравнивать не с чем")

    status, body = http("GET", f"{shop.base}/api/health")
    check("живой /api/health отвечает и называет себя первым уровнем",
          status == 200 and body.get("level") == 1 and body.get("stack") == "PHP",
          f"HTTP {status} {body}")
    check("по порту отвечает ИМЕННО поднятый нами экземпляр (файл-метка вернулся)",
          shop.is_mine(), f"метка {shop.marker} по {shop.base} не подтвердилась")
    note(f"порт {shop.port} подобран свободным, каталог {shop.dir.name}, "
         f"БД создана php init_db.php")

    catalog = shop.catalog()
    check("каталог отдаёт массив товаров с остатками", len(catalog) == 3
          and all("stock" in p for p in catalog), str(catalog)[:160])
    note("остатки сида: " + ", ".join(
        f"{p['slug']}={p['stock']}" for p in catalog))


# ────────────────────────────────────────────────────────────────────────────
# [3] contract_probe против четырёх глаголов контракта
# ────────────────────────────────────────────────────────────────────────────

def test_contract(shop: Shop) -> Prober:
    print("\n[3] contract_probe: четыре глагола контракта на живом сервисе")
    manifest = load_manifest(LEVEL1_MANIFEST)
    prober = Prober(manifest, base_url=shop.base)
    result = prober.contract_probe()

    check("проба контракта применима", result.applicable, result.evidence)
    verbs = result.data["verbs"]
    declared = {c.id for c in manifest}
    check("в манифесте уровня 1 ровно четыре глагола", len(declared) == 4, str(declared))
    check("вызваны все четыре, ни один не пропущен",
          set(verbs) == declared and not result.data["skipped"],
          f"вызваны {sorted(verbs)}, пропущены {result.data['skipped']}")
    check("все четыре ответили по своей же output-схеме",
          result.data["passed"] == result.data["total"] == 4,
          f"{result.data['passed']}/{result.data['total']}")
    check("маршрут есть у каждого объявленного глагола",
          result.data["missing_verbs"] == [], str(result.data["missing_verbs"]))
    check("вердикт пробы положительный", result.ok is True, str(result.ok))
    for vid in sorted(verbs):
        note(f"{vid}: HTTP {verbs[vid]['status']}, схема "
             f"{'сошлась' if verbs[vid]['shape_ok'] else 'разошлась'}, "
             f"{verbs[vid]['ms']} мс")
    return prober


# ────────────────────────────────────────────────────────────────────────────
# [2] склад: независимое измерение состояния мира, затем вердикт пробы
# ────────────────────────────────────────────────────────────────────────────

def test_stock_measured(shop: Shop) -> None:
    print("\n[2] склад: заказ сверх остатка — измерение, а не чтение исходников")
    pid = shop.product_id(ROSE_SLUG)
    before = shop.stock_of(ROSE_SLUG)
    check(f"остаток '{ROSE_SLUG}' до заказа прочитан из живого каталога",
          before == 50 and pid is not None, f"id={pid}, stock={before}")

    status, body = shop.order(pid, ABSURD_QUANTITY)
    accepted = 200 <= status < 300
    check(f"заказ {ABSURD_QUANTITY} шт. при остатке {before} ПРИНЯТ — "
          f"уровень 1 не проверяет остаток",
          accepted and status == 201, f"HTTP {status} {body}")
    order_number = (body or {}).get("order_number", "")
    check("на принятый заказ выдано обязательство (order_number, 32 hex)",
          bool(re.fullmatch(r"[0-9a-f]{32}", str(order_number))), str(order_number))
    note(f"сумма обязательства: total={(body or {}).get('total')} EUR "
         f"за {ABSURD_QUANTITY} шт. по цене каталога")

    st, doc = http("GET", f"{shop.base}/api/orders/{order_number}")
    recorded = None
    if st == 200 and isinstance(doc, dict):
        lines = doc.get("items") or []
        recorded = lines[0].get("quantity") if lines else None
    check(f"заказ записан целиком: в обязательстве стоит quantity={ABSURD_QUANTITY}",
          recorded == ABSURD_QUANTITY, f"HTTP {st}, записано {recorded}")

    after = shop.stock_of(ROSE_SLUG)
    check(f"остаток ПОСЛЕ принятого заказа не сдвинулся: {before} → {after}",
          after == before == 50, f"{before} → {after}")

    # Контроль обязателен: без него «остаток не сдвинулся» нельзя отличить от
    # «этот магазин вообще никогда не списывает». Обычный заказ списывает —
    # значит неподвижность вызвана именно завышенным количеством.
    st2, body2 = shop.order(pid, 1)
    control = shop.stock_of(ROSE_SLUG)
    check("контроль: обычный заказ 1 шт. списывает остаток, механизм списания жив",
          st2 == 201 and control == after - 1, f"HTTP {st2}: {after} → {control}")

    # Причина — из stderr живого процесса, а не из догадки.
    log = shop.stderr()
    check("в stderr живого php видно, почему списание не состоялось: "
          "CHECK constraint failed: stock >= 0",
          "CHECK constraint failed: stock" in log,
          "в логе такой записи нет")
    check("при этом ни одна ошибка не доехала до клиента (ответ был 201)",
          accepted, f"HTTP {status}")

    print("    НАХОДКА (измерена, в manifests/levels/level1.act.json не описана):")
    note(f"ожидалось при проверке склада: отказ, остаток {before}")
    note(f"ожидалось по замыслу кода (stock = stock - qty): "
         f"{before - ABSURD_QUANTITY}, что само запрещено CHECK (stock >= 0)")
    note(f"измерено: HTTP 201, заказ на {ABSURD_QUANTITY} шт. записан, "
         f"остаток {after} — ни отказа, ни списания")
    note("механизм: UPDATE products SET stock = stock - ? нарушает "
         "CHECK (stock >= 0) из schema.sql; SQLite3Stmt::execute() в PHP не "
         "бросает исключение, а возвращает false с warning, поэтому catch/ROLLBACK "
         "в index.php не срабатывает и COMMIT проходит")
    note("дефект уровня 'stock-not-checked' описан верно, но неполно: заказ не "
         "только не сверяется с остатком — он и не списывает его, то есть "
         "обязательство и склад расходятся молча")


def test_stock_probe(prober: Prober, shop: Shop) -> None:
    print("\n[6] stock_probe: тот же факт — вердиктом измерителя")
    before = shop.stock_of(ROSE_SLUG)
    result = prober.stock_probe()
    after = shop.stock_of(ROSE_SLUG)

    check("складская проба применима к vendor-профилю уровня 1",
          result.applicable, result.evidence)
    check("вердикт: остаток НЕ проверяется (ok is False)", result.ok is False,
          str(result.ok))
    check("проба целилась в обязывающий глагол заказа",
          result.data["verb"] == "order.create", str(result.data.get("verb")))
    check("количество завышено в поле, объявленном манифестом, а не выдуманном",
          result.data["bumped"] == "items[].quantity"
          and set(result.data["line"]) == {"product_id", "quantity"},
          f"{result.data.get('bumped')} / {result.data.get('line')}")
    check(f"сервис принял завышенный заказ: HTTP {result.data['status']}",
          result.data["accepted"] and result.data["status"] == 201,
          str(result.data))
    check("остаток и после пробы измерителя не сдвинулся",
          after == before, f"{before} → {after}")
    check("наблюдение в вердикте — наблюдение, а не пересказ",
          str(ABSURD_QUANTITY) in result.evidence and "201" in result.evidence,
          result.evidence)
    note(result.evidence)


# ────────────────────────────────────────────────────────────────────────────
# [4] идемпотентность: объявлена манифестом, не реализована сервисом
# ────────────────────────────────────────────────────────────────────────────

def test_idempotency(prober: Prober, shop: Shop, source: Path) -> None:
    print("\n[4] idempotency_probe: объявленный client_token против живого кода")
    result = prober.idempotency_probe()
    check("проба идемпотентности применима", result.applicable, result.evidence)
    check("вердикт отрицательный: повтор не возвращает то же обязательство",
          result.ok is False, str(result.ok))
    verdict = result.data["verbs"]["order.create"]["verdict"]
    check("исход назван точно: duplicated (создано ВТОРОЕ обязательство)",
          verdict == "duplicated", verdict)

    # Независимое подтверждение: два POST-а теста с одним и тем же ключом.
    token = "stock-live-" + uuid.uuid4().hex[:12]
    pid = shop.product_id(ROSE_SLUG)
    s1, b1 = shop.order(pid, 1, token=token)
    s2, b2 = shop.order(pid, 1, token=token)
    first, second = (b1 or {}).get("order_number"), (b2 or {}).get("order_number")
    check("независимо: один client_token дважды → два разных order_number",
          s1 == 201 and s2 == 201 and first and second and first != second,
          f"{s1}/{s2}: {first} и {second}")

    text = (source / "index.php").read_text(encoding="utf-8", errors="replace")
    check("в настоящем index.php слова client_token нет ни разу — "
          "объявленный ключ не читается",
          "client_token" not in text, "упоминание нашлось")

    print("    НАХОДКА (измерена):")
    note("манифест act/manifests/levels/level1.act.json объявляет у order.create "
         "idempotency='field:client_token'")
    note("живой сервис это поле игнорирует: повтор после обрыва связи создаёт "
         "второй заказ, то есть второе необратимое обязательство (§4.5)")
    note(f"наблюдение: {first} и {second} — два разных заказа на один ключ")


# ────────────────────────────────────────────────────────────────────────────
# [5] задержка
# ────────────────────────────────────────────────────────────────────────────

def test_latency(prober: Prober) -> None:
    print("\n[5] latency_probe: p50/p95 на читающих глаголах")
    result = prober.latency_probe(repeats=5)
    check("проба задержки применима", result.applicable, result.evidence)
    check("p50 не больше p95", result.data["p50_ms"] <= result.data["p95_ms"],
          str(result.data))
    check("замеры сделаны на обоих читающих глаголах без параметров",
          {"health.check", "catalog.list"} <= set(result.data["verbs"]),
          str(sorted(result.data["verbs"])))
    check("замеров не меньше, чем повторов на каждом глаголе",
          result.data["samples"] >= 10, str(result.data["samples"]))
    note(result.evidence)


# ────────────────────────────────────────────────────────────────────────────
# [7] measure() + compare(): заявленный профиль против измеренного
# ────────────────────────────────────────────────────────────────────────────

def test_compare(shop: Shop) -> None:
    print("\n[7] compare(): профиль из manifests/levels/level1.act.json против измеренного")
    declared = load_level_profile(LEVEL1_MANIFEST)
    measured = measure(LEVEL1_MANIFEST, base_url=shop.base, concurrency=4, repeats=5)
    gaps = compare(declared, measured)
    by_field = {d.field: d for d in gaps}

    check("измерен тот сервис, который заявлен в манифесте",
          measured.service == "level1-php" and measured.base_url == shop.base,
          f"{measured.service} @ {measured.base_url}")

    check("ГЛАВНЫЙ ФАКТ подтверждён: заявлено stock_checked=false, "
          "измерено false — расхождения нет",
          declared.stock_checked is False
          and measured.value("stock_checked") is False
          and "stock_checked" not in by_field,
          f"заявлено {declared.stock_checked}, измерено "
          f"{measured.value('stock_checked')}, расхождение "
          f"{by_field.get('stock_checked')}")

    m_passed, m_total = measured.conformance
    check("соответствие контракту сошлось: заявлено 22/22 (100%), измерено 4/4 (100%)",
          (m_passed, m_total) == (4, 4) and declared.conformance_ratio == 1.0
          and "contract_conformance" not in by_field,
          f"{m_passed}/{m_total}, расхождение {by_field.get('contract_conformance')}")

    check("нереализованных глаголов нет ни в заявлении, ни в измерении",
          not declared.missing_verbs and not measured.value("missing_verbs")
          and "missing_verbs" not in by_field,
          f"{sorted(declared.missing_verbs)} против {measured.value('missing_verbs')}")

    conc = by_field.get("concurrency_safe")
    check("concurrency_safe честно помечен непроверяемым, а не подтверждённым: "
          "у уровня 1 нет обратимых глаголов",
          conc is not None and conc.direction == UNVERIFIABLE
          and measured.value("concurrency_safe") is None,
          str(conc))
    check("непроверяемое заявление не записано в приукрашивания",
          conc not in embellishments(gaps), str(conc))

    lies = embellishments(gaps)
    check("приукрашивания найдены ровно по идемпотентности — и это находка, "
          "а не ошибка измерения",
          {d.field for d in lies} == {"idempotency", "double_execution"}
          and all(d.severity == "critical" and d.direction == EMBELLISHED for d in lies),
          str([(d.field, d.direction, d.severity) for d in lies]))

    names = {p.name for p in measured.probes}
    check("в измеренном профиле все пять проб и у каждого признака наблюдение",
          names == {CONTRACT, STOCK, IDEMPOTENCY, LATENCY, "concurrency"}
          and all(f.evidence.strip() for f in measured.features.values()),
          str(names))
    check("измерение честно перечислило необратимо израсходованное",
          len(measured.spent) >= 1 and all("order.create" in s for s in measured.spent),
          str(measured.spent))

    print("    отчёт измерителя:")
    for line in report(measured, declared).splitlines():
        print("      " + line)


# ────────────────────────────────────────────────────────────────────────────
# [8] какие уровни измерены, а какие нет — и это проверено, а не предположено
# ────────────────────────────────────────────────────────────────────────────

def module_absent(name: str) -> bool:
    out = subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True)
    return out.returncode != 0


def vendored(branch: str, marker: str) -> bool:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "--name-only", branch],
                         capture_output=True)
    return marker in out.stdout.decode("utf-8", "replace").split()


def test_unmeasured() -> None:
    print("\n[8] остальные шесть уровней: чем именно они не поднимаются здесь")
    check("flask в окружении нет — уровни 2 и 5 поднять нечем",
          module_absent("flask"))
    check("django в окружении нет — уровень 3 поднять нечем",
          module_absent("django"))
    check("в ветке уровня 4 нет node_modules — express и sqlite3 пришлось бы "
          "ставить из сети, а это запрещено",
          not vendored("origin/claude/level4-express-GBpVR", "node_modules"))
    check("в ветке уровня 6 нет node_modules — и она требует postgres с prisma",
          not vendored("origin/claude/level6-nextjs-GBpVR", "node_modules"))
    check("уровень 7 поднимается только docker-compose (postgres + rabbit)",
          vendored("origin/claude/level7-enterprise-GBpVR", "docker-compose.local.yml"))
    print("    ЧЕСТНАЯ ГРАНИЦА ЭТОГО НАБОРА:")
    note("измерен живьём: уровень 1 (php + sqlite, ветка " + BRANCH + ")")
    note("не измерены: уровни 2-7. Их строки stock_checked в профилях "
         "подтверждены ЧТЕНИЕМ исходников и остаются заявлением (§10.1), "
         "а не измерением")
    note("утверждение «проверку остатка делает только уровень 6» измерением "
         "здесь подтверждено для уровня 1 и для него одного")


# ────────────────────────────────────────────────────────────────────────────

def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="npp_stock_live_",
                                dir=os.environ.get("TMPDIR") or None))
    try:
        try:
            source = unpack_level1(tmp / "src")
        except Unavailable as e:
            skip(str(e))
            print(f"\n{'─' * 58}")
            print("⊘ НАБОР ПРОПУЩЕН ЦЕЛИКОМ: измерений не было, "
                  "пройденных проверок 0.")
            print("  Чтения исходников вместо измерения здесь не будет: "
                  "это и есть самосертификация.")
            return 0

        with Shop(source, "stock") as shop:
            test_live_source(source, shop)
            test_stock_measured(shop)

        with Shop(source, "probes") as shop:
            prober = test_contract(shop)
            test_idempotency(prober, shop, source)
            test_latency(prober)
            test_stock_probe(prober, shop)   # последней: она расходует склад
            sweep = prober.cleanup()
            check("измеритель убрался за собой (возвращать было нечего — "
                  "у уровня 1 нет обратимых глаголов)",
                  sweep["clean"], str(sweep))

        with Shop(source, "compare") as shop:
            test_compare(shop)

        test_unmeasured()
    except Unavailable as e:
        skip(str(e))
        print(f"\n{'─' * 58}")
        print(f"⊘ НАБОР ПРЕРВАН БЕЗ ИЗМЕРЕНИЯ: {e}")
        return 0
    except Exception as e:
        print(f"\n✗ набор прерван: {type(e).__name__}: {e}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'─' * 58}")
    if SKIPPED:
        print(f"⊘ пропущено частей: {len(SKIPPED)} — " + "; ".join(SKIPPED))
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
