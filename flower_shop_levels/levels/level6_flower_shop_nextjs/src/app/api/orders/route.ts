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

    // Рассчитать общую сумму
    let totalAmount = new Decimal(0);
    const orderItems = items.map((item, index) => {
      const product = productsData[index]!;
      const price = new Decimal(product.price.toString());
      const subtotal = price.mul(item.quantity);
      totalAmount = totalAmount.add(subtotal);

      return {
        productId: item.productId,
        quantity: item.quantity,
        price: product.price,
      };
    });

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
          totalAmount,
          deliveryAddress: customer.address,
          notes: notes || null,
          status: 'NEW',
          items: {
            create: orderItems,
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
