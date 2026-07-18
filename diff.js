// diff.js — глубокое структурное сравнение канонических форм с путём до расхождения.
function deepDiff(ref, act, path = '') {
  const out = [];
  const ta = Array.isArray(ref), tb = Array.isArray(act);
  if (ta || tb) {
    if (!ta || !tb) { out.push({ path, reference: ref, actual: act }); return out; }
    if (ref.length !== act.length) out.push({ path: (path || '') + '.length', reference: ref.length, actual: act.length });
    const n = Math.min(ref.length, act.length);
    for (let i = 0; i < n; i++) out.push(...deepDiff(ref[i], act[i], `${path}[${i}]`));
    return out;
  }
  const oa = ref && typeof ref === 'object', ob = act && typeof act === 'object';
  if (oa || ob) {
    if (!oa || !ob) { out.push({ path, reference: ref, actual: act }); return out; }
    const keys = new Set([...Object.keys(ref), ...Object.keys(act)]);
    for (const k of keys) out.push(...deepDiff(ref[k], act[k], path ? `${path}.${k}` : k));
    return out;
  }
  if (ref !== act) out.push({ path, reference: ref, actual: act });
  return out;
}
module.exports = { deepDiff };
