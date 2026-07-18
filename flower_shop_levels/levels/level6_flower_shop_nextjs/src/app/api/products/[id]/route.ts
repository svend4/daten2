// src/app/api/products/[id]/route.ts
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
    const id = parseInt(params.id);

    if (isNaN(id)) {
      return NextResponse.json(
        {
          success: false,
          error: 'Неверный ID товара',
        },
        { status: 400 }
      );
    }

    const product = await prisma.product.findUnique({
      where: {
        id,
        isActive: true,
      },
      include: {
        category: true,
      },
    });

    if (!product) {
      return NextResponse.json(
        {
          success: false,
          error: 'Товар не найден',
        },
        { status: 404 }
      );
    }

    return NextResponse.json({
      success: true,
      data: product,
    });
  } catch (error) {
    console.error('Product API Error:', error);
    return NextResponse.json(
      {
        success: false,
        error: 'Ошибка при получении товара',
      },
      { status: 500 }
    );
  }
}
