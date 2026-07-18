// POST /api/payments/intent — создать платёжное намерение для заказа.
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { getPaymentProvider } from '@/lib/payments';

export async function POST(request: NextRequest) {
  try {
    const { orderNumber } = await request.json();
    if (!orderNumber) {
      return NextResponse.json({ success: false, error: 'orderNumber обязателен' }, { status: 400 });
    }

    const order = await prisma.order.findUnique({ where: { orderNumber } });
    if (!order) {
      return NextResponse.json({ success: false, error: 'Заказ не найден' }, { status: 404 });
    }
    if (order.paymentStatus === 'PAID') {
      return NextResponse.json({ success: false, error: 'Заказ уже оплачен' }, { status: 409 });
    }

    const provider = getPaymentProvider();
    const amount = Number(order.totalAmount);
    const intent = await provider.createIntent(amount, order.currency);

    await prisma.payment.create({
      data: {
        orderId: order.id,
        provider: provider.name,
        providerRef: intent.providerRef,
        amount: order.totalAmount,
        currency: order.currency,
        status: 'REQUIRES_CONFIRMATION',
      },
    });

    return NextResponse.json({
      success: true,
      data: { providerRef: intent.providerRef, clientSecret: intent.clientSecret, amount, currency: order.currency },
    });
  } catch (error) {
    console.error('Payment intent error:', error);
    return NextResponse.json({ success: false, error: 'Ошибка создания платежа' }, { status: 500 });
  }
}
