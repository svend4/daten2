// runner.js — движок property-based: гоняет свойство на многих входах; при первом
// провале СЖИМАЕТ вход (shrink) до минимального контрпримера.
const { client } = require('./http');
const gen = require('./gen');
const properties = require('./properties');

const hash = (s) => { let h = 0; for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0; return h >>> 0; };

async function shrinkFail(prop, ctx, input) {
  let current = input, steps = 0, guard = 0;
  while (guard++ < 100) {
    const candidates = prop.shrink ? prop.shrink(current) : [];
    let found = null;
    for (const c of candidates) { const r = await prop.prop(ctx, c); if (!r.ok) { found = c; break; } }
    if (found) { current = found; steps++; } else break;
  }
  return { input: current, steps };
}

async function check(prop, ctx, { iterations = 40, seed = 1 } = {}) {
  const rng = gen.makeRng(seed + hash(prop.id));
  for (let i = 0; i < iterations; i++) {
    const input = prop.gen ? prop.gen(ctx, rng) : {};
    let res;
    try { res = await prop.prop(ctx, input); } catch (e) { res = { ok: false, detail: 'исключение: ' + e.message }; }
    if (!res.ok) {
      const sh = await shrinkFail(prop, ctx, input);
      return { id: prop.id, name: prop.name, ok: false, tested: i + 1, detail: res.detail, counterexample: sh.input, shrinkSteps: sh.steps };
    }
  }
  return { id: prop.id, name: prop.name, ok: true, tested: iterations };
}

async function runAll(base, opts = {}) {
  const http = client(base);
  const cat = await http.get('/api/products');
  const catalog = Array.isArray(cat.body) ? cat.body : [];
  const priceMap = Object.fromEntries(catalog.map((p) => [p.id, Number(p.price)]));
  const ctx = { http, catalog, priceOf: (id) => priceMap[id] || 0 };
  const results = [];
  for (const p of properties) results.push(await check(p, ctx, opts));
  const held = results.filter((r) => r.ok).length;
  return { target: http.url, iterations: opts.iterations || 40, held, total: results.length, allHold: held === results.length, results };
}

module.exports = { runAll, check };
