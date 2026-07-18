// interpret.js — детерминированная сводка по реестру плагинов.
function ask(registry, text) {
  const low = (text || '').toLowerCase();
  const st = registry.stats();
  if (!st.versions) return { reply: 'Реестр пуст — опубликуйте плагин-бэкенд с манифестом.', engine: 'rules' };

  if (/отклон|reject|почему|провал|не прош/.test(low)) {
    const bad = registry.all().filter((r) => r.state === 'rejected');
    if (!bad.length) return { reply: 'Отклонённых публикаций нет — все прошли гейт соответствия.', engine: 'rules' };
    const lines = bad.slice(0, 6).map((r) => `• ${r.id}@${r.version}: ${r.reason === 'manifest' ? 'манифест (' + (r.errors || []).join('; ') + ')' : 'не соответствует контракту (' + r.checks.filter((c) => !c.ok).map((c) => c.name).join(', ') + ')'}`);
    return { reply: `Отклонено ${bad.length}:\n` + lines.join('\n'), engine: 'rules' };
  }
  if (/каталог|catalog|роутер|активн|доступн/.test(low)) {
    const cat = registry.catalog();
    if (!cat.length) return { reply: 'В каталоге нет сертифицированных бэкендов.', engine: 'rules' };
    return { reply: `Каталог для роутера (${cat.length}): ` + cat.map((c) => `${c.id}@${c.version} (${c.stack})`).join(', '), engine: 'rules' };
  }
  return { reply: `Плагинов: ${st.plugins}, версий: ${st.versions}. Сертифицировано ${st.certified}, отклонено ${st.rejected}, отозвано ${st.yanked}. В каталоге для роутера: ${st.catalogSize}.`, engine: 'rules' };
}
module.exports = { ask };
