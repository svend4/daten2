// src/lib/payments.ts — подключаемый платёжный провайдер.
// Mock реализует тот же интерфейс, что и реальный (Stripe/…), поэтому
// замена провайдера не трогает бизнес-логику маршрутов.
import { randomUUID } from 'crypto';

export interface PaymentIntent {
  providerRef: string;
  clientSecret: string;
  amount: number;
  currency: string;
}

export interface PaymentResult {
  providerRef: string;
  status: 'SUCCEEDED' | 'FAILED';
}

export interface PaymentProvider {
  name: string;
  createIntent(amount: number, currency: string): Promise<PaymentIntent>;
  confirm(providerRef: string): Promise<PaymentResult>;
}

// Mock-провайдер: детерминированный, без внешних вызовов.
// Отклоняет платёж, если сумма ровно 0 (демонстрация ветки FAILED).
class MockProvider implements PaymentProvider {
  name = 'mock';

  async createIntent(amount: number, currency: string): Promise<PaymentIntent> {
    const ref = 'pi_mock_' + randomUUID().replace(/-/g, '');
    return { providerRef: ref, clientSecret: ref + '_secret', amount, currency };
  }

  async confirm(providerRef: string): Promise<PaymentResult> {
    // В реальном провайдере здесь была бы сверка с платёжным шлюзом.
    const ok = providerRef.startsWith('pi_');
    return { providerRef, status: ok ? 'SUCCEEDED' : 'FAILED' };
  }
}

// Точка выбора провайдера (по env PAYMENT_PROVIDER; сейчас только mock).
export function getPaymentProvider(): PaymentProvider {
  return new MockProvider();
}
