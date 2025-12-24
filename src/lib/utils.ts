// src/lib/utils.ts
import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Объединение Tailwind классов
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Форматирование цены
 */
export function formatPrice(price: number | string): string {
  const numPrice = typeof price === 'string' ? parseFloat(price) : price;
  
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    minimumFractionDigits: 2,
  }).format(numPrice);
}

/**
 * Форматирование даты
 */
export function formatDate(date: Date | string): string {
  const dateObj = typeof date === 'string' ? new Date(date) : date;
  
  return new Intl.DateTimeFormat('ru-RU', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(dateObj);
}

/**
 * Обрезка текста
 */
export function truncate(text: string, length: number = 100): string {
  if (!text || text.length <= length) return text;
  return text.substring(0, length) + '...';
}

/**
 * Получить статус наличия
 */
export function getStockStatus(stock: number): {
  text: string;
  className: string;
} {
  if (stock > 10) {
    return { text: 'В наличии', className: 'text-green-600' };
  } else if (stock > 0) {
    return { text: `Осталось ${stock} шт.`, className: 'text-yellow-600' };
  } else {
    return { text: 'Нет в наличии', className: 'text-red-600' };
  }
}

/**
 * Генерация slug из строки
 */
export function generateSlug(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * Задержка (для демонстрации loading states)
 */
export function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
