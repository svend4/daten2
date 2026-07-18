// hashchain.js — tamper-evident цепочка: каждое событие хэшируется вместе с хэшем
// предыдущего. Любая пост-фактум правка журнала ломает цепь → журнал доказуемо
// append-only. Детерминированный SHA-256 (без соли/времени внутри хэша).
const crypto = require('crypto');

const canon = (obj) => JSON.stringify(obj, Object.keys(obj).sort());
function linkHash(prevHash, payload) {
  return crypto.createHash('sha256').update(String(prevHash) + '|' + canon(payload)).digest('hex');
}

// events: [{ ...payload, hash }] — проверяем, что каждый hash пересчитывается.
function verifyChain(events) {
  let prev = 'genesis';
  for (let i = 0; i < events.length; i++) {
    const { hash, ...payload } = events[i];
    const expect = linkHash(prev, payload);
    if (expect !== hash) return { ok: false, brokenAt: i };
    prev = hash;
  }
  return { ok: true, head: prev, length: events.length };
}

module.exports = { linkHash, verifyChain };
