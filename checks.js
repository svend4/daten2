// checks.js — библиотека утверждений для эвалов (возвращают { ok, msg }).
const ok = (msg) => ({ ok: true, msg });
const bad = (msg) => ({ ok: false, msg });

const isArray = (v, m) => (Array.isArray(v) ? ok(m || 'массив') : bad(`ожидался массив, получено ${typeof v}`));
const isNum = (v, m) => (typeof v === 'number' && !Number.isNaN(v) ? ok(m) : bad(`ожидалось число: ${JSON.stringify(v)}`));
const isStr = (v, m) => (typeof v === 'string' && v.length > 0 ? ok(m) : bad(`ожидалась непустая строка: ${JSON.stringify(v)}`));
const eq = (a, b, m) => (a === b ? ok(m) : bad(`${m || ''}: ${JSON.stringify(a)} ≠ ${JSON.stringify(b)}`));
const approx = (a, b, tol, m) => (Math.abs(a - b) <= (tol ?? 0.01) ? ok(m) : bad(`${m || ''}: ${a} ≉ ${b}`));
const status = (res, code, m) => (res.status === code ? ok(m) : bad(`${m || 'статус'}: ${res.status} ≠ ${code}`));
const statusIn = (res, codes, m) => (codes.includes(res.status) ? ok(m) : bad(`${m || 'статус'}: ${res.status} ∉ ${codes}`));

// объединить несколько проверок: pass только если все ok
function all(results) {
  const fails = results.filter((r) => !r.ok);
  return { ok: fails.length === 0, msg: fails.length ? fails.map((f) => f.msg).join('; ') : 'ok' };
}

module.exports = { ok, bad, isArray, isNum, isStr, eq, approx, status, statusIn, all };
