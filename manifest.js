// manifest.js — валидация манифеста плагина-бэкенда (форма до живой проверки).
const semver = require('./semver');

const SLUG = /^[a-z0-9][a-z0-9-]{1,40}$/;

function validate(m) {
  const errors = [];
  m = m || {};
  if (!SLUG.test(String(m.id || ''))) errors.push('id: нужен slug [a-z0-9-]');
  if (!m.name || String(m.name).length < 2) errors.push('name: обязателен');
  if (!semver.valid(m.version)) errors.push('version: нужен semver x.y.z');
  if (!/^https?:\/\/.+/.test(String(m.url || ''))) errors.push('url: нужен http(s)-адрес');
  if (!m.stack || String(m.stack).length < 2) errors.push('stack: обязателен (напр. "PHP", "Flask")');
  if (m.capabilities && !Array.isArray(m.capabilities)) errors.push('capabilities: массив строк');
  if (m.regions && !Array.isArray(m.regions)) errors.push('regions: массив строк');
  if (m.cost != null && (typeof m.cost !== 'number' || m.cost < 0)) errors.push('cost: неотрицательное число');
  return { ok: errors.length === 0, errors };
}

// нормализованная запись манифеста
function normalize(m) {
  return {
    id: m.id, name: m.name, version: m.version, url: String(m.url).replace(/\/$/, ''), stack: m.stack,
    capabilities: m.capabilities || [], regions: m.regions || [], cost: m.cost == null ? null : m.cost,
    description: m.description || '',
  };
}
module.exports = { validate, normalize };
