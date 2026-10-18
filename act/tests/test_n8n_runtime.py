"""Узел n8n на рантайме: execute() настоящего NppAct.node.js против настоящего шлюза.

test_n8n.py проверяет файлы пакета и `node --check`, а узел выполняет через
минимальный самописный хост. Этот тест идёт дальше: ошибки берутся из настоящего
пакета n8n-workflow (npm), а запросы уходят по сети в поднятый подпроцессом шлюз.

Честная граница — что настоящее, а что нет:

  настоящее — пакет n8n-workflow из npm (NodeOperationError и типы ошибок n8n);
              сам узел act/integrations/n8n/nodes/NppAct/NppAct.node.js;
              шлюз `python3 -m act.gateway` вместе с губернатором и журналом;
              сервис заведения `python3 -m act.services.venue.server`;
              HTTP — настоящий fetch по сети к поднятым подпроцессам.
  наше      — контекст исполнения: getNodeParameter, helpers.httpRequest,
              getNode, continueOnFail. Он написан в хосте-обвязке и повторяет
              подписи n8n, но сам n8n здесь не запускается: нет его движка,
              очередей, UI и передачи items между узлами.

Что проверяется:
  1. dryRun=true и dryRun по умолчанию: решение получено, слот свободен, журнал пуст.
  2. dryRun=false: удержание создано, слот занят (по GET /api/slots), в журнале
     есть intent/decision/execution/outcome.
  3. Обязательство без согласия даёт escalate; узел его не исполняет, и в журнале
     нет execution — ни с предварительным вопросом, ни без него.
  4. Ошибка шлюза (404 на неверном пути, 502 при недоступном сервисе) становится
     NodeOperationError, а не молчаливым выходом с verdict=unknown.
  5. Узел не ходит в сервис напрямую. Все действия оставили запись в журнале
     шлюза. Контрольный опыт: прямой вызов сервиса журнал не трогает, так что
     отсутствие записи здесь было бы видно.

Порты не фиксированы: pick_port() берёт порт у ОС и проверяет его дважды —
молчит по HTTP и свободен для bind. Пакет ставится в свой временный каталог
внутри TMPDIR, не в репозиторий; `--ignore-scripts` не даёт выполниться
install-скриптам чужого пакета.

Запуск:  python3 -m act.tests.test_n8n_runtime
Код выхода: 0 — все проверки пройдены; 1 — есть провалы;
            77 — тест ПРОПУЩЕН (нет node или npm, либо n8n-workflow не
            установился из npm). Пропуск печатается с причиной: он не
            означает, что узел проверен.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
N8N = ROOT / "act" / "integrations" / "n8n"
NODE_JS = N8N / "nodes" / "NppAct" / "NppAct.node.js"
PACKAGE_NAME = "n8n-workflow"
NODE_NAME = "venue-clinic-nord"

EXIT_SKIP = 77

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


# ────────────────────────────────────────────────────────────────────────────
# Порты и HTTP
# ────────────────────────────────────────────────────────────────────────────


def answers_http(port: int) -> bool:
    """Отвечает ли что-то по HTTP на порту. Любой HTTP-ответ, даже 404, — занято."""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def pick_port() -> int:
    """Свободный порт: молчит по HTTP И свободен для bind.

    Двух проверок по отдельности мало: молчащий порт может быть занят процессом,
    не говорящим по HTTP, а успешный bind не говорит, кто ответит на запрос.
    Поэтому проверяются оба условия, а bind повторяется уже после HTTP-проверки.
    """
    for _ in range(50):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if answers_http(port):
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("не удалось подобрать свободный порт")


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def post_json(url: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait_identified(url: str, is_ours, attempts: int = 100) -> bool:
    """Ждать не просто ответа, а ОПОЗНАННОГО ответа: по тому же адресу может
    отвечать посторонний процесс (§10 SPEC: совпадения адреса недостаточно)."""
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if is_ours(json.loads(r.read())):
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


# ────────────────────────────────────────────────────────────────────────────
# Установка настоящего n8n-workflow
# ────────────────────────────────────────────────────────────────────────────


def install_n8n_workflow(base: Path) -> tuple[Path | None, str]:
    """Поставить n8n-workflow в каталог внутри base. Вернуть (node_modules, причина пропуска)."""
    if shutil.which("node") is None:
        return None, "в системе нет node"
    if shutil.which("npm") is None:
        return None, "в системе нет npm"
    pkg_dir = base / "n8n-runtime"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.json").write_text(
        json.dumps({"name": "npp-act-n8n-runtime-check", "version": "0.0.0", "private": True}),
        encoding="utf-8")
    try:
        proc = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--ignore-scripts", PACKAGE_NAME],
            cwd=str(pkg_dir), capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None, f"npm install {PACKAGE_NAME} не уложился в 600 с"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip()[-300:]
        return None, f"npm install {PACKAGE_NAME} завершился с кодом {proc.returncode}: {tail}"
    modules = pkg_dir / "node_modules"
    if not (modules / PACKAGE_NAME / "package.json").is_file():
        return None, f"после npm install пакета {PACKAGE_NAME} нет в node_modules"
    return modules, ""


# ────────────────────────────────────────────────────────────────────────────
# Хост-обвязка: настоящий узел, наш контекст, настоящий fetch
# ────────────────────────────────────────────────────────────────────────────

HARNESS = r"""
'use strict';
// Хост-обвязка вместо n8n. Контекст исполнения написан здесь: его подписи
// повторяют n8n — getNodeParameter(name, itemIndex, fallback) в execute и
// getNodeParameter(name, fallback) в loadOptions. httpRequest ходит настоящим fetch.
// Ошибки берутся из настоящего пакета n8n-workflow, который требуется по NODE_PATH.
const fs = require('fs');

const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const nodeFile = process.argv[3];
const calls = [];

function emit(obj) {
	process.stdout.write(JSON.stringify(obj));
}

async function httpRequest(opts) {
	calls.push({ method: opts.method || 'GET', url: opts.url });
	const headers = { accept: 'application/json' };
	let body;
	if (opts.body !== undefined) {
		body = JSON.stringify(opts.body);
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
	try { parsed = JSON.parse(text); } catch (e) { /* не JSON — отдаём строкой, как n8n */ }
	// Как в n8n при ignoreHttpStatusErrors: статус сам по себе исключения не порождает.
	if (!res.ok && !opts.ignoreHttpStatusErrors) {
		const err = new Error(`HTTP ${res.status}`);
		err.response = { statusCode: res.status, body: parsed };
		throw err;
	}
	if (opts.returnFullResponse) return { statusCode: res.status, body: parsed };
	return parsed;
}

async function main() {
	const wf = require('n8n-workflow');
	const resolved = require.resolve('n8n-workflow');
	if (job.mode === 'probe') {
		emit({
			ok: true,
			resolved,
			version: require('n8n-workflow/package.json').version,
			hasNodeOperationError: typeof wf.NodeOperationError === 'function',
		});
		return;
	}

	const { NppAct } = require(nodeFile);
	const node = new NppAct();
	// Значения по умолчанию берутся из описания узла, как это делает n8n для не заданных полей.
	const defaults = {};
	for (const p of node.description.properties) defaults[p.name] = p.default;
	const given = job.params || {};
	const nodeInfo = {
		name: 'NPP-Act', type: 'n8n-nodes-npp-act.nppAct', typeVersion: 1,
		position: [0, 0], parameters: given,
	};

	function makeCtx(items) {
		return {
			getNodeParameter(...args) {
				const name = args[0];
				const fallback = args.length === 2 ? args[1] : args[2];
				if (Object.prototype.hasOwnProperty.call(given, name)) return given[name];
				if (defaults[name] !== undefined) return defaults[name];
				return fallback;
			},
			getCurrentNodeParameter: (name) => (job.current || {})[name],
			getInputData: () => items,
			getNode: () => nodeInfo,
			continueOnFail: () => false,
			helpers: { httpRequest },
		};
	}

	try {
		if (job.mode === 'loadOptions') {
			const out = await node.methods.loadOptions[job.method].call(makeCtx([]));
			emit({ ok: true, out, calls, resolved });
			return;
		}
		const items = job.items || [{ json: {} }];
		const result = await node.execute.call(makeCtx(items));
		emit({ ok: true, out: result[0].map((entry) => entry.json), calls, resolved });
	} catch (e) {
		emit({
			ok: false,
			error: String((e && e.message) || e),
			nodeOperationError: Boolean(e && e instanceof wf.NodeOperationError),
			errorClass: e && e.constructor ? e.constructor.name : '',
			itemIndex: e && e.context ? e.context.itemIndex : undefined,
			calls,
			resolved,
		});
	}
}

main().catch((e) => {
	emit({ ok: false, crash: String((e && e.stack) || e) });
});
"""


class NodeRunner:
    """Запуск узла одним процессом node на одну задачу."""

    def __init__(self, base: Path, modules: Path):
        self.base = base
        self.modules = modules
        self.harness = base / "n8n-harness.js"
        self.harness.write_text(HARNESS, encoding="utf-8")
        self.env = {**os.environ, "NODE_PATH": str(modules)}
        self.count = 0
        self.all_calls: list[dict] = []

    def run(self, job: dict) -> dict:
        self.count += 1
        job_file = self.base / f"job-{self.count}.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        try:
            proc = subprocess.run(
                ["node", str(self.harness), str(job_file), str(NODE_JS)],
                capture_output=True, text=True, timeout=120, env=self.env)
        except subprocess.TimeoutExpired:
            return {"ok": False, "crash": "node не уложился в 120 с"}
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"ok": False, "crash": (proc.stderr or "пустой вывод").strip()[-300:]}
        result = json.loads(proc.stdout)
        self.all_calls.extend(result.get("calls", []))
        return result


def execute_job(params: dict) -> dict:
    """Задача execute(): параметры узла задаются явно; остальное берётся из описания узла."""
    base = {"operation": "perform", "gatewayUrl": "", "verifyGateway": True, "timeoutMs": 20000}
    base.update(params)
    return {"mode": "execute", "params": base}


def first_out(result: dict) -> dict:
    return (result.get("out") or [{}])[0]


# ────────────────────────────────────────────────────────────────────────────
# Журнал и слоты (читаются напрямую, мимо узла — это и есть независимая сторона)
# ────────────────────────────────────────────────────────────────────────────


def ledger_head(gw: str) -> int:
    """Отметка журнала: seq последней записи, -1 для пустого журнала.

    Нумерация журнала начинается с 0, поэтому пустой журнал нельзя отмечать нулём:
    первая запись с seq=0 потерялась бы при фильтре «seq > отметка».
    """
    recs = get_json(f"{gw}/act/ledger?limit=500")
    return recs[-1]["seq"] if recs else -1


def ledger_since(gw: str, seq: int) -> list[dict]:
    return [r for r in get_json(f"{gw}/act/ledger?limit=500") if r["seq"] > seq]


def free_slot_ids(venue: str) -> set[int]:
    return {s["id"] for s in get_json(f"{venue}/api/slots")}


# ────────────────────────────────────────────────────────────────────────────
# Подпроцессы: venue, шлюз, шлюз на мёртвый сервис
# ────────────────────────────────────────────────────────────────────────────


class Stack:
    """Поднять сервис и шлюзы подпроцессами и опознать каждый по ответу /api/health."""

    def __init__(self, base: Path):
        self.base = base
        self.procs: list[subprocess.Popen] = []
        self.logs: list = []

    def _spawn(self, args: list[str], name: str) -> None:
        log = (self.base / f"{name}.log").open("w", encoding="utf-8")
        self.logs.append(log)
        self.procs.append(subprocess.Popen(
            [sys.executable, "-m", *args], cwd=str(ROOT), stdout=log, stderr=log))

    def start(self) -> tuple[str, str, str, str]:
        self.venue_port = pick_port()
        self.gw_port = pick_port()
        self.gw_dead_port = pick_port()
        self.dead_venue_port = pick_port()  # сюда намеренно никто не запускается
        self.venue = f"http://127.0.0.1:{self.venue_port}"
        self.gw = f"http://127.0.0.1:{self.gw_port}"
        self.gw_dead = f"http://127.0.0.1:{self.gw_dead_port}"
        self.dead_venue = f"http://127.0.0.1:{self.dead_venue_port}"
        self.ledger_main = self.base / "gw.jsonl"
        self.ledger_dead = self.base / "gw-dead.jsonl"

        self._spawn(["act.services.venue.server", "--port", str(self.venue_port),
                     "--db", str(self.base / "venue.db"), "--reset"], "venue")
        if not wait_identified(f"{self.venue}/api/health",
                               lambda b: b.get("service") == "venue"):
            raise RuntimeError("сервис заведения не опознан по /api/health")

        self._spawn(["act.gateway", "--port", str(self.gw_port),
                     "--manifests", str(ROOT / "act" / "manifests"),
                     "--ledger", str(self.ledger_main),
                     "--budget", "300", "--owner", "person:n8n",
                     "--rebind", f"{NODE_NAME}={self.venue}"], "gateway")
        if not wait_identified(f"{self.gw}/api/health",
                               lambda b: b.get("runtime") == "npp-act"):
            raise RuntimeError("шлюз рантайма не опознан по /api/health")

        self._spawn(["act.gateway", "--port", str(self.gw_dead_port),
                     "--manifests", str(ROOT / "act" / "manifests"),
                     "--ledger", str(self.ledger_dead), "--budget", "300",
                     "--owner", "person:n8n",
                     "--rebind", f"{NODE_NAME}={self.dead_venue}"], "gateway-dead")
        if not wait_identified(f"{self.gw_dead}/api/health",
                               lambda b: b.get("runtime") == "npp-act"):
            raise RuntimeError("шлюз на недоступный сервис не опознан по /api/health")
        return self.venue, self.gw, self.gw_dead, self.dead_venue

    def stop(self) -> None:
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        for log in self.logs:
            log.close()


# ────────────────────────────────────────────────────────────────────────────
# Сценарии
# ────────────────────────────────────────────────────────────────────────────


def scenario_loading(runner: NodeRunner, base: Path) -> None:
    print("\nНастоящий пакет и загрузка узла:")
    probe = runner.run({"mode": "probe"})
    resolved = probe.get("resolved", "")
    check("n8n-workflow загружен из своего каталога внутри TMPDIR",
          str(base) in resolved and PACKAGE_NAME in resolved, resolved[-100:] or probe.get("crash", ""))
    check("пакет экспортирует NodeOperationError", probe.get("hasNodeOperationError") is True)

    # Статическая проверка текста узла: единственный внешний импорт — n8n-workflow.
    # Это чтение исходника, поэтому оно дополняет рантайм, а не заменяет его.
    src = NODE_JS.read_text(encoding="utf-8")
    imports = set(re.findall(r"require\('([^']+)'\)", src))
    check("в тексте узла единственный внешний импорт — n8n-workflow",
          imports == {PACKAGE_NAME}, str(sorted(imports)))


def scenario_catalog(runner: NodeRunner, gw: str) -> None:
    print("\nВыпадающие списки через настоящий пакет читают живой шлюз:")
    r = runner.run({"mode": "loadOptions", "method": "getServices",
                    "params": {"gatewayUrl": gw, "catalogSource": "gateway"}})
    values = {o.get("value") for o in r.get("out", [])}
    check("getServices отдал сервис заведения", r.get("ok") and NODE_NAME in values,
          r.get("error") or r.get("crash", ""))
    r = runner.run({"mode": "loadOptions", "method": "getVerbs",
                    "current": {"service": NODE_NAME},
                    "params": {"gatewayUrl": gw, "catalogSource": "gateway", "service": NODE_NAME}})
    check("getVerbs отдал глаголы этого сервиса с пометкой последствия",
          r.get("ok") and len(r.get("out", [])) == 5
          and any("commit" in o.get("name", "") for o in r.get("out", [])),
          r.get("error") or r.get("crash", ""))


def scenario_dry_run(runner: NodeRunner, stack: Stack, slot: int) -> None:
    print("\nСухой прогон: решение есть, исполнения нет:")
    seq = ledger_head(stack.gw)
    free_before = free_slot_ids(stack.venue)
    r = runner.run(execute_job({
        "gatewayUrl": stack.gw, "service": NODE_NAME, "verb": "slot.hold",
        "payload": {"slot_id": slot}, "dryRun": True,
    }))
    out = first_out(r)
    check("dryRun=true: узел получил verdict=admit", r.get("ok") and out.get("verdict") == "admit",
          r.get("error") or r.get("crash", ""))
    check("dryRun=true: executed=false, dry_run=true",
          out.get("executed") is False and out.get("dry_run") is True)
    check("dryRun=true: слот остался свободным", slot in free_slot_ids(stack.venue))
    check("dryRun=true: журнал не изменился", ledger_since(stack.gw, seq) == [])
    check("dryRun=true: в списке свободных ровно те же слоты",
          free_slot_ids(stack.venue) == free_before)

    seq = ledger_head(stack.gw)
    r = runner.run(execute_job({
        "gatewayUrl": stack.gw, "service": NODE_NAME, "verb": "slot.hold",
        "payload": {"slot_id": slot},
    }))
    out = first_out(r)
    check("dryRun не задан: по умолчанию сухой прогон, исполнения нет",
          r.get("ok") and out.get("dry_run") is True and out.get("executed") is False
          and slot in free_slot_ids(stack.venue) and ledger_since(stack.gw, seq) == [],
          r.get("error") or str(out)[:200])


def scenario_commit_reserve(runner: NodeRunner, stack: Stack, slot: int) -> dict | None:
    print("\nНастоящее удержание через узел (dryRun=false):")
    seq = ledger_head(stack.gw)
    r = runner.run(execute_job({
        "gatewayUrl": stack.gw, "service": NODE_NAME, "verb": "slot.hold",
        "payload": {"slot_id": slot}, "dryRun": False,
    }))
    out = first_out(r)
    # Форма выхода узла: status и result (тело ответа сервиса) — на верхнем уровне.
    hold_body = out.get("result") or {}
    check("dryRun=false: решение admit, исполнено",
          r.get("ok") and out.get("verdict") == "admit" and out.get("executed") is True,
          r.get("error") or str(out)[:200])
    check("предварительный вопрос пройден перед настоящим запросом",
          out.get("stopped_by") is None and out.get("dry_run") is False)
    check("сервис вернул удержание (201 и hold_id)",
          out.get("status") == 201 and str(hold_body.get("hold_id", "")).startswith("hold_"),
          str(out)[:200])
    check("слот занят — проверено по GET /api/slots, а не по ответу узла",
          slot not in free_slot_ids(stack.venue))
    kinds = {rec["kind"] for rec in ledger_since(stack.gw, seq)}
    check("действие узла записано в журнал шлюза (intent, decision, execution, outcome)",
          {"intent", "decision", "execution", "outcome"} <= kinds, str(sorted(kinds)))
    execs = [rec for rec in ledger_since(stack.gw, seq) if rec["kind"] == "execution"]
    check("запись execution относится к нашему глаголу",
          any(rec["payload"].get("verb") == "slot.hold" and rec["payload"].get("ok") is True
              for rec in execs))
    if not hold_body.get("hold_id"):
        return None
    return hold_body


def scenario_escalate(runner: NodeRunner, stack: Stack, hold: dict) -> None:
    print("\nОбязательство без согласия: узел не обходит губернатора:")
    job = {
        "gatewayUrl": stack.gw, "service": NODE_NAME, "verb": "booking.create",
        "payload": {"hold_id": hold["hold_id"], "name": "Узел", "max_money": 50},
        "idempotencyKey": "n8n-rt-escalate-1",
        "hold": {"hold_id": hold["hold_id"], "expires_at": hold.get("expires_at")},
        "dryRun": False,
    }

    seq = ledger_head(stack.gw)
    r = runner.run(execute_job(dict(job, preflight=True)))
    out = first_out(r)
    check("с предварительным вопросом: verdict=escalate",
          r.get("ok") and out.get("verdict") == "escalate", r.get("error") or str(out)[:240])
    check("с предварительным вопросом: остановлено до настоящего запроса",
          out.get("stopped_by") == "preflight" and out.get("executed") is False)
    check("обязательство не исполнено — в журнале нет execution",
          not any(rec["kind"] == "execution" for rec in ledger_since(stack.gw, seq)))
    check("в решении названа причина", bool(out.get("reason")), str(out)[:200])

    seq = ledger_head(stack.gw)
    r = runner.run(execute_job(dict(job, preflight=False)))
    out = first_out(r)
    check("без предварительного вопроса: решение escalate от шлюза, исполнения нет",
          r.get("ok") and out.get("verdict") == "escalate" and out.get("executed") is False
          and out.get("stopped_by") is None, r.get("error") or str(out)[:240])
    check("без предварительного вопроса: execution в журнале нет",
          not any(rec["kind"] == "execution" for rec in ledger_since(stack.gw, seq)))


def scenario_gateway_errors(runner: NodeRunner, stack: Stack, slot: int) -> None:
    print("\nОшибка шлюза не становится молчаливым успехом:")

    # 404 от шлюза: неверный путь. verifyGateway выключен, чтобы ошибка пришла именно из /act/perform.
    r = runner.run(execute_job({
        "gatewayUrl": stack.gw + "/no-such-prefix", "verifyGateway": False,
        "service": NODE_NAME, "verb": "slot.hold", "payload": {"slot_id": slot}, "dryRun": True,
    }))
    check("404 от шлюза → ошибка узла",
          r.get("ok") is False and "404" in (r.get("error") or ""),
          r.get("error") or r.get("crash") or "узел вернул успех: " + str(first_out(r))[:200])
    check("ошибка узла — NodeOperationError из n8n-workflow",
          r.get("nodeOperationError") is True, r.get("errorClass", ""))
    check("ошибка привязана к элементу входа (itemIndex=0)", r.get("itemIndex") == 0,
          str(r.get("itemIndex")))

    # 502 от шлюза: сервис недоступен при настоящем исполнении. Preflight пройдёт (решение admit),
    # а настоящий запрос упрётся в мёртвый адрес заведения.
    seq = ledger_head(stack.gw_dead)
    free_before = free_slot_ids(stack.venue)
    r = runner.run(execute_job({
        "gatewayUrl": stack.gw_dead, "service": NODE_NAME, "verb": "slot.hold",
        "payload": {"slot_id": slot}, "dryRun": False,
    }))
    check("502 от шлюза при недоступном сервисе → ошибка узла",
          r.get("ok") is False and "502" in (r.get("error") or ""),
          r.get("error") or r.get("crash") or "узел вернул успех: " + str(first_out(r))[:200])
    check("и это NodeOperationError", r.get("nodeOperationError") is True)
    check("при ошибке шлюза слот настоящего сервиса не тронут",
          free_slot_ids(stack.venue) == free_before)
    check("шлюз не записал исполнения, которого не было",
          not any(rec["kind"] == "execution" for rec in ledger_since(stack.gw_dead, seq)))

    # Адрес сервиса вместо адреса рантайма: проверка должна упасть, а не пропустить.
    r = runner.run(execute_job({
        "gatewayUrl": stack.venue, "verifyGateway": True,
        "service": NODE_NAME, "verb": "slot.hold", "payload": {"slot_id": slot}, "dryRun": False,
    }))
    check("адрес сервиса вместо рантайма — NodeOperationError «не рантайм»",
          r.get("nodeOperationError") is True and "не рантайм" in (r.get("error") or ""),
          r.get("error") or str(first_out(r))[:200])
    check("попытка не изменила склад заведения", free_slot_ids(stack.venue) == free_before)


def scenario_no_bypass(runner: NodeRunner, stack: Stack, slot_control: int) -> None:
    print("\nУзел не ходит в сервис напрямую:")
    service_calls = [c for c in runner.all_calls if c["url"].startswith(stack.venue)]
    check("узел ни разу не обратился к заведению, кроме проверки /api/health",
          all(c["method"] == "GET" and c["url"].endswith("/api/health") for c in service_calls),
          str([c for c in service_calls if not c["url"].endswith("/api/health")])[:200])
    performs = [c for c in runner.all_calls if c["url"].endswith("/act/perform")]
    check("каждое действие узла шло POST на /act/perform (адрес рантайма)",
          len(performs) > 0 and all(c["method"] == "POST" for c in performs),
          str(performs[:3])[:200])

    # Контрольный опыт: прямой вызов сервиса (не через узел) оставляет слот занятым,
    # но в журнале шлюза следа не оставляет. Значит, наличие записей от узла — реальный признак маршрута.
    seq = ledger_head(stack.gw)
    status, _ = post_json(f"{stack.venue}/api/holds", {"slot_id": slot_control})
    taken = slot_control not in free_slot_ids(stack.venue)
    check("контроль: прямой вызов сервиса занял слот", status == 201 and taken, str(status))
    check("контроль: прямой вызов сервиса не оставил записи в журнале шлюза",
          ledger_since(stack.gw, seq) == [],
          str([r["kind"] for r in ledger_since(stack.gw, seq)]))
    check("журнал шлюза цел после всех сценариев",
          get_json(f"{stack.gw}/act/ledger/verify")["ok"] is True)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="npp_n8n_rt_"))
    stack = Stack(base)
    try:
        if not NODE_JS.is_file():
            print(f"✗ ПРОПУЩЕН: нет файла узла {NODE_JS}")
            return EXIT_SKIP
        modules, reason = install_n8n_workflow(base)
        if modules is None:
            print(f"⊘ ПРОПУЩЕН: {reason}")
            print("  Узел не проверен на настоящем n8n-workflow. Это не зелёный результат.")
            return EXIT_SKIP
        print(f"n8n-workflow установлен в {modules}")

        runner = NodeRunner(base, modules)
        scenario_loading(runner, base)

        venue, gw, _gw_dead, _dead_venue = stack.start()
        print(f"\nСервис заведения: {venue}   Шлюз рантайма: {gw}   "
              f"Шлюз на недоступный сервис: {stack.gw_dead}")

        slots = get_json(f"{venue}/api/slots")
        check("в заведении достаточно свободных слотов для сценариев", len(slots) >= 3,
              str(len(slots)))
        if len(slots) < 3:
            return 1
        slot, slot_other, slot_control = slots[0]["id"], slots[1]["id"], slots[2]["id"]

        scenario_catalog(runner, gw)
        scenario_dry_run(runner, stack, slot)
        hold = scenario_commit_reserve(runner, stack, slot)
        if hold is None:
            check("удержание получено для сценария обязательства", False)
        else:
            scenario_escalate(runner, stack, hold)
        scenario_gateway_errors(runner, stack, slot_other)
        scenario_no_bypass(runner, stack, slot_control)
    finally:
        stack.stop()
        shutil.rmtree(base, ignore_errors=True)

    print(f"\n{'─' * 58}")
    if FAILED:
        print(f"✗ ПРОВАЛЕНО: {FAILED}, пройдено {PASSED}")
        return 1
    print(f"✓ Все проверки пройдены ({PASSED}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
