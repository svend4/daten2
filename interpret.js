// interpret.js — детерминированные ответы о работе файрвола (фолбэк без ключа).
const store = require('./store');

function ask(_session, text) {
  const low = (text || '').toLowerCase();
  const s = store.stats();
  if (!s.total) return { reply: 'Пока нет решений — отправьте ввод/вызов на проверку.', engine: 'rules' };

  if (/заблок|блок|отклон|block|отбит|атак/.test(low)) {
    const cats = Object.entries(s.byCategory).sort((a, b) => b[1] - a[1]).slice(0, 6);
    return { reply: `Заблокировано: ${s.counts.block || 0}, санитизировано: ${s.counts.sanitize || 0}, урезано: ${s.counts['allow-clamped'] || 0}.\nЧастые срабатывания:\n` + (cats.length ? cats.map(([c, n]) => `• ${c}: ${n}`).join('\n') : '—'), engine: 'rules' };
  }
  if (/категор|тип|причин|срабат/.test(low)) {
    const cats = Object.entries(s.byCategory).sort((a, b) => b[1] - a[1]);
    if (!cats.length) return { reply: 'Срабатываний не было.', engine: 'rules' };
    return { reply: 'Срабатывания по категориям:\n' + cats.map(([c, n]) => `• ${c}: ${n}`).join('\n'), engine: 'rules' };
  }
  if (/послед|недавн|лог|recent|истори/.test(low)) {
    const r = store.recent(8);
    return { reply: 'Последние решения:\n' + r.map((x) => `• [${x.surface}] ${x.action} (риск ${x.risk})${x.categories && x.categories.length ? ' — ' + x.categories.join(', ') : ''}`).join('\n'), engine: 'rules' };
  }
  const c = s.counts;
  return { reply: `Проверено решений: ${s.total}. allow ${c.allow || 0} · sanitize ${c.sanitize || 0} · allow-clamped ${c['allow-clamped'] || 0} · block ${c.block || 0} · redact ${c.redact || 0}.`, engine: 'rules' };
}

module.exports = { ask };
