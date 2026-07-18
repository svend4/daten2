// test/services.mjs — проверяет auth-service и payment-service,
// и что роутер корректно на них проксирует.
import assert from 'assert';

const AUTH_PORT = 8091, PAY_PORT = 8092, GW_PORT = 8090;

async function main() {
  const auth = (await import('../services/auth-service/server.js')).default;
  const pay = (await import('../services/payment-service/server.js')).default;

  const authSrv = auth.listen(AUTH_PORT);
  const paySrv = pay.listen(PAY_PORT);

  process.env.AUTH_URL = `http://localhost:${AUTH_PORT}`;
  process.env.PAYMENT_URL = `http://localhost:${PAY_PORT}`;
  const gw = (await import('../server.js')).default;
  const gwSrv = gw.listen(GW_PORT);
  const G = `http://localhost:${GW_PORT}`;

  await new Promise((r) => setTimeout(r, 200));

  // --- auth через роутер ---
  const reg = await fetch(`${G}/api/auth/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'a@b.c', password: 'secret123', name: 'ИИ' }) });
  assert.strictEqual(reg.status, 201, 'register через роутер');
  const { token } = await reg.json();
  const me = await fetch(`${G}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  assert.strictEqual(me.status, 200, 'me через роутер');
  assert.strictEqual((await me.json()).name, 'ИИ', 'me данные');
  const noauth = await fetch(`${G}/api/auth/me`);
  assert.strictEqual(noauth.status, 401, 'me без токена = 401');
  const badlogin = await fetch(`${G}/api/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'a@b.c', password: 'wrong' }) });
  assert.strictEqual(badlogin.status, 401, 'неверный пароль');
  console.log('✓ auth-service через роутер: register/me/401/login');

  // --- payment через роутер ---
  const intent = await fetch(`${G}/api/payments/intent`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_number: 'ord123', amount: 3.0 }) });
  assert.strictEqual(intent.status, 201, 'intent через роутер');
  const { provider_ref } = await intent.json();
  assert(provider_ref.startsWith('pi_'), 'provider_ref');
  const confirm = await fetch(`${G}/api/payments/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider_ref }) });
  assert.strictEqual(confirm.status, 200, 'confirm через роутер');
  assert.strictEqual((await confirm.json()).status, 'SUCCEEDED', 'оплата успешна');
  const status = await fetch(`${G}/api/payments/ord123`);
  assert.strictEqual((await status.json()).status, 'SUCCEEDED', 'статус оплаты');
  console.log('✓ payment-service через роутер: intent/confirm/status');

  console.log('\nВСЕ ПРОВЕРКИ ПРОЙДЕНЫ ✓');
  authSrv.close(); paySrv.close(); gwSrv.close();
}

main().catch((e) => { console.error('✗', e.message); process.exit(1); });
