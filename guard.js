// guard.js — оркестрация файрвола: сводит детекторы в вердикт allow / sanitize /
// block по порогам политики. Опционально усиливается LLM-судьёй (второе мнение).
const detectors = require('./detectors');
const policy = require('./policy');

const decide = (risk) => (risk >= policy.thresholds.block ? 'block' : risk >= policy.thresholds.flag ? 'sanitize' : 'allow');

// judge — необязательная async-функция text → { risk } (LLM-классификатор инъекций)
async function guardInput(text, judge) {
  const scan = detectors.scanInput(text);
  let risk = scan.risk;
  let llm = null;
  if (judge) {
    try { llm = await judge(text); if (llm && typeof llm.risk === 'number') risk = Math.min(100, Math.max(risk, llm.risk)); }
    catch { /* судья необязателен */ }
  }
  const action = decide(risk);
  return {
    surface: 'input', action, risk, categories: scan.categories, matches: scan.matches,
    sanitized: action === 'allow' ? text : detectors.sanitize(text),
    llm: llm || undefined,
  };
}

function guardTool(tool, input) {
  const v = detectors.validateTool(tool, input);
  let action;
  if (v.blocked || v.risk >= policy.thresholds.block) action = 'block';
  else if (v.violations.length) action = 'allow-clamped'; // безопасно урезано
  else action = 'allow';
  return { surface: 'tool', tool, action, risk: v.risk, violations: v.violations, clamped: v.clamped };
}

function guardOutput(text) {
  const scan = detectors.scanOutput(text);
  const action = scan.risk >= policy.thresholds.block ? 'block' : scan.risk >= policy.thresholds.flag ? 'redact' : 'allow';
  return { surface: 'output', action, risk: scan.risk, categories: scan.categories, matches: scan.matches };
}

module.exports = { guardInput, guardTool, guardOutput, decide };
