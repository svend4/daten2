// encoder.js — детерминированный семантический энкодер.
// Отображает произвольный текст (запрос или описание товара) в вектор по фиксированным
// смысловым осям. Плюс база знаний о цветах, чтобы даже товар «только с названием»
// получал осмысленный вектор. Косинусная близость по этим осям = семантический поиск.

// Смысловые оси пространства. kw — корни ключевых слов (RU), substring-совпадение.
const AXES = [
  { key: 'fragrance',     label: 'аромат',    kw: ['запах', 'аромат', 'пахн', 'благоух', 'душист', 'фрагран', 'парфюм', 'нюх'] },
  { key: 'longevity',     label: 'стойкость', kw: ['долго стоя', 'долго сто', 'стойк', 'не вян', 'дольше', 'долговеч', 'простоя', 'неделю', 'долго'] },
  { key: 'romance',       label: 'романтика', kw: ['романт', 'любов', 'свидан', 'страст', 'сердц', 'возлюбл', 'девушк', 'жене'] },
  { key: 'brightness',    label: 'яркость',   kw: ['ярк', 'сочн', 'красочн', 'насыщен', 'пёстр', 'пестр', 'контраст'] },
  { key: 'lushness',      label: 'пышность',  kw: ['пышн', 'объём', 'объем', 'крупн', 'махров', 'густ', 'роскош', 'богат'] },
  { key: 'affordability', label: 'бюджет',    kw: ['недорог', 'дешёв', 'дешев', 'бюджет', 'экономн', 'доступн', 'подешевл'] },
  { key: 'festivity',     label: 'торжество', kw: ['праздник', 'торжеств', 'юбилей', 'свадьб', 'поздрав', 'день рожд', 'днём рожд'] },
  { key: 'tenderness',    label: 'нежность',  kw: ['нежн', 'пастель', 'пастел', 'деликат', 'мягк', 'воздушн', 'маме', 'маму'] },
];
const KEYS = AXES.map((a) => a.key);

// База знаний: корень названия → базовый вектор (реальные свойства цветов).
const KB = {
  'роз':        { fragrance: 0.7,  longevity: 0.7,  romance: 0.95, brightness: 0.7,  lushness: 0.6,  festivity: 0.7,  tenderness: 0.4 },
  'тюльпан':    { fragrance: 0.2,  longevity: 0.5,  romance: 0.5,  brightness: 0.85, lushness: 0.3,  festivity: 0.6,  tenderness: 0.7 },
  'пион':       { fragrance: 0.9,  longevity: 0.45, romance: 0.8,  brightness: 0.6,  lushness: 0.95, festivity: 0.7,  tenderness: 0.8 },
  'гвоздик':    { fragrance: 0.45, longevity: 0.95, romance: 0.4,  brightness: 0.7,  lushness: 0.4,  festivity: 0.6,  tenderness: 0.5 },
  'хризантем':  { fragrance: 0.35, longevity: 0.9,  romance: 0.35, brightness: 0.75, lushness: 0.6,  festivity: 0.6,  tenderness: 0.5 },
  'лили':       { fragrance: 0.95, longevity: 0.75, romance: 0.7,  brightness: 0.7,  lushness: 0.7,  festivity: 0.75, tenderness: 0.6 },
  'альстромер': { fragrance: 0.1,  longevity: 0.95, romance: 0.4,  brightness: 0.7,  lushness: 0.4,  festivity: 0.5,  tenderness: 0.6 },
  'ромашк':     { fragrance: 0.3,  longevity: 0.6,  romance: 0.3,  brightness: 0.6,  lushness: 0.2,  festivity: 0.3,  tenderness: 0.85 },
};

const clamp01 = (n) => Math.max(0, Math.min(1, n));
const zero = () => Object.fromEntries(KEYS.map((k) => [k, 0]));

// Текст → вектор по ключевым словам. 1 совпадение ≈ 0.6, 2+ → насыщение к 1.
function encodeText(text) {
  const t = ' ' + String(text || '').toLowerCase() + ' ';
  const v = zero();
  for (const axis of AXES) {
    let hits = 0;
    for (const kw of axis.kw) if (t.includes(kw)) hits++;
    v[axis.key] = clamp01(hits * 0.6);
  }
  return v;
}

// Корень названия из базы знаний.
function kbRoot(name) {
  const n = String(name || '').toLowerCase();
  for (const root of Object.keys(KB)) if (n.includes(root)) return root;
  return null;
}

// Товар → вектор: база знаний по названию + описание; affordability — из цены.
function encodeProduct(product, priceAffordability) {
  const base = KB[kbRoot(product.name)] || zero();
  const desc = encodeText(`${product.name} ${product.description || ''}`);
  const v = zero();
  for (const k of KEYS) v[k] = clamp01(base[k] * 0.75 + desc[k] * 0.6);
  if (typeof priceAffordability === 'number') v.affordability = clamp01(priceAffordability);
  return v;
}

function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (const k of KEYS) { dot += a[k] * b[k]; na += a[k] * a[k]; nb += b[k] * b[k]; }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

const norm = (v) => Math.sqrt(KEYS.reduce((s, k) => s + v[k] * v[k], 0));

// Оси, по которым запрос и товар совпали (для объяснения «почему»).
function matchedAxes(query, prod) {
  return AXES
    .filter((a) => query[a.key] > 0.05 && prod[a.key] >= 0.5)
    .sort((x, y) => prod[y.key] - prod[x.key])
    .map((a) => a.label);
}

module.exports = { AXES, KEYS, KB, kbRoot, encodeText, encodeProduct, cosine, norm, matchedAxes };
