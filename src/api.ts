// src/api.ts — клиент единого контракта магазина.
// Один и тот же код работает с любым из 7 уровней ИЛИ с капабилити-роутером,
// т.к. все они реализуют один контракт (openapi.yaml).

const BACKEND_URL = (process.env.BACKEND_URL || 'http://localhost:8080').replace(/\/$/, '');

export interface Product {
  id: number;
  name: string;
  slug?: string;
  description?: string | null;
  price: number;
  currency?: string;
  image?: string | null;
  sku?: string | null;
  stock: number;
  is_featured?: boolean;
  category_name?: string | null;
}

export interface OrderItemInput {
  product_id: number;
  quantity: number;
}

export type OrderDetail = {
  order: {
    order_number: string;
    status: string;
    payment_status: string;
    total_amount: number;
    customer_name: string;
    phone: string;
  };
  items: Array<{
    product_name: string;
    quantity: number;
    unit_price: number;
    line_total: number;
  }>;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BACKEND_URL + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  const text = await res.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const msg = body && typeof body === 'object' && 'error' in body
      ? String((body as Record<string, unknown>).error)
      : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body as T;
}

export function health(): Promise<{ ok: boolean; level?: number; stack?: string }> {
  return request('/api/health');
}

export function listProducts(): Promise<Product[]> {
  return request('/api/products');
}

export function createOrder(payload: {
  name: string;
  phone?: string;
  email?: string;
  address?: string;
  items: OrderItemInput[];
}): Promise<{ order_number: string; total: number }> {
  return request('/api/orders', { method: 'POST', body: JSON.stringify(payload) });
}

export function getOrder(orderNumber: string): Promise<OrderDetail> {
  return request('/api/orders/' + encodeURIComponent(orderNumber));
}

export { BACKEND_URL };
