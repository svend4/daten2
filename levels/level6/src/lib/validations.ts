// src/lib/validations.ts
import { z } from 'zod';

/**
 * Схема валидации для создания заказа
 */
export const createOrderSchema = z.object({
  customer: z.object({
    name: z
      .string()
      .min(2, 'Имя должно содержать минимум 2 символа')
      .max(100, 'Имя слишком длинное'),
    
    phone: z
      .string()
      .regex(/^[+]?[0-9\s\-\(\)]{10,}$/, 'Неверный формат телефона'),
    
    email: z
      .string()
      .email('Неверный формат email')
      .optional()
      .or(z.literal('')),
    
    address: z
      .string()
      .min(10, 'Адрес должен содержать минимум 10 символов')
      .max(500, 'Адрес слишком длинный'),
  }),
  
  items: z
    .array(
      z.object({
        productId: z.number().positive('ID товара должен быть положительным'),
        quantity: z.number().int().positive('Количество должно быть больше 0'),
      })
    )
    .min(1, 'Заказ должен содержать хотя бы один товар'),
  
  notes: z
    .string()
    .max(1000, 'Комментарий слишком длинный')
    .optional()
    .or(z.literal('')),
});

export type CreateOrderInput = z.infer<typeof createOrderSchema>;

/**
 * Валидация email
 */
export function isValidEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

/**
 * Валидация телефона
 */
export function isValidPhone(phone: string): boolean {
  const phoneRegex = /^[+]?[0-9\s\-\(\)]{10,}$/;
  return phoneRegex.test(phone);
}
