// semver.js — минимальный semver: разбор x.y.z и сравнение.
function parse(v) {
  const m = String(v || '').trim().match(/^(\d+)\.(\d+)\.(\d+)$/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}
function valid(v) { return parse(v) != null; }
function compare(a, b) {
  const pa = parse(a), pb = parse(b);
  if (!pa || !pb) return 0;
  for (let i = 0; i < 3; i++) if (pa[i] !== pb[i]) return pa[i] - pb[i];
  return 0;
}
module.exports = { parse, valid, compare };
