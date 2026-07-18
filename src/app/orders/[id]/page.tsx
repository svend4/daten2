// src/app/orders/[id]/page.tsx
'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { CheckCircle, Package, User, MapPin, Phone, Mail, MessageSquare } from 'lucide-react';
import { Order } from '@/types/order';
import { formatPrice, formatDate } from '@/lib/utils';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import Loading from '@/components/ui/Loading';

interface PageProps {
  params: {
    id: string;
  };
}

export default function OrderSuccessPage({ params }: PageProps) {
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  useEffect(() => {
    loadOrder();
  }, [params.id]);

  const pay = async () => {
    if (!order) return;
    setPaying(true);
    setPayError(null);
    try {
      // 1) намерение оплаты
      const intentRes = await fetch('/api/payments/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ orderNumber: order.orderNumber }),
      });
      const intent = await intentRes.json();
      if (!intent.success) throw new Error(intent.error || 'Ошибка платежа');

      // 2) подтверждение (аналог confirm/webhook провайдера)
      const confirmRes = await fetch('/api/payments/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ orderNumber: order.orderNumber, providerRef: intent.data.providerRef }),
      });
      const confirmed = await confirmRes.json();
      if (!confirmed.success) throw new Error(confirmed.error || 'Платёж отклонён');

      await loadOrder();
    } catch (e) {
      setPayError(e instanceof Error ? e.message : 'Ошибка оплаты');
    } finally {
      setPaying(false);
    }
  };

  const loadOrder = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(`/api/orders/${params.id}`);
      const data = await response.json();

      if (data.success) {
        setOrder(data.data);
      } else {
        setError(data.error || 'Заказ не найден');
      }
    } catch (err) {
      setError('Ошибка при загрузке заказа');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <Loading message="Загрузка информации о заказе..." />;
  }

  if (error || !order) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
          {error || 'Заказ не найден'}
        </div>
        <Link href="/">
          <Button>Вернуться на главную</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Успех */}
      <div className="text-center mb-12">
        <div className="inline-flex items-center justify-center w-24 h-24 bg-green-100 rounded-full mb-4">
          <CheckCircle className="w-16 h-16 text-green-600" />
        </div>
        <h1 className="text-4xl font-bold text-gray-900 mb-2">
          Заказ успешно оформлен!
        </h1>
        <p className="text-lg text-gray-600">
          Номер заказа:{' '}
          <span className="font-bold text-pink-600">#{order.id}</span>
        </p>

        {/* Оплата (пила коммерции L6) */}
        <div className="mt-5">
          {order.paymentStatus === 'PAID' ? (
            <span className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-green-100 text-green-800 font-semibold">
              <CheckCircle className="w-5 h-5" /> Оплачено
            </span>
          ) : order.paymentStatus === 'FAILED' ? (
            <div className="space-y-2">
              <span className="inline-block px-4 py-2 rounded-full bg-red-100 text-red-800 font-semibold">Платёж отклонён</span>
              <div><Button onClick={pay} disabled={paying}>{paying ? 'Обработка…' : 'Повторить оплату'}</Button></div>
            </div>
          ) : (
            <div className="space-y-2">
              <span className="inline-block px-3 py-1 rounded-full bg-yellow-100 text-yellow-800 text-sm font-medium">Ожидает оплаты</span>
              <div>
                <Button onClick={pay} disabled={paying}>
                  {paying ? 'Обработка…' : `Оплатить ${formatPrice(order.totalAmount)}`}
                </Button>
              </div>
            </div>
          )}
          {payError && <p className="text-red-600 mt-2">{payError}</p>}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Детали заказа */}
        <Card>
          <CardHeader className="bg-pink-50">
            <div className="flex items-center space-x-2">
              <Package className="w-5 h-5 text-pink-600" />
              <h2 className="text-xl font-bold">Детали заказа</h2>
            </div>
          </CardHeader>

          <CardBody className="space-y-4">
            <div>
              <span className="text-sm text-gray-600">Статус:</span>
              <div className="mt-1">
                <span className="inline-block bg-yellow-100 text-yellow-800 text-sm font-semibold px-3 py-1 rounded-full">
                  Новый
                </span>
              </div>
            </div>

            <div>
              <span className="text-sm text-gray-600">Дата создания:</span>
              <p className="font-semibold text-gray-900">
                {formatDate(order.createdAt)}
              </p>
            </div>

            <div>
              <span className="text-sm text-gray-600">Общая сумма:</span>
              <p className="text-2xl font-bold text-pink-600">
                {formatPrice(order.totalAmount)}
              </p>
            </div>
          </CardBody>
        </Card>

        {/* Контактные данные */}
        <Card>
          <CardHeader className="bg-blue-50">
            <div className="flex items-center space-x-2">
              <User className="w-5 h-5 text-blue-600" />
              <h2 className="text-xl font-bold">Контактные данные</h2>
            </div>
          </CardHeader>

          <CardBody className="space-y-4">
            <div>
              <div className="flex items-center space-x-2 text-sm text-gray-600 mb-1">
                <User className="w-4 h-4" />
                <span>Имя:</span>
              </div>
              <p className="font-semibold text-gray-900">
                {order.customer?.name}
              </p>
            </div>

            <div>
              <div className="flex items-center space-x-2 text-sm text-gray-600 mb-1">
                <Phone className="w-4 h-4" />
                <span>Телефон:</span>
              </div>
              <p className="font-semibold text-gray-900">
                {order.customer?.phone}
              </p>
            </div>

            {order.customer?.email && (
              <div>
                <div className="flex items-center space-x-2 text-sm text-gray-600 mb-1">
                  <Mail className="w-4 h-4" />
                  <span>Email:</span>
                </div>
                <p className="font-semibold text-gray-900">
                  {order.customer.email}
                </p>
              </div>
            )}

            <div>
              <div className="flex items-center space-x-2 text-sm text-gray-600 mb-1">
                <MapPin className="w-4 h-4" />
                <span>Адрес доставки:</span>
              </div>
              <p className="font-semibold text-gray-900">
                {order.deliveryAddress}
              </p>
            </div>

            {order.notes && (
              <div>
                <div className="flex items-center space-x-2 text-sm text-gray-600 mb-1">
                  <MessageSquare className="w-4 h-4" />
                  <span>Комментарий:</span>
                </div>
                <p className="font-semibold text-gray-900">{order.notes}</p>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Товары в заказе */}
      <Card className="mb-8">
        <CardHeader className="bg-gray-50">
          <h2 className="text-xl font-bold">Товары в заказе</h2>
        </CardHeader>

        <CardBody>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-3 px-2">Товар</th>
                  <th className="text-right py-3 px-2">Цена</th>
                  <th className="text-center py-3 px-2">Количество</th>
                  <th className="text-right py-3 px-2">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {order.items?.map((item) => (
                  <tr key={item.id} className="border-b last:border-b-0">
                    <td className="py-3 px-2">
                      <div className="flex items-center space-x-3">
                        {item.product?.image && (
                          <div className="relative w-12 h-12 flex-shrink-0 rounded-lg overflow-hidden bg-gray-100">
                            <Image
                              src={item.product.image}
                              alt={item.product.name}
                              fill
                              className="object-cover"
                              sizes="48px"
                            />
                          </div>
                        )}
                        <span className="font-medium">
                          {item.productName ?? item.product?.name}
                        </span>
                      </div>
                    </td>
                    <td className="text-right py-3 px-2">
                      {formatPrice(item.unitPrice)}
                    </td>
                    <td className="text-center py-3 px-2">
                      {item.quantity} шт.
                    </td>
                    <td className="text-right py-3 px-2 font-semibold">
                      {formatPrice(item.lineTotal)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-gray-50">
                  <td colSpan={3} className="text-right py-4 px-2 font-bold">
                    Итого:
                  </td>
                  <td className="text-right py-4 px-2 font-bold text-lg text-pink-600">
                    {formatPrice(order.totalAmount)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </CardBody>
      </Card>

      {/* Что дальше? */}
      <Card className="mb-8">
        <CardHeader className="bg-green-50">
          <h2 className="text-xl font-bold text-green-900">
            📞 Что дальше?
          </h2>
        </CardHeader>

        <CardBody>
          <ol className="space-y-3 text-gray-700">
            <li className="flex items-start space-x-2">
              <span className="flex-shrink-0 w-6 h-6 bg-green-100 text-green-700 rounded-full flex items-center justify-center text-sm font-bold">
                1
              </span>
              <span>
                Мы свяжемся с вами по телефону{' '}
                <strong>{order.customer?.phone}</strong> в течение 15 минут для
                подтверждения заказа
              </span>
            </li>
            <li className="flex items-start space-x-2">
              <span className="flex-shrink-0 w-6 h-6 bg-green-100 text-green-700 rounded-full flex items-center justify-center text-sm font-bold">
                2
              </span>
              <span>Уточним время доставки (обычно 2-4 часа)</span>
            </li>
            <li className="flex items-start space-x-2">
              <span className="flex-shrink-0 w-6 h-6 bg-green-100 text-green-700 rounded-full flex items-center justify-center text-sm font-bold">
                3
              </span>
              <span>
                Доставим свежие цветы по адресу:{' '}
                <strong>{order.deliveryAddress}</strong>
              </span>
            </li>
            <li className="flex items-start space-x-2">
              <span className="flex-shrink-0 w-6 h-6 bg-green-100 text-green-700 rounded-full flex items-center justify-center text-sm font-bold">
                4
              </span>
              <span>Оплата при получении наличными или картой курьеру</span>
            </li>
          </ol>
        </CardBody>
      </Card>

      {/* Кнопка */}
      <div className="text-center">
        <Link href="/">
          <Button size="lg">Вернуться на главную</Button>
        </Link>
      </div>
    </div>
  );
}
