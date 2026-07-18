// model.js — крошечная softmax-модель-ученик (линейная логистическая регрессия
// над хэш-мешком токенов). Детерминированное обучение (init нулями, порядок
// фиксирован) → воспроизводимый артефакт. serialize/deserialize дают версионируемый
// объект весов, который выкатывается как продакшн-инференс.
const teacher = require('./teacher');
const DIM = 192;

function hash(tok) { let h = 2166136261; for (let i = 0; i < tok.length; i++) { h ^= tok.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0); }
function featurize(text, D) {
  const x = new Float64Array(D);
  for (const t of String(text).toLowerCase().split(/[^a-zа-яё0-9]+/).filter(Boolean)) x[hash(t) % D] += 1;
  return x;
}
function softmax(z) { const m = Math.max(...z); const e = z.map((v) => Math.exp(v - m)); const s = e.reduce((a, b) => a + b, 0); return e.map((v) => v / s); }

function train(samples, { epochs = 200, lr = 0.5, classes = teacher.CLASSES, D = DIM } = {}) {
  const C = classes.length;
  const W = Array.from({ length: C }, () => new Float64Array(D));
  const b = new Float64Array(C);
  const idx = Object.fromEntries(classes.map((c, i) => [c, i]));
  const feats = samples.map((s) => ({ x: featurize(s.text, D), y: idx[s.label] }));
  for (let e = 0; e < epochs; e++) {
    for (const { x, y } of feats) {
      if (y == null) continue;
      const z = W.map((w, c) => { let s = b[c]; for (let j = 0; j < D; j++) s += w[j] * x[j]; return s; });
      const p = softmax(z);
      for (let c = 0; c < C; c++) {
        const g = p[c] - (c === y ? 1 : 0);
        b[c] -= lr * g;
        if (g !== 0) for (let j = 0; j < D; j++) if (x[j] !== 0) W[c][j] -= lr * g * x[j];
      }
    }
  }
  return serialize({ classes, D, W, b });
}

function serialize({ classes, D, W, b }) {
  return { classes, D, W: W.map((w) => Array.from(w)), b: Array.from(b) };
}
function predictor(artifact) {
  const { classes, D, W, b } = artifact;
  return (text) => {
    const x = featurize(text, D);
    const z = W.map((w, c) => { let s = b[c]; for (let j = 0; j < D; j++) s += w[j] * x[j]; return s; });
    const p = softmax(z);
    let arg = 0; for (let c = 1; c < classes.length; c++) if (p[c] > p[arg]) arg = c;
    return { label: classes[arg], prob: Math.round(p[arg] * 1000) / 1000 };
  };
}

// согласие модели с учителем на выборке
function agreement(artifact, samples) {
  const predict = predictor(artifact);
  if (!samples.length) return 0;
  const hit = samples.filter((s) => predict(s.text).label === teacher.label(s.text)).length;
  return Math.round((hit / samples.length) * 1000) / 1000;
}

module.exports = { train, predictor, agreement, featurize, DIM };
