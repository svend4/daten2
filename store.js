// store.js — временной ряд снимков каталога (для вывода спроса и аномалий).
// Хранение в памяти + необязательная персистентность в data/snapshots.json,
// чтобы ряд переживал перезапуск. Один снимок = { t, products:[{id,name,price,stock,is_featured}] }.
const fs = require('node:fs');
const path = require('node:path');

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const FILE = path.join(DATA_DIR, 'snapshots.json');
const MAX = Number(process.env.MAX_SNAPSHOTS || 500);

let snapshots = [];

function load() {
  try {
    snapshots = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    if (!Array.isArray(snapshots)) snapshots = [];
  } catch { snapshots = []; }
}

function persist() {
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify(snapshots));
  } catch { /* персистентность необязательна */ }
}

// t передаётся снаружи (в тестах — детерминированно; Date.now недоступен в некоторых средах)
function record(products, t) {
  const snap = {
    t,
    products: products.map((p) => ({
      id: p.id, name: p.name, price: Number(p.price),
      stock: Number(p.stock), is_featured: !!p.is_featured,
    })),
  };
  snapshots.push(snap);
  if (snapshots.length > MAX) snapshots = snapshots.slice(-MAX);
  persist();
  return snap;
}

const all = () => snapshots;
const latest = () => snapshots[snapshots.length - 1] || null;
function reset() { snapshots = []; persist(); }

module.exports = { load, record, all, latest, reset };
