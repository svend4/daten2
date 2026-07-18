// runner.js — верификация агента против поведенческого пакта.
// Каждое ожидание проверяется на СЕМЕЙСТВЕ формулировок (mutate); держится, только
// если проходят все. При смене модели/агента — сравнение с baseline → регрессии.
const { client } = require('./agent');
const mutate = require('./mutate');
const pact = require('./pact');

function assertReply(assert, reply) {
  for (const re of assert.mustMatch || []) if (!re.test(reply)) return { ok: false, reason: `нет ожидаемого (${re})` };
  for (const re of assert.mustNotMatch || []) if (re.test(reply)) return { ok: false, reason: `запрещённое присутствует (${re})` };
  return { ok: true };
}

async function check(exp, agent, judge) {
  let tested = 0;
  for (const input of exp.inputs) {
    for (const v of mutate.variants(input)) {
      tested++;
      let reply;
      try { reply = await agent.send(v); } catch (e) { return { id: exp.id, name: exp.name, category: exp.category, ok: false, tested, failedInput: v, reason: 'ошибка запроса: ' + e.message }; }
      const res = assertReply(exp.assert, reply);
      let ok = res.ok, reason = res.reason;
      if (ok && exp.rubric && judge) { const j = await judge(v, reply, exp.rubric).catch(() => null); if (j && j.pass === false) { ok = false; reason = 'LLM-судья: ' + (j.note || 'не соответствует'); } }
      if (!ok) return { id: exp.id, name: exp.name, category: exp.category, ok: false, tested, failedInput: v, reply: String(reply).slice(0, 140), reason };
    }
  }
  return { id: exp.id, name: exp.name, category: exp.category, ok: true, tested };
}

async function runAll(agentBase, { path, judge } = {}) {
  const agent = client(agentBase, path);
  const results = [];
  for (const exp of pact.expectations) results.push(await check(exp, agent, judge));
  const byCat = {};
  for (const r of results) { const c = (byCat[r.category] = byCat[r.category] || { total: 0, held: 0 }); c.total++; if (r.ok) c.held++; }
  const held = results.filter((r) => r.ok).length;
  return { agent: agent.url, consumer: pact.consumer, held, total: results.length, allHold: held === results.length, byCat, results };
}

// регрессии: держалось в baseline, но упало сейчас (и наоборот — исправления)
function compare(current, baseline) {
  if (!baseline) return { hasBaseline: false, regressions: [], fixes: [] };
  const bmap = Object.fromEntries(baseline.results.map((r) => [r.id, r.ok]));
  const regressions = [], fixes = [];
  for (const r of current.results) {
    if (bmap[r.id] === true && !r.ok) regressions.push({ id: r.id, name: r.name, reason: r.reason, failedInput: r.failedInput });
    if (bmap[r.id] === false && r.ok) fixes.push({ id: r.id, name: r.name });
  }
  return { hasBaseline: true, regressions, fixes };
}

module.exports = { runAll, compare, check };
