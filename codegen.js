// codegen.js — генерация типизированных клиентов из спецификации контракта.
// Один источник (spec.js) → клиенты для JS, Python и типы TypeScript.
const spec = require('./spec');

const snake = (s) => s.replace(/([A-Z])/g, '_$1').toLowerCase();

function pathExprJs(op) {
  if (!op.params || !op.params.length) return `'${op.path}'`;
  let e = '`' + op.path.replace(/\{(\w+)\}/g, (_, p) => '${encodeURIComponent(' + p + ')}') + '`';
  return e;
}
function pathExprPy(op) {
  if (!op.params || !op.params.length) return `'${op.path}'`;
  return 'f' + "'" + op.path.replace(/\{(\w+)\}/g, (_, p) => '{' + snake(p) + '}') + "'";
}

function js() {
  const methods = spec.operations.map((op) => {
    const args = [...(op.params || []), ...(op.body ? ['input'] : [])];
    return `  async ${op.name}(${args.join(', ')}) {\n    return this._req('${op.method}', ${pathExprJs(op)}${op.body ? ', input' : ''});\n  }`;
  }).join('\n');
  return `// Generated from ${spec.title} v${spec.version} — единый контракт. Не редактировать вручную.
class FlowerShopClient {
  constructor(baseUrl) { this.base = String(baseUrl).replace(/\\/$/, ''); }
  async _req(method, path, body) {
    const r = await fetch(this.base + path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }
${methods}
}
module.exports = FlowerShopClient;
`;
}

function python() {
  const methods = spec.operations.map((op) => {
    const args = ['self', ...(op.params || []).map(snake), ...(op.body ? ['order_input'] : [])];
    return `    def ${snake(op.name)}(${args.join(', ')}):\n        return self._req('${op.method}', ${pathExprPy(op)}${op.body ? ', order_input' : ''})`;
  }).join('\n');
  return `# Generated from ${spec.title} v${spec.version} — единый контракт. Не редактировать вручную.
import requests

class FlowerShopClient:
    def __init__(self, base_url):
        self.base = base_url.rstrip('/')

    def _req(self, method, path, body=None):
        r = requests.request(method, self.base + path, json=body)
        r.raise_for_status()
        return r.json()

${methods}
`;
}

function tsTypes() {
  const tsType = (t) => {
    const opt = t.endsWith('?');
    const base = t.replace('?', '');
    const map = { number: 'number', string: 'string', boolean: 'boolean' };
    let ty = map[base] || base.replace('[]', '[]');
    return { ty, opt };
  };
  const ifaces = Object.entries(spec.types).map(([name, fields]) => {
    const body = Object.entries(fields).map(([k, t]) => { const { ty, opt } = tsType(t); return `  ${k}${opt ? '?' : ''}: ${ty};`; }).join('\n');
    return `export interface ${name} {\n${body}\n}`;
  }).join('\n\n');
  return `// Generated from ${spec.title} v${spec.version}\n${ifaces}\n`;
}

function generate(lang) {
  if (lang === 'js' || lang === 'javascript') return { lang: 'js', filename: 'flower-shop-client.js', code: js() };
  if (lang === 'python' || lang === 'py') return { lang: 'python', filename: 'flower_shop_client.py', code: python() };
  if (lang === 'ts' || lang === 'ts-types' || lang === 'typescript') return { lang: 'ts-types', filename: 'contract.d.ts', code: tsTypes() };
  return { error: 'неизвестный язык: ' + lang + ' (js|python|ts-types)' };
}

module.exports = { generate, langs: ['js', 'python', 'ts-types'] };
