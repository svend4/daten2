// ledger.js — append-only журнал операционных решений ИИ (event sourcing).
// Два вида событий: `decision` (что выбрали, какие были альтернативы, с какой
// вероятностью — propensity) и `outcome` (наблюдённая награда выбранного действия).
// Награда НЕ мутирует decision — это отдельное событие → хэш-цепь остаётся целой.
// Состояние = свёртка событий. Так журнал остаётся честным: награды невыбранных
// действий мы НЕ выдумываем; их ценность оценивает off-policy оценщик (ope.js).
const { linkHash, verifyChain } = require('./hashchain');

function createLedger() {
  const events = [];
  let seq = 0;
  const head = () => (events.length ? events[events.length - 1].hash : 'genesis');
  function append(payload) {
    const hash = linkHash(head(), payload);
    events.push({ ...payload, hash });
    return hash;
  }

  // decision: {domain, context, actions:[{id,...attrs}], chosen:id, propensity:(0..1], ts?}
  function decision(d) {
    const id = 'd' + (++seq);
    append({ kind: 'decision', id, domain: d.domain || 'default', context: d.context || {}, actions: d.actions || [], chosen: d.chosen, propensity: d.propensity == null ? 1 : d.propensity, ts: d.ts == null ? seq : d.ts });
    return id;
  }
  // outcome: наблюдённая награда выбранного действия
  function outcome(ref, reward) { append({ kind: 'outcome', ref, reward, ts: ++seq }); return ref; }

  // свёртка: map id → решение с заполненной наградой
  function state() {
    const map = new Map();
    for (const e of events) {
      if (e.kind === 'decision') map.set(e.id, { id: e.id, domain: e.domain, context: e.context, actions: e.actions, chosen: e.chosen, propensity: e.propensity, ts: e.ts, reward: null });
      else if (e.kind === 'outcome' && map.has(e.ref)) map.get(e.ref).reward = e.reward;
    }
    return [...map.values()];
  }

  return {
    decision, outcome, state,
    events: () => events.slice(),
    verify: () => verifyChain(events),
    resolvedCount: () => state().filter((d) => d.reward != null).length,
    domains: () => [...new Set(state().map((d) => d.domain))],
  };
}

module.exports = { createLedger };
