// registry.js — реестр плагинов-бэкендов. publish = валидация манифеста → ЖИВАЯ
// проверка соответствия контракту → сертификация. Каталог для роутера отдаёт
// только сертифицированные, не отозванные версии (наивысший semver на плагин).
const manifest = require('./manifest');
const contract = require('./contract');
const semver = require('./semver');

function createRegistry() {
  const versions = new Map(); // `${id}@${version}` → record
  let seq = 0;

  async function publish(m) {
    const v = manifest.validate(m);
    const norm = v.ok ? manifest.normalize(m) : null;
    const key = norm ? `${norm.id}@${norm.version}` : null;
    if (!v.ok) return { state: 'rejected', reason: 'manifest', errors: v.errors };

    const rec = { seq: ++seq, id: norm.id, version: norm.version, manifest: norm, yanked: false };
    const conf = await contract.probe(norm.url);
    rec.checks = conf.checks; rec.score = conf.score;
    rec.state = conf.certified ? 'certified' : 'rejected';
    if (!conf.certified) rec.reason = 'conformance';
    versions.set(key, rec);
    return rec;
  }

  const all = () => [...versions.values()].sort((a, b) => b.seq - a.seq);
  const forId = (id) => all().filter((r) => r.id === id).sort((a, b) => semver.compare(b.version, a.version));
  const ids = () => [...new Set(all().map((r) => r.id))];

  function yank(id, version) {
    const r = versions.get(`${id}@${version}`);
    if (!r) return { error: 'нет такой версии' };
    r.yanked = true; return { ok: true, id, version };
  }

  // активная версия плагина = наивысший сертифицированный не-отозванный semver
  function active(id) { return forId(id).find((r) => r.state === 'certified' && !r.yanked) || null; }

  // каталог в форме, готовой к авто-регистрации в роутере
  function catalog() {
    return ids().map((id) => active(id)).filter(Boolean).map((r) => ({
      id: r.id, name: r.manifest.name, url: r.manifest.url, stack: r.manifest.stack,
      version: r.version, cost: r.manifest.cost, regions: r.manifest.regions, capabilities: r.manifest.capabilities,
    }));
  }

  function stats() {
    const a = all();
    return { plugins: ids().length, versions: a.length, certified: a.filter((r) => r.state === 'certified' && !r.yanked).length, rejected: a.filter((r) => r.state === 'rejected').length, yanked: a.filter((r) => r.yanked).length, catalogSize: catalog().length };
  }

  return { publish, all, forId, ids, yank, active, catalog, stats };
}
module.exports = { createRegistry };
