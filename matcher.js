// matcher.js — типовые матчеры (Pact-style «like»): сравниваем СТРУКТУРУ и ТИПЫ,
// а не конкретные значения. Поэтому изменчивый order_number/цена проходят по типу.
function match(m, v, path, out) {
  if (m === 'any') return;
  if (m === 'number') { if (typeof v !== 'number' || Number.isNaN(v)) out.push({ path: path || '/', expected: 'number', got: typeof v }); return; }
  if (m === 'string') { if (typeof v !== 'string') out.push({ path: path || '/', expected: 'string', got: typeof v }); return; }
  if (m === 'boolean') { if (typeof v !== 'boolean') out.push({ path: path || '/', expected: 'boolean', got: typeof v }); return; }
  if (m && m.array) {
    if (!Array.isArray(v)) { out.push({ path: path || '/', expected: 'array', got: typeof v }); return; }
    v.forEach((x, i) => match(m.array, x, `${path}[${i}]`, out));
    return;
  }
  if (m && m.object) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) { out.push({ path: path || '/', expected: 'object', got: Array.isArray(v) ? 'array' : typeof v }); return; }
    for (const k of Object.keys(m.object)) match(m.object[k], v[k], `${path}.${k}`, out);
    return; // лишние поля у провайдера допускаются (совместимость вперёд)
  }
  if (v !== m) out.push({ path: path || '/', expected: m, got: v }); // литерал — точное совпадение
}

function verifyBody(matcher, body) {
  const out = [];
  match(matcher, body, '', out);
  return { ok: out.length === 0, mismatches: out.slice(0, 25) };
}

module.exports = { match, verifyBody };
