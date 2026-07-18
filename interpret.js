// interpret.js — детерминированная сводка по конвейеру выката.
function ask(registry, text) {
  const low = (text || '').toLowerCase();
  const st = registry.stats();
  if (!st.versions) return { reply: 'Моделей ещё не выкатывали.', engine: 'rules' };

  if (/откат|rollback|инцидент|просад|деград|incident/.test(low)) {
    const inc = registry.incidents();
    if (!inc.length) return { reply: 'Авто-откатов не было — продакшн-модель держит SLO.', engine: 'rules' };
    return { reply: `Авто-откатов: ${inc.length}.\n` + inc.map((i) => `• ${i.from} → ${i.to}: ${i.reason}`).join('\n'), engine: 'rules' };
  }
  if (/продакшн|production|текущ|какая модель/.test(low)) {
    const p = registry.get(st.production);
    return { reply: p ? `В продакшне: ${p.version} (канареечное согласие ${p.canaryAgreement}).` : 'Продакшн-модель не назначена.', engine: 'rules' };
  }
  const rej = registry.all().filter((v) => v.state === 'rejected').length;
  return { reply: `Версий: ${st.versions}, в продакшне ${st.production || '—'}, отклонено гейтом ${rej}, авто-откатов ${st.incidents}.`, engine: 'rules' };
}
module.exports = { ask };
