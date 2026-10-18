"""Тест интеграции с n8n: каталог последствий и настоящий узел на настоящем рантайме.

Дисциплина та же, что в test_act.py и test_gateway.py: никакой самосертификации.
Конкретно здесь это означает три вещи.

  1. Каталог проверяется по НАСТОЯЩИМ манифестам из act/manifests, а не по
     придуманному для теста образцу: расходится манифест — падает тест.
  2. Узел n8n запускается НАСТОЯЩИМ node и ходит по сети в НАСТОЯЩИЙ шлюз
     (`python3 -m act.gateway`), за которым стоит настоящий сервис заведения.
     Моком здесь является только сам n8n — хост, которого в репозитории нет;
     всё, что проверяется (узел, шлюз, губернатор, журнал, сервис), живое.
  3. Проверяется не «узел вернул 200», а главный инвариант: узел НЕ МОЖЕТ
     обойти губернатора. Отсюда проверки на dry_run, на отказ без ключа
     идемпотентности и на отказ работать с адресом сервиса вместо адреса
     рантайма.

Запуск:  python3 -m act.tests.test_n8n
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from act.npp_act import Registry  # noqa: E402

N8N = ROOT / "act" / "integrations" / "n8n"
NODE_JS = N8N / "nodes" / "NppAct" / "NppAct.node.js"
NODE_JSON = N8N / "nodes" / "NppAct" / "NppAct.node.json"
PACKAGE = N8N / "package.json"

def _free_port(start: int) -> int:
    """Свободный порт: молчит по HTTP И свободен для bind (двойная проверка).

    Фиксированные номера здесь уже однажды стали причиной молчаливого измерения
    чужого процесса в другом наборе; выбираем порт при загрузке модуля.
    """
    import socket
    for port in range(start, start + 400):
        if _answers(f"http://127.0.0.1:{port}/api/health"):
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("свободный порт не найден")


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5):
            return True
    except Exception:
        return False


GW_PORT = _free_port(8203)
VENUE_PORT = _free_port(GW_PORT + 1)
GUILD_PORT = _free_port(VENUE_PORT + 1)
GW = f"http://127.0.0.1:{GW_PORT}"
VENUE = f"http://127.0.0.1:{VENUE_PORT}"
GUILD = f"http://127.0.0.1:{GUILD_PORT}"

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


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def run_cli(*args: str) -> tuple[int, str, str]:
    """Запустить экспортёр как настоящий CLI: модулем, из корня репозитория."""
    proc = subprocess.run(
        [sys.executable, "-m", "act.integrations.n8n.export_catalog", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ────────────────────────────────────────────────────────────────────────────
# 1. Каталог: экспорт по настоящим манифестам
# ────────────────────────────────────────────────────────────────────────────

def test_export() -> dict:
    print("\nЭкспорт каталога — по настоящим манифестам:")

    code, out, err = run_cli("--format", "json")
    check("экспортёр отработал без ошибок", code == 0, err.strip()[:200])
    try:
        cat = json.loads(out)
    except json.JSONDecodeError as e:
        check("вывод — валидный JSON", False, str(e))
        return {}
    check("вывод — валидный JSON", True)
    check("объявлена версия расширения", cat.get("npp_act") == "1.0")

    ops = cat.get("operations", [])
    # Сверка с библиотекой, а не с ожиданием, записанным в тесте: добавят глагол
    # в манифест — обе величины вырастут вместе, подменят манифест — разойдутся.
    reg = Registry().load_dir(ROOT / "act/manifests").load_dir(ROOT / "act/manifests/levels")
    expected = sum(len(reg.manifest(s).capabilities) for s in reg.services())
    check("операций столько же, сколько объявлено глаголов",
          len(ops) == expected and cat["counts"]["operations"] == expected,
          f"{len(ops)} против {expected}")
    check("сервисы перечислены для выпадающего списка",
          [s["value"] for s in cat["services"]] == reg.services())

    effects = {o["effect"] for o in ops}
    check("в каталоге есть глаголы чтения", "read" in effects)
    check("в каталоге есть глаголы-обязательства", "commit" in effects)
    check("в каталоге есть обратимые удержания",
          any(o["effect"] == "reserve" and o["reversible"] and o["reverse"] for o in ops))

    committing = [o for o in ops if o["effect"] in ("commit", "money", "destroy")]
    check("обязательств нашлось достаточно для проверки", len(committing) >= 10,
          str(len(committing)))
    check("у каждого обязательства объявлено согласие",
          all(o["consent"] in ("notify", "confirm", "two_party") for o in committing),
          str([o["verb"] for o in committing if o["consent"] == "none"]))
    check("у каждого обязательства объявлена идемпотентность",
          all(o["idempotency"] != "none" and o["idempotency_in"] in ("header", "field")
              for o in committing),
          str([o["verb"] for o in committing if o["idempotency"] == "none"]))
    check("обязательство требует ключа и человека в явном виде",
          all(o["requires_idempotency_key"] for o in committing)
          and all(o["requires_human"] for o in committing if o["consent"] != "notify"))
    check("чтению сухой прогон не навязывается",
          all(o["recommended_dry_run"] is (o["effect"] != "read") for o in ops))

    # Каталог не должен превращаться в список адресов, по которым можно постучать.
    check("каталог не отдаёт адрес сервиса как адрес действия",
          all("base_url" not in o for o in ops))
    check("единственная дверь действия — эндпоинт рантайма",
          cat["gateway"]["perform"] == "/act/perform"
          and set(cat["gateway"]["request"]) == {"service", "verb", "payload",
                                                 "idempotency_key", "dry_run"})
    check("роли четырёх слоёв названы в самом каталоге",
          set(cat["roles"]) == {"catalog", "consequence", "execution", "restraint"})

    code, out, _ = run_cli("--format", "table")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    # Заголовок + две линейки + две строки сводки обрамляют ровно len(ops) строк.
    check("таблица содержит заголовок и все операции",
          code == 0 and lines[0].split()[0] == "СЕРВИС" and len(lines) == len(ops) + 5
          and all(any(o["verb"] in ln for ln in lines) for o in ops),
          f"строк {len(lines)} при {len(ops)} операциях")
    check("таблица напоминает, через что идёт действие",
          any("/act/perform" in ln for ln in lines))

    with tempfile.TemporaryDirectory() as t:
        dest = Path(t) / "catalog.json"
        code, out, err = run_cli("--format", "json", "--out", str(dest))
        check("--out записал файл", code == 0 and dest.is_file(), err.strip()[:120])
        check("файл содержит тот же каталог",
              json.loads(dest.read_text(encoding="utf-8"))["counts"]["operations"] == len(ops))
        check("на stdout остался отчёт о записи", "каталог записан" in out)

        code, out, _ = run_cli("--service", "venue-clinic-nord")
        one = json.loads(out)
        check("--service оставил только один сервис",
              code == 0 and {o["service"] for o in one["operations"]} == {"venue-clinic-nord"}
              and one["counts"]["operations"] == 5, str(one["counts"]))

        code, out, _ = run_cli("--effect", "commit")
        only = json.loads(out)
        check("--effect оставил только обязательства",
              code == 0 and {o["effect"] for o in only["operations"]} == {"commit"})

        # Половина каталога хуже отсутствующего каталога: битый манифест — отказ.
        bad = Path(t) / "bad"
        bad.mkdir()
        (bad / "broken.act.json").write_text(
            json.dumps({"npp_act": "1.0", "service": "broken", "base_url": "http://x",
                        "profile": "vendor", "capabilities": [{"id": "a.b"}]}),
            encoding="utf-8")
        code, out, err = run_cli("--manifests", str(bad))
        check("битый манифест отвергнут целиком",
              code == 2 and "отвергнут" in err and out.strip() == "", f"код {code}")

    # Второй способ запуска: файлом по пути, без -m.
    proc = subprocess.run([sys.executable, str(N8N / "export_catalog.py"), "--format", "json"],
                          cwd=str(Path.home()), capture_output=True, text=True, timeout=120)
    check("экспортёр работает и как скрипт по пути",
          proc.returncode == 0 and json.loads(proc.stdout)["counts"]["operations"] == len(ops),
          proc.stderr.strip()[:160])

    return cat


# ────────────────────────────────────────────────────────────────────────────
# 2. Файлы пакета n8n
# ────────────────────────────────────────────────────────────────────────────

def test_files() -> list[str]:
    print("\nПакет n8n — объявление узла:")

    pkg = json.loads(PACKAGE.read_text(encoding="utf-8"))
    check("package.json валиден и версия 1.0.0", pkg["version"] == "1.0.0")
    check("пакет помечен как community node",
          "n8n-community-node-package" in pkg["keywords"])
    check("поле n8n.nodes указывает на существующий файл",
          pkg["n8n"]["nodes"] == ["nodes/NppAct/NppAct.node.js"]
          and (N8N / pkg["n8n"]["nodes"][0]).is_file())
    check("API-ключей и внешних зависимостей нет",
          pkg["dependencies"] == {} and "n8n-workflow" in pkg.get("peerDependencies", {}))

    codex = json.loads(NODE_JSON.read_text(encoding="utf-8"))
    check("NppAct.node.json валиден как кодекс n8n",
          codex["node"] == "n8n-nodes-npp-act.nppAct"
          and codex["codexVersion"] == "1.0" and codex["nodeVersion"] == "1.0")
    declared = [p["name"] for p in codex["npp_act"]["parameters"]]
    required = {"operation", "gatewayUrl", "service", "verb", "payload",
                "idempotencyKey", "dryRun"}
    check("объявлены все заявленные поля узла", required <= set(declared),
          str(sorted(required - set(declared))))
    check("сухой прогон объявлен включённым по умолчанию",
          next(p for p in codex["npp_act"]["parameters"] if p["name"] == "dryRun")["default"] is True)
    check("кодекс объявляет контракт рантайма",
          codex["npp_act"]["runtime"]["perform"] == {"method": "POST", "path": "/act/perform"}
          and set(codex["npp_act"]["runtime"]["request_body"])
          >= {"service", "verb", "payload", "idempotency_key", "dry_run"})
    check("кодекс прямо говорит, что узел не является гейтом",
          "не гейт" in codex["npp_act"]["not_a_safety_boundary"])

    src = NODE_JS.read_text(encoding="utf-8")
    check("узел не знает других путей сервисов, кроме /api/health рантайма",
          src.count("'/api/") == 1 and "/api/health" in src)
    check("узел предупреждает о себе в собственном коде",
          "НЕ ЯВЛЯЕТСЯ ГАРАНТИЕЙ БЕЗОПАСНОСТИ" in src)
    return declared


# ────────────────────────────────────────────────────────────────────────────
# 3. Узел исполняется настоящим node
# ────────────────────────────────────────────────────────────────────────────

HARNESS = r"""
'use strict';
// Минимальный хост вместо n8n: единственное, чего нет в репозитории.
// Узел, шлюз, губернатор, журнал и сервис в этом прогоне настоящие.
const job = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const { NppAct } = require(process.argv[2]);

async function httpRequest(opts) {
	const headers = Object.assign({ accept: 'application/json' }, opts.headers || {});
	let body;
	if (opts.body !== undefined) {
		body = typeof opts.body === 'string' ? opts.body : JSON.stringify(opts.body);
		headers['content-type'] = 'application/json';
	}
	const res = await fetch(opts.url, {
		method: opts.method || 'GET',
		headers,
		body,
		signal: AbortSignal.timeout(opts.timeout || 30000),
	});
	const text = await res.text();
	let parsed = text;
	try { parsed = JSON.parse(text); } catch (e) { /* не JSON — отдаём как есть */ }
	if (!res.ok && !opts.ignoreHttpStatusErrors) {
		const err = new Error('HTTP ' + res.status);
		err.response = { statusCode: res.status, body: parsed };
		throw err;
	}
	if (opts.returnFullResponse) return { statusCode: res.status, body: parsed };
	return parsed;
}

const params = job.params || {};
const node = new NppAct();

async function main() {
	if (job.mode === 'loadOptions') {
		const ctx = {
			getNodeParameter: (name, fallback) => (params[name] !== undefined ? params[name] : fallback),
			getCurrentNodeParameter: (name) => (job.current || {})[name],
			getNode: () => ({ name: 'NPP-Act', type: 'n8n-nodes-npp-act.nppAct' }),
			helpers: { httpRequest },
		};
		return node.methods.loadOptions[job.method].call(ctx);
	}
	const items = job.items || [{ json: {} }];
	const ctx = {
		getInputData: () => items,
		getNodeParameter: (name, i, fallback) => (params[name] !== undefined ? params[name] : fallback),
		getNode: () => ({ name: 'NPP-Act', type: 'n8n-nodes-npp-act.nppAct' }),
		continueOnFail: () => false,
		helpers: { httpRequest },
	};
	const out = await node.execute.call(ctx);
	return out[0].map((entry) => entry.json);
}

main()
	.then((out) => { process.stdout.write(JSON.stringify({ ok: true, out: out })); })
	.catch((e) => { process.stdout.write(JSON.stringify({ ok: false, error: String(e.message || e) })); });
"""


def test_node_live(tmp: Path) -> None:
    harness = tmp / "harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    counter = {"n": 0}

    def run_node(params: dict, *, mode: str = "execute", method: str = "",
                 current: dict | None = None, items: list | None = None) -> dict:
        counter["n"] += 1
        job = tmp / f"job{counter['n']}.json"
        job.write_text(json.dumps({"mode": mode, "method": method, "params": params,
                                   "current": current or {}, "items": items},
                                  ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(["node", str(harness), str(NODE_JS), str(job)],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return {"ok": False, "error": f"node упал: {proc.stderr.strip()[:300]}"}
        return json.loads(proc.stdout or '{"ok":false,"error":"пустой ответ"}')

    def ledger_size() -> int:
        return len(get_json(f"{GW}/act/ledger?limit=500"))

    base = {"gatewayUrl": GW, "catalogSource": "gateway", "verifyGateway": True,
            "timeoutMs": 20000, "failOnBlock": False, "hold": {}, "payload": {}}

    print("\nУзел n8n — загрузка и форма:")
    check("node --check проходит",
          subprocess.run(["node", "--check", str(NODE_JS)],
                         capture_output=True).returncode == 0)
    described = run_node({}, mode="loadOptions", method="getServices")  # прогреет require
    probe = subprocess.run(
        ["node", "-e",
         f"const m=require({json.dumps(str(NODE_JS))});"
         "const d=new m.NppAct().description;"
         "process.stdout.write(JSON.stringify({name:d.name,version:d.version,"
         "props:d.properties.map(p=>({name:p.name,default:p.default})),"
         "inputs:d.inputs,outputs:d.outputs,"
         "lo:Object.keys(new m.NppAct().methods.loadOptions)}));"],
        capture_output=True, text=True, timeout=60)
    check("узел загружается настоящим node и описывает себя", probe.returncode == 0,
          probe.stderr.strip()[:200])
    desc = json.loads(probe.stdout)
    check("имя и версия узла", desc["name"] == "nppAct" and desc["version"] == 1)
    check("один вход и один выход", desc["inputs"] == ["main"] and desc["outputs"] == ["main"])
    check("выпадающие списки читают каталог",
          sorted(desc["lo"]) == ["getServices", "getVerbs"])
    props = {p["name"]: p["default"] for p in desc["props"]}
    check("сухой прогон включён по умолчанию", props.get("dryRun") is True)
    check("проверка адреса рантайма включена по умолчанию", props.get("verifyGateway") is True)
    return_declared = json.loads(NODE_JSON.read_text(encoding="utf-8"))["npp_act"]["parameters"]
    check("поля в JS и в NppAct.node.json совпадают точно",
          [p["name"] for p in return_declared] == list(props),
          f'{[p["name"] for p in return_declared]} против {list(props)}')

    print("\nУзел читает каталог живого рантайма и живого сервиса:")
    r = run_node(dict(base, operation="catalog"), mode="loadOptions", method="getServices")
    check("getServices вернул сервисы рантайма",
          r.get("ok") and any(o["value"] == "venue-clinic-nord" for o in r["out"]),
          str(r)[:200])
    r = run_node(dict(base, service="venue-clinic-nord"),
                 mode="loadOptions", method="getVerbs", current={"service": "venue-clinic-nord"})
    check("getVerbs подписывает глаголы последствием",
          r.get("ok") and len(r["out"]) == 5
          and any("commit" in o["name"] for o in r["out"]),
          str(r)[:200])
    r = run_node(dict(base, operation="catalog"))
    check("операция «каталог» отдала строки последствий",
          r.get("ok") and len(r["out"]) >= 9 and all("effect" in x for x in r["out"]),
          str(r)[:200])
    # Манифест берётся из сервиса, который публикует его по пути из SPEC §3.
    # Цех выбран потому, что у него этот путь работает: у сервиса заведения
    # /.well-known/npp-act.json отвечает 404 (ошибка в вычислении пути к файлу,
    # чужой модуль — здесь он только зафиксирован тестом, а не исправлен).
    r = run_node(dict(base, operation="catalog", catalogSource="manifest",
                      manifestUrl=f"{GUILD}/.well-known/npp-act.json"))
    check("узел читает настоящий манифест прямо у сервиса",
          r.get("ok") and len(r["out"]) == 19
          and {x["service"] for x in r["out"]} == {"freelance-guild"},
          str(r)[:200])
    check("в манифесте видно согласие обеих сторон на подпись контракта",
          r.get("ok") and any(x["verb"] == "contract.sign" and x["consent"] == "two_party"
                              and x["effect"] == "commit" for x in r["out"]),
          str(r)[:200])

    print("\nГлавный инвариант — узел не обходит губернатора:")
    before = ledger_size()
    free_before = len(get_json(f"{VENUE}/api/slots"))
    r = run_node(dict(base, operation="perform", service="venue-clinic-nord", verb="slot.hold",
                      payload={"slot_id": 1}, idempotencyKey="n8n-dry-1", dryRun=True))
    check("сухой прогон показал решение губернатора",
          r.get("ok") and r["out"][0]["verdict"] == "admit", str(r)[:200])
    check("сухой прогон ничего не исполнил", r["out"][0]["executed"] is False)
    check("после сухого прогона слоты у сервиса не тронуты",
          len(get_json(f"{VENUE}/api/slots")) == free_before)
    check("сухой прогон не оставил записей в журнале", ledger_size() == before,
          f"{before} → {ledger_size()}")

    r = run_node(dict(base, operation="perform", service="venue-clinic-nord", verb="slot.list",
                      payload={"day": "2026-10-12"}, dryRun=False, preflight=True))
    check("настоящее чтение прошло через рантайм и вернуло данные",
          r.get("ok") and r["out"][0]["executed"] is True
          and isinstance(r["out"][0]["result"], list) and r["out"][0]["result"],
          str(r)[:200])
    kinds = {rec["kind"] for rec in get_json(f"{GW}/act/ledger?limit=500")}
    check("действие узла записано в журнал рантайма",
          {"intent", "decision", "execution", "outcome"} <= kinds, str(sorted(kinds)))

    r = run_node(dict(base, operation="perform", service="venue-clinic-nord",
                      verb="booking.create", payload={"name": "Узел", "max_money": 50},
                      idempotencyKey="", dryRun=False, preflight=False))
    check("обязательство без ключа идемпотентности заблокировано",
          r.get("ok") and r["out"][0]["verdict"] == "block"
          and "идемпотент" in r["out"][0]["reason"], str(r)[:220])
    check("заблокированное обязательство не исполнено", r["out"][0]["executed"] is False)

    before = ledger_size()
    r = run_node(dict(base, operation="perform", service="venue-clinic-nord",
                      verb="booking.create", payload={"name": "Узел", "max_money": 50},
                      idempotencyKey="", dryRun=False, preflight=True))
    check("предварительный вопрос остановил узел до настоящего запроса",
          r.get("ok") and r["out"][0]["stopped_by"] == "preflight"
          and r["out"][0]["verdict"] == "block", str(r)[:220])
    check("остановленный запрос не дошёл до журнала", ledger_size() == before,
          f"{before} → {ledger_size()}")

    r = run_node(dict(base, operation="perform", service="venue-clinic-nord",
                      verb="booking.create", payload={"name": "Узел", "max_money": 50},
                      idempotencyKey="", dryRun=False, preflight=False, failOnBlock=True))
    check("с failOnBlock отказ губернатора становится ошибкой узла",
          r.get("ok") is False and "губернатор отказал" in r.get("error", ""), str(r)[:220])

    print("\nПопытка указать сервис вместо рантайма:")
    r = run_node(dict(base, operation="perform", gatewayUrl=VENUE,
                      service="venue-clinic-nord", verb="slot.list", dryRun=False))
    check("узел отказался работать с адресом сервиса",
          r.get("ok") is False and "не рантайм" in r.get("error", ""), str(r)[:220])
    check("попытка не изменила склад времени",
          len(get_json(f"{VENUE}/api/slots")) == free_before)

    r = run_node(dict(base, operation="perform", service="venue-clinic-nord",
                      verb="slot.hold", payload="это не JSON", dryRun=True))
    check("непригодный вход отвергнут до обращения к рантайму",
          r.get("ok") is False and "не является объектом JSON" in r.get("error", ""),
          str(r)[:220])

    check("журнал рантайма цел после всех попыток",
          get_json(f"{GW}/act/ledger/verify")["ok"] is True)


def main() -> int:
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        print("✗ в системе нет node — узел n8n проверить нечем")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="npp_n8n_"))
    procs: list[subprocess.Popen] = []
    try:
        test_export()
        test_files()

        procs.append(subprocess.Popen(
            [sys.executable, "-m", "act.services.venue.server",
             "--port", str(VENUE_PORT), "--db", str(tmp / "venue.db"), "--reset"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if not wait_up(f"{VENUE}/api/health"):
            print("✗ сервис заведения не поднялся")
            return 1

        procs.append(subprocess.Popen(
            [sys.executable, "-m", "act.services.freelance.server",
             "--port", str(GUILD_PORT), "--db", str(tmp / "guild.db"), "--reset"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if not wait_up(f"{GUILD}/api/health"):
            print("✗ сервис цеха не поднялся")
            return 1

        procs.append(subprocess.Popen(
            [sys.executable, "-m", "act.gateway",
             "--port", str(GW_PORT), "--ledger", str(tmp / "gw.jsonl"),
             "--budget", "300", "--owner", "person:n8n",
             "--rebind", f"venue-clinic-nord={VENUE}"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if not wait_up(f"{GW}/api/health"):
            print("✗ шлюз рантайма не поднялся")
            return 1
        print(f"\nШлюз рантайма на :{GW_PORT}, заведение на :{VENUE_PORT}")

        test_node_live(tmp)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
