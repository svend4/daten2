#!/usr/bin/env node
// src/index.ts — MCP-сервер магазина цветов.
// Даёт ИИ инструменты для управления любым из 7 уровней через единый контракт.
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { health, listProducts, createOrder, getOrder, BACKEND_URL, type Product } from './api.js';

const server = new McpServer({ name: 'flower-shop-mcp-server', version: '1.0.0' });

const errText = (e: unknown) => `Ошибка: ${e instanceof Error ? e.message : String(e)}`;

// --- health: какой уровень отвечает ---
server.registerTool(
  'flowershop_health',
  {
    title: 'Проверка магазина',
    description: `Проверяет доступность бэкенда магазина и сообщает, какой из 7 уровней отвечает.

Returns JSON: { "ok": boolean, "level": number, "stack": string }
Use when: нужно понять, работает ли магазин и какая реализация (PHP/Flask/Django/…) обслуживает запросы.`,
    inputSchema: {},
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  },
  async () => {
    try {
      const h = await health();
      return { content: [{ type: 'text', text: JSON.stringify(h) }], structuredContent: h };
    } catch (e) {
      return { content: [{ type: 'text', text: errText(e) }], isError: true };
    }
  }
);

// --- каталог с клиентскими фильтрами (контракт без query-параметров) ---
const ListSchema = {
  search: z.string().optional().describe('Подстрока в названии товара (регистронезависимо)'),
  featured_only: z.boolean().default(false).describe('Только рекомендуемые товары'),
  max_price: z.number().positive().optional().describe('Максимальная цена'),
  in_stock: z.boolean().default(false).describe('Только товары в наличии (stock > 0)'),
};

server.registerTool(
  'flowershop_list_products',
  {
    title: 'Каталог товаров',
    description: `Возвращает каталог активных товаров магазина, с необязательными фильтрами.

Args:
  - search (string): подстрока в названии
  - featured_only (boolean): только рекомендуемые (default false)
  - max_price (number): максимальная цена
  - in_stock (boolean): только в наличии (default false)

Returns JSON: { "count": number, "products": [ { id, name, price, currency, stock, is_featured, category_name } ] }
Use when: нужно показать ассортимент, найти товар, узнать цену/остаток перед оформлением заказа.`,
    inputSchema: ListSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  },
  async ({ search, featured_only, max_price, in_stock }) => {
    try {
      let products = await listProducts();
      if (search) {
        const q = search.toLowerCase();
        products = products.filter((p: Product) => p.name.toLowerCase().includes(q));
      }
      if (featured_only) products = products.filter((p: Product) => p.is_featured);
      if (typeof max_price === 'number') products = products.filter((p: Product) => Number(p.price) <= max_price);
      if (in_stock) products = products.filter((p: Product) => p.stock > 0);

      const output = {
        count: products.length,
        products: products.map((p: Product) => ({
          id: p.id, name: p.name, price: Number(p.price), currency: p.currency || 'EUR',
          stock: p.stock, is_featured: !!p.is_featured, category_name: p.category_name ?? null,
        })),
      };
      return { content: [{ type: 'text', text: JSON.stringify(output, null, 2) }], structuredContent: output };
    } catch (e) {
      return { content: [{ type: 'text', text: errText(e) }], isError: true };
    }
  }
);

// --- оформление заказа ---
const CreateOrderSchema = {
  name: z.string().min(1).describe('Имя покупателя'),
  phone: z.string().optional().describe('Телефон'),
  email: z.string().email().optional().describe('Email'),
  address: z.string().optional().describe('Адрес доставки'),
  items: z.array(z.object({
    product_id: z.number().int().positive().describe('ID товара из каталога'),
    quantity: z.number().int().positive().describe('Количество'),
  })).min(1).describe('Позиции заказа'),
};

server.registerTool(
  'flowershop_create_order',
  {
    title: 'Оформить заказ',
    description: `Создаёт заказ в магазине. Цены берутся с сервера, возвращается непубличный номер (токен) заказа.

Args:
  - name (string, обязательно): имя покупателя
  - phone, email, address (string): контакты и доставка
  - items (array, обязательно): [{ product_id, quantity }] — ID берите из flowershop_list_products

Returns JSON: { "order_number": string, "total": number }
Use when: покупатель подтвердил покупку. Это ЗАПИСЬ данных — не вызывайте без явного намерения оформить заказ.`,
    inputSchema: CreateOrderSchema,
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  },
  async (params) => {
    try {
      const r = await createOrder(params);
      return { content: [{ type: 'text', text: JSON.stringify(r) }], structuredContent: r };
    } catch (e) {
      return { content: [{ type: 'text', text: errText(e) }], isError: true };
    }
  }
);

// --- заказ по номеру ---
server.registerTool(
  'flowershop_get_order',
  {
    title: 'Заказ по номеру',
    description: `Возвращает детали заказа по непубличному номеру (токену), полученному при оформлении.

Args:
  - order_number (string, обязательно): токен заказа

Returns JSON: { "order": { order_number, status, payment_status, total_amount, customer_name, phone }, "items": [...] }
Use when: нужно проверить статус/состав заказа.`,
    inputSchema: { order_number: z.string().min(8).describe('Непубличный номер заказа (токен)') },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  },
  async ({ order_number }) => {
    try {
      const r = await getOrder(order_number);
      return { content: [{ type: 'text', text: JSON.stringify(r, null, 2) }], structuredContent: r };
    } catch (e) {
      return { content: [{ type: 'text', text: errText(e) }], isError: true };
    }
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`flower-shop-mcp-server запущен (backend: ${BACKEND_URL})`);
}

main().catch((e) => {
  console.error('Фатальная ошибка:', e);
  process.exit(1);
});
