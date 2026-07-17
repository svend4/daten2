// prisma/seed.ts — канонический сид (те же 3 товара, что на L1–L5)
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  console.log('🌱 Начало загрузки данных...');

  // Очистить существующие данные
  await prisma.orderStatusHistory.deleteMany();
  await prisma.orderItem.deleteMany();
  await prisma.order.deleteMany();
  await prisma.customer.deleteMany();
  await prisma.cartItem.deleteMany();
  await prisma.cart.deleteMany();
  await prisma.productViewStats.deleteMany();
  await prisma.product.deleteMany();
  await prisma.category.deleteMany();

  const categories = await Promise.all([
    prisma.category.create({ data: { name: 'Розы', slug: 'roses', description: 'Классические розы' } }),
    prisma.category.create({ data: { name: 'Тюльпаны', slug: 'tulips', description: 'Весенние тюльпаны' } }),
    prisma.category.create({ data: { name: 'Букеты', slug: 'bouquets', description: 'Готовые букеты' } }),
  ]);
  console.log(`✅ Категорий: ${categories.length}`);

  const products = await Promise.all([
    prisma.product.create({
      data: {
        name: 'Красная роза', slug: 'red-rose',
        description: 'Классическая красная роза премиум класса',
        price: 1.50, currency: 'EUR', sku: 'ROSE-RED-01',
        categoryId: categories[0].id, image: 'images/rose.jpg',
        stock: 50, isActive: true, isFeatured: true,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Жёлтый тюльпан', slug: 'yellow-tulip',
        description: 'Яркий жёлтый тюльпан',
        price: 0.80, currency: 'EUR', sku: 'TULIP-YEL-01',
        categoryId: categories[1].id, image: 'images/tulip.jpg',
        stock: 100, isActive: true, isFeatured: false,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Пион', slug: 'peony',
        description: 'Нежный ароматный пион',
        price: 2.20, currency: 'EUR', sku: 'PEONY-01',
        categoryId: categories[2].id, image: 'images/peony.jpg',
        stock: 30, isActive: true, isFeatured: true,
      },
    }),
  ]);
  console.log(`✅ Товаров: ${products.length}`);
  console.log('🎉 Готово!');
}

main()
  .catch((e) => {
    console.error('❌ Ошибка при загрузке данных:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
