// src/app/api/orders/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { createOrderSchema } from '@/lib/validations';
import { Decimal } from '@prisma/client/runtime/library';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Валидация
    const validationResult = createOrderSchema.safeParse(body);
    
    if (!validationResult.success) {
      return NextResponse.json(
        {
          success: false,
          errors: validationResult.error.errors.map(err => err.message),
        },
        { status: 400 }
      );
    }

    const { customer, items, notes } = validationResult.data;

    // Проверить товары и рассчитать сумму
    const productsData = await Promise.all(
      items.map(item =>
        prisma.product.findUnique({
          where: { id: item.productId },
        })
      )
    );

    // Проверить наличие товаров
    for (let i = 0; i < productsData.length; i++) {
      const product = productsData[i];
      const item = items[i];

      if (!product || !product.isActive) {
        return NextResponse.json(
          {
            success: false,
            error: `Товар с ID ${item.productId} не найден`,
          },
          { status: 404 }
        );
      }

      if (product.stock < item.quantity) {
        return NextResponse.json(
          {
            success: false,
            error: `Недостаточно товара "${product.name}" на складе`,
          },
          { status: 400 }
        );
      }
    }

    // Рассчитать суммы и собрать позиции со снимком названия/цены
    let subtotal = new Decimal(0);
    const orderItems = items.map((item, index) => {
      const product = productsData[index]!;
      const unitPrice = new Decimal(product.price.toString());
      const lineTotal = unitPrice.mul(item.quantity);
      subtotal = subtotal.add(lineTotal);

      return {
        productId: item.productId,
        productName: product.name,
        quantity: item.quantity,
        unitPrice: product.price,
        lineTotal,
      };
    });
    const totalAmount = subtotal; // discount/deliveryFee = 0 для демо

    // Создать заказ в транзакции
    const order = await prisma.$transaction(async (tx) => {
      // Создать клиента
      const newCustomer = await tx.customer.create({
        data: {
          name: customer.name,
          phone: customer.phone,
          email: customer.email || null,
          address: customer.address,
        },
      });

      // Создать заказ
      const newOrder = await tx.order.create({
        data: {
          customerId: newCustomer.id,
          subtotal,
          totalAmount,
          deliveryAddress: customer.address,
          notes: notes || null,
          status: 'NEW',
          paymentStatus: 'PENDING',
          items: {
            create: orderItems,
          },
          statusHistory: {
            create: { status: 'NEW', note: 'Заказ создан' },
          },
        },
        include: {
          customer: true,
          items: {
            include: {
              product: {
                select: {
                  name: true,
                  image: true,
                },
              },
            },
          },
        },
      });

      // Уменьшить остатки
      await Promise.all(
        items.map(item =>
          tx.product.update({
            where: { id: item.productId },
            data: {
              stock: {
                decrement: item.quantity,
              },
            },
          })
        )
      );

      return newOrder;
    });

    return NextResponse.json(
      {
        success: true,
        message: `Заказ #${order.id} успешно создан`,
        data: order,
      },
      { status: 201 }
    );
  } catch (error) {
    console.error('Create Order Error:', error);
    return NextResponse.json(
      {
        success: false,
        error: 'Ошибка при создании заказа',
      },
      { status: 500 }
    );
  }
}
