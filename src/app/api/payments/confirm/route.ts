// POST /api/payments/confirm — подтвердить платёж (аналог webhook провайдера).
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { getPaymentProvider } from '@/lib/payments';

export async function POST(request: NextRequest) {
  try {
    const { orderNumber, providerRef } = await request.json();
    if (!orderNumber || !providerRef) {
      return NextResponse.json({ success: false, error: 'orderNumber и providerRef обязательны' }, { status: 400 });
    }

    const order = await prisma.order.findUnique({ where: { orderNumber } });
    if (!order) {
      return NextResponse.json({ success: false, error: 'Заказ не найден' }, { status: 404 });
    }

    const payment = await prisma.payment.findUnique({ where: { providerRef } });
    if (!payment || payment.orderId !== order.id) {
      return NextResponse.json({ success: false, error: 'Платёж не найден' }, { status: 404 });
    }

    const provider = getPaymentProvider();
    const result = await provider.confirm(providerRef);

    // Обновляем платёж + заказ + историю статусов в транзакции
    const updated = await prisma.$transaction(async (tx) => {
      await tx.payment.update({
        where: { providerRef },
        data: { status: result.status },
      });

      if (result.status === 'SUCCEEDED') {
        const o = await tx.order.update({
          where: { id: order.id },
          data: { paymentStatus: 'PAID', status: 'CONFIRMED' },
        });
        await tx.orderStatusHistory.create({
          data: { orderId: order.id, status: 'CONFIRMED', note: 'Оплата получена' },
        });
        return o;
      }

      await tx.order.update({ where: { id: order.id }, data: { paymentStatus: 'FAILED' } });
      return null;
    });

    if (result.status !== 'SUCCEEDED' || !updated) {
      return NextResponse.json({ success: false, error: 'Платёж отклонён', paymentStatus: 'FAILED' }, { status: 402 });
    }

    return NextResponse.json({
      success: true,
      data: { orderNumber, paymentStatus: updated.paymentStatus, status: updated.status },
    });
  } catch (error) {
    console.error('Payment confirm error:', error);
    return NextResponse.json({ success: false, error: 'Ошибка подтверждения платежа' }, { status: 500 });
  }
}
