// memory.js — пер-клиентская память для персонализации.
// preferences: любимые товары/поводы/бюджет; history: последние вопросы/действия.
// Хранится в памяти (+ опц. персист в data/memory.json).
const fs = require('node:fs');
const path = require('node:path');

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const FILE = path.join(DATA_DIR, 'memory.json');
let mem = {};

function load() { try { mem = JSON.parse(fs.readFileSync(FILE, 'utf8')) || {}; } catch { mem = {}; } }
function persist() { try { fs.mkdirSync(DATA_DIR, { recursive: true }); fs.writeFileSync(FILE, JSON.stringify(mem)); } catch { /* опц. */ } }

function recall(customerId) {
  return mem[customerId] || { preferences: { favorites: [], occasions: [], budget: null }, history: [], notes: '' };
}

function remember(customerId, patch = {}) {
  const cur = recall(customerId);
  const pref = cur.preferences;
  const p = patch.preferences || {};
  if (Array.isArray(p.favorites)) for (const f of p.favorites) if (!pref.favorites.includes(f)) pref.favorites.push(f);
  if (Array.isArray(p.occasions)) for (const o of p.occasions) if (!pref.occasions.includes(o)) pref.occasions.push(o);
  if (p.budget != null) pref.budget = Number(p.budget);
  if (patch.note) cur.notes = String(patch.note);
  if (patch.event) { cur.history.push(patch.event); if (cur.history.length > 50) cur.history = cur.history.slice(-50); }
  cur.preferences = pref;
  mem[customerId] = cur;
  persist();
  return cur;
}

function forget(customerId) { delete mem[customerId]; persist(); }

module.exports = { load, recall, remember, forget };
