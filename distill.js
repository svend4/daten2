// distill.js — оркестрация дистилляции: генерируем размеченные учителем данные,
// делим train/test, обучаем ученика и меряем СОГЛАСИЕ ученика с учителем.
const dataset = require('./dataset');
const teacher = require('./teacher');
const student = require('./student');

function split(rows, ratio = 0.8) {
  // детерминированное разбиение: каждый 5-й — в тест
  const train = [], test = [];
  rows.forEach((r, i) => ((i % 5 === 4) ? test : train).push(r));
  return { train, test };
}

function distill({ n = 500, seed = 42, epochs = 250, lr = 0.5 } = {}) {
  const rows = dataset.generate(n, seed);
  const { train, test } = split(rows);
  const trained = student.train(teacher.LABELS, train, { epochs, lr });
  // согласие с учителем на тесте (ground truth = teacher.label)
  let agree = 0;
  const confusions = [];
  for (const r of test) {
    const pred = student.predict(trained.model, r.text).label;
    const truth = teacher.label(r.text);
    if (pred === truth) agree++;
    else confusions.push({ text: r.text, teacher: truth, student: pred });
  }
  const agreement = test.length ? agree / test.length : 0;
  return {
    model: trained.model,
    metrics: {
      dataset: rows.length, train: train.length, test: test.length,
      agreement: Math.round(agreement * 1000) / 1000,
      loss: trained.loss,
      confusions: confusions.slice(0, 10),
    },
  };
}

module.exports = { distill, split };
