// bus.js — append-only журнал доменных событий (event store) + подписчики (SSE/консьюмеры).
// Событие: { seq, type, at, source, payload }. Журнал неизменяем: события только добавляются.
const KNOWN = ['OrderPlaced', 'OrderStatusChanged', 'StockChanged', 'PriceChanged', 'ProductAdded', 'ProductRemoved', 'ProductViewed'];

let log = [];
let seq = 0;
const subs = new Set();

// at передаётся снаружи (в тестах — детерминированно); по умолчанию — время сервера
function append(type, payload, source, at) {
  const e = { seq: ++seq, type, at: at ?? Date.now(), source: source || 'ingest', payload: payload || {} };
  log.push(e);
  for (const fn of subs) { try { fn(e); } catch { /* подписчик не должен ронять шину */ } }
  return e;
}

const all = () => log.slice();
const since = (n) => log.filter((e) => e.seq > Number(n || 0));
const count = () => log.length;
const lastSeq = () => seq;

function subscribe(fn) { subs.add(fn); return () => subs.delete(fn); }
function reset() { log = []; seq = 0; }

module.exports = { KNOWN, append, all, since, count, lastSeq, subscribe, reset };
