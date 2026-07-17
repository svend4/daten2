// src/app/api/orders/[id]/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';

interface RouteParams {
  params: {
    id: string;
  };
}

export async function GET(
  request: NextRequest,
  { params }: RouteParams
) {
  try {
    // Поиск по непубличному токену, а не по последовательному ID —
    // исключает перебор чужих заказов (IDOR).
    const token = params.id;

    if (!token || token.length < 8) {
      return NextResponse.json(
        {
          success: false,
          error: 'Неверный идентификатор заказа',
        },
        { status: 400 }
      );
    }

    const order = await prisma.order.findUnique({
      where: { token },
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

    if (!order) {
      return NextResponse.json(
        {
          success: false,
          error: 'Заказ не найден',
        },
        { status: 404 }
      );
    }

    return NextResponse.json({
      success: true,
      data: order,
    });
  } catch (error) {
    console.error('Order API Error:', error);
    return NextResponse.json(
      {
        success: false,
        error: 'Ошибка при получении заказа',
      },
      { status: 500 }
    );
  }
}
