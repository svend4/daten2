// prisma/seed.ts
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  console.log('🌱 Начало загрузки тестовых данных...');

  // Очистить существующие данные
  await prisma.orderItem.deleteMany();
  await prisma.order.deleteMany();
  await prisma.customer.deleteMany();
  await prisma.product.deleteMany();
  await prisma.category.deleteMany();

  console.log('🗑️  Старые данные удалены');

  // Создать категории
  const categories = await Promise.all([
    prisma.category.create({
      data: {
        name: 'Розы',
        description: 'Классические и экзотические розы',
        slug: 'rozy',
      },
    }),
    prisma.category.create({
      data: {
        name: 'Тюльпаны',
        description: 'Весенние тюльпаны разных сортов',
        slug: 'tyulpany',
      },
    }),
    prisma.category.create({
      data: {
        name: 'Букеты',
        description: 'Готовые букеты на любой случай',
        slug: 'bukety',
      },
    }),
    prisma.category.create({
      data: {
        name: 'Комнатные растения',
        description: 'Цветы в горшках для дома',
        slug: 'komnatnye-rasteniya',
      },
    }),
  ]);

  console.log(`✅ Создано ${categories.length} категорий`);

  // Создать товары
  const products = await Promise.all([
    // Розы
    prisma.product.create({
      data: {
        name: 'Красная роза',
        slug: 'krasnaya-roza',
        description: 'Классическая красная роза премиум класса. Идеальна для романтических подарков.',
        price: 150.00,
        categoryId: categories[0].id,
        image: '/images/products/rose-red.jpg',
        stock: 50,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Белая роза',
        slug: 'belaya-roza',
        description: 'Нежная белая роза, символ чистоты и невинности.',
        price: 140.00,
        categoryId: categories[0].id,
        image: '/images/products/rose-white.jpg',
        stock: 30,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Розовая роза',
        slug: 'rozovaya-roza',
        description: 'Романтичная розовая роза для выражения нежных чувств.',
        price: 145.00,
        categoryId: categories[0].id,
        image: '/images/products/rose-pink.jpg',
        stock: 40,
      },
    }),
    
    // Тюльпаны
    prisma.product.create({
      data: {
        name: 'Желтый тюльпан',
        slug: 'zheltyj-tyulpan',
        description: 'Яркий желтый тюльпан, символ весны и радости.',
        price: 80.00,
        categoryId: categories[1].id,
        image: '/images/products/tulip-yellow.jpg',
        stock: 100,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Розовый тюльпан',
        slug: 'rozovyj-tyulpan',
        description: 'Нежно-розовый тюльпан для особенных моментов.',
        price: 85.00,
        categoryId: categories[1].id,
        image: '/images/products/tulip-pink.jpg',
        stock: 80,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Красный тюльпан',
        slug: 'krasnyj-tyulpan',
        description: 'Классический красный тюльпан, символ страстной любви.',
        price: 90.00,
        categoryId: categories[1].id,
        image: '/images/products/tulip-red.jpg',
        stock: 70,
      },
    }),
    
    // Букеты
    prisma.product.create({
      data: {
        name: 'Букет "Романтика"',
        slug: 'buket-romantika',
        description: 'Роскошный букет из 15 красных роз. Идеальный подарок для любимой.',
        price: 2200.00,
        categoryId: categories[2].id,
        image: '/images/products/bouquet-romance.jpg',
        stock: 10,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Букет "Весна"',
        slug: 'buket-vesna',
        description: 'Яркий микс из тюльпанов и нарциссов. Весеннее настроение гарантировано!',
        price: 1500.00,
        categoryId: categories[2].id,
        image: '/images/products/bouquet-spring.jpg',
        stock: 15,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Букет "Нежность"',
        slug: 'buket-nezhnost',
        description: 'Нежный букет из белых и розовых роз. Для самых дорогих людей.',
        price: 1800.00,
        categoryId: categories[2].id,
        image: '/images/products/bouquet-tender.jpg',
        stock: 12,
      },
    }),
    
    // Комнатные растения
    prisma.product.create({
      data: {
        name: 'Орхидея фаленопсис',
        slug: 'orhideya-falenopsis',
        description: 'Элегантная белая орхидея в горшке. Прекрасное украшение интерьера.',
        price: 1200.00,
        categoryId: categories[3].id,
        image: '/images/products/orchid-white.jpg',
        stock: 8,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Фиалка',
        slug: 'fialka',
        description: 'Очаровательная комнатная фиалка. Доступны разные цвета.',
        price: 350.00,
        categoryId: categories[3].id,
        image: '/images/products/violet.jpg',
        stock: 20,
      },
    }),
    prisma.product.create({
      data: {
        name: 'Кактус',
        slug: 'kaktus',
        description: 'Декоративный кактус в красивом горшке. Неприхотлив в уходе.',
        price: 280.00,
        categoryId: categories[3].id,
        image: '/images/products/cactus.jpg',
        stock: 30,
      },
    }),
  ]);

  console.log(`✅ Создано ${products.length} товаров`);
  console.log('🎉 Загрузка данных завершена!');
}

main()
  .catch((e) => {
    console.error('❌ Ошибка при загрузке данных:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
