// differ.js — сравнение ответов primary и candidate с нормализацией.
// Изменчивые поля (токены, метки времени) отбрасываются, чтобы не считать их
// расхождением. Возвращает список различий по путям.

function normalize(v, ignore) {
  if (Array.isArray(v)) return v.map((x) => normalize(x, ignore));
  if (v && typeof v === 'object') {
    const out = {};
    for (const k of Object.keys(v)) {
      if (ignore.includes(k)) continue;
      out[k] = normalize(v[k], ignore);
    }
    return out;
  }
  return v;
}

function deepDiff(a, b, path, out) {
  if (a === b) return;
  const ta = Array.isArray(a) ? 'array' : typeof a;
  const tb = Array.isArray(b) ? 'array' : typeof b;
  if (ta !== tb) { out.push({ path: path || '/', type: 'type', a: ta, b: tb }); return; }
  if (ta === 'array') {
    if (a.length !== b.length) out.push({ path: path || '/', type: 'length', a: a.length, b: b.length });
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) deepDiff(a[i], b[i], `${path}[${i}]`, out);
    return;
  }
  if (ta === 'object' && a && b) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const k of keys) {
      if (!(k in a)) { out.push({ path: `${path}.${k}`, type: 'missing-in-primary', b: b[k] }); continue; }
      if (!(k in b)) { out.push({ path: `${path}.${k}`, type: 'missing-in-candidate', a: a[k] }); continue; }
      deepDiff(a[k], b[k], `${path}.${k}`, out);
    }
    return;
  }
  out.push({ path: path || '/', type: 'value', a, b });
}

// compare(primaryBody, candidateBody, ignore) → { match, diffs }
function compare(pBody, cBody, ignore = []) {
  const out = [];
  deepDiff(normalize(pBody, ignore), normalize(cBody, ignore), '', out);
  return { match: out.length === 0, diffs: out.slice(0, 25) };
}

module.exports = { compare, normalize };
