// src/lib/prisma.ts
import { PrismaClient } from '@prisma/client';

// Singleton паттерн для Prisma Client
const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined;
};

export const prisma =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === 'development' ? ['query', 'error', 'warn'] : ['error'],
  });

if (process.env.NODE_ENV !== 'production') {
  globalForPrisma.prisma = prisma;
}

// Типы Prisma для удобства
export type { 
  Product, 
  Category, 
  Order, 
  OrderItem, 
  Customer,
  OrderStatus 
} from '@prisma/client';
