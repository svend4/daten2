// vision.js — детерминированное «зрение»: анализ доминирующего цвета изображения
// и отображение в тип цветка, смысловые оси и теги. Работает на пикселях (PNG),
// без внешних моделей. С LLM-ключом дополняется Claude-vision.
const png = require('./png');

// Цвет → цветок/оси/теги (доменные знания о цветах магазина).
const COLOR_MAP = [
  { name: 'красный',   test: (r, g, b) => r > 130 && r - g > 50 && r - b > 50,            flower: 'роз',     root: 'роз',     tags: ['романтика', 'страсть', 'розы'],       axes: { romance: 0.9, brightness: 0.7 } },
  { name: 'жёлтый',    test: (r, g, b) => r > 160 && g > 140 && b < 120 && Math.abs(r - g) < 60, flower: 'тюльпан', root: 'тюльпан', tags: ['яркость', 'весна', 'тюльпаны'], axes: { brightness: 0.9, tenderness: 0.5 } },
  { name: 'розовый',   test: (r, g, b) => r > 180 && b > 130 && r - g > 30 && b - g > 10, flower: 'пион',    root: 'пион',    tags: ['нежность', 'пастель', 'пионы'],        axes: { tenderness: 0.9, lushness: 0.7 } },
  { name: 'белый',     test: (r, g, b) => r > 200 && g > 200 && b > 200,                  flower: 'пион',    root: 'пион',    tags: ['нежность', 'чистота'],                 axes: { tenderness: 0.85 } },
  { name: 'зелёный',   test: (r, g, b) => g > r && g > b && g > 100,                       flower: null,      root: null,      tags: ['зелень', 'листва'],                    axes: {} },
];

function analyzeBuffer(buffer) {
  const img = png.decode(buffer); // бросит, если не PNG/неподдерживаемый
  let R = 0, G = 0, B = 0, n = 0;
  const step = Math.max(1, Math.floor((img.width * img.height) / 4000)); // сэмплируем
  for (let i = 0; i < img.width * img.height; i += step) {
    const p = i * 4;
    if (img.pixels[p + 3] < 16) continue; // прозрачные пропускаем
    R += img.pixels[p]; G += img.pixels[p + 1]; B += img.pixels[p + 2]; n++;
  }
  n = n || 1;
  const avg = { r: Math.round(R / n), g: Math.round(G / n), b: Math.round(B / n) };
  const match = COLOR_MAP.find((c) => c.test(avg.r, avg.g, avg.b));
  return {
    width: img.width, height: img.height,
    dominant: avg,
    colorName: match ? match.name : 'смешанный',
    flowerRoot: match ? match.root : null,
    tags: match ? match.tags : ['букет'],
    axes: match ? match.axes : {},
  };
}

// Подбор товаров по анализу фото (поиск по фото).
function matchProducts(analysis, catalog) {
  const root = analysis.flowerRoot;
  const scored = catalog.map((p) => {
    const n = String(p.name).toLowerCase();
    let score = p.is_featured ? 0.3 : 0.1;
    const reasons = [];
    if (root && n.includes(root)) { score += 1.0; reasons.push(`цвет → ${analysis.colorName}`); }
    return { id: p.id, name: p.name, price: Number(p.price), score: Math.round(score * 100) / 100, reasons };
  });
  return scored.sort((a, b) => b.score - a.score);
}

function describe(analysis) {
  const c = analysis.dominant;
  const base = `На фото преобладает ${analysis.colorName} цвет (RGB ${c.r},${c.g},${c.b}).`;
  const flower = analysis.flowerRoot ? ` Похоже на ${analysis.tags.slice(-1)[0]}.` : '';
  const tags = analysis.tags.length ? ` Теги: ${analysis.tags.join(', ')}.` : '';
  return base + flower + tags;
}

module.exports = { analyzeBuffer, matchProducts, describe, COLOR_MAP };
