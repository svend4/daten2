// src/app/checkout/page.tsx
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import { useCartStore } from '@/store/cartStore';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import { formatPrice } from '@/lib/utils';
import { createOrderSchema } from '@/lib/validations';
import { Phone, Mail, MapPin, AlertCircle } from 'lucide-react';

export default function CheckoutPage() {
  const router = useRouter();
  const { items, getTotalPrice, clearCart } = useCartStore();

  const [formData, setFormData] = useState({
    name: '',
    phone: '',
    email: '',
    address: '',
    notes: '',
  });

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const totalPrice = getTotalPrice();

  // Редирект если корзина пуста
  useEffect(() => {
    if (items.length === 0) {
      router.push('/');
    }
  }, [items, router]);

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));

    // Очистить ошибку поля
    if (errors[name]) {
      setErrors((prev) => {
        const newErrors = { ...prev };
        delete newErrors[name];
        return newErrors;
      });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    setIsSubmitting(true);
    setApiError(null);
    setErrors({});

    try {
      // Подготовить данные заказа
      const orderData = {
        customer: {
          name: formData.name.trim(),
          phone: formData.phone.trim(),
          email: formData.email.trim() || undefined,
          address: formData.address.trim(),
        },
        items: items.map((item) => ({
          productId: item.id,
          quantity: item.quantity,
        })),
        notes: formData.notes.trim() || undefined,
      };

      // Валидация
      const validationResult = createOrderSchema.safeParse(orderData);

      if (!validationResult.success) {
        const newErrors: Record<string, string> = {};
        validationResult.error.errors.forEach((error) => {
          const path = error.path.join('.');
          newErrors[path] = error.message;
        });
        setErrors(newErrors);
        setIsSubmitting(false);
        return;
      }

      // Отправить заказ
      const response = await fetch('/api/orders', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(orderData),
      });

      const data = await response.json();

      if (data.success) {
        // Очистить корзину
        clearCart();

        // Перейти на страницу успеха по непубличному номеру заказа
        router.push(`/orders/${data.data.orderNumber}`);
      } else {
        setApiError(
          Array.isArray(data.errors)
            ? data.errors.join(', ')
            : data.error || 'Ошибка при создании заказа'
        );
      }
    } catch (error) {
      console.error('Checkout error:', error);
      setApiError('Ошибка при создании заказа. Попробуйте ещё раз.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (items.length === 0) {
    return null;
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-gray-900 mb-8">
        Оформление заказа
      </h1>

      {/* Ошибка API */}
      {apiError && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-start space-x-2">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <span>{apiError}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Форма */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <h2 className="text-xl font-bold">Контактные данные</h2>
            </CardHeader>

            <CardBody>
              <form onSubmit={handleSubmit} className="space-y-6">
                {/* Имя */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Ваше имя *
                  </label>
                  <input
                    type="text"
                    name="name"
                    placeholder="Иван Петров"
                    value={formData.name}
                    onChange={handleChange}
                    className={`w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 ${
                      errors['customer.name']
                        ? 'border-red-500 focus:ring-red-600'
                        : 'border-gray-300 focus:ring-pink-600'
                    }`}
                    required
                  />
                  {errors['customer.name'] && (
                    <p className="mt-1 text-sm text-red-600">
                      {errors['customer.name']}
                    </p>
                  )}
                </div>

                {/* Телефон */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    <Phone className="inline w-4 h-4 mr-1" />
                    Телефон *
                  </label>
                  <input
                    type="tel"
                    name="phone"
                    placeholder="+7 (900) 123-45-67"
                    value={formData.phone}
                    onChange={handleChange}
                    className={`w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 ${
                      errors['customer.phone']
                        ? 'border-red-500 focus:ring-red-600'
                        : 'border-gray-300 focus:ring-pink-600'
                    }`}
                    required
                  />
                  {errors['customer.phone'] && (
                    <p className="mt-1 text-sm text-red-600">
                      {errors['customer.phone']}
                    </p>
                  )}
                  <p className="mt-1 text-sm text-gray-500">
                    Формат: +7 (900) 123-45-67
                  </p>
                </div>

                {/* Email */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    <Mail className="inline w-4 h-4 mr-1" />
                    Email
                  </label>
                  <input
                    type="email"
                    name="email"
                    placeholder="ivan@example.com"
                    value={formData.email}
                    onChange={handleChange}
                    className={`w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 ${
                      errors['customer.email']
                        ? 'border-red-500 focus:ring-red-600'
                        : 'border-gray-300 focus:ring-pink-600'
                    }`}
                  />
                  {errors['customer.email'] && (
                    <p className="mt-1 text-sm text-red-600">
                      {errors['customer.email']}
                    </p>
                  )}
                  <p className="mt-1 text-sm text-gray-500">
                    Необязательно, но мы отправим подтверждение
                  </p>
                </div>

                {/* Адрес */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    <MapPin className="inline w-4 h-4 mr-1" />
                    Адрес доставки *
                  </label>
                  <textarea
                    name="address"
                    rows={3}
                    placeholder="Город, улица, дом, квартира"
                    value={formData.address}
                    onChange={handleChange}
                    className={`w-full px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 ${
                      errors['customer.address']
                        ? 'border-red-500 focus:ring-red-600'
                        : 'border-gray-300 focus:ring-pink-600'
                    }`}
                    required
                  />
                  {errors['customer.address'] && (
                    <p className="mt-1 text-sm text-red-600">
                      {errors['customer.address']}
                    </p>
                  )}
                </div>

                {/* Комментарий */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Комментарий к заказу
                  </label>
                  <textarea
                    name="notes"
                    rows={2}
                    placeholder="Дополнительные пожелания"
                    value={formData.notes}
                    onChange={handleChange}
                    className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-pink-600"
                  />
                </div>

                {/* Информация о доставке */}
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <h3 className="font-semibold text-blue-900 mb-2">
                    ℹ️ Информация о доставке:
                  </h3>
                  <ul className="space-y-1 text-sm text-blue-800">
                    <li>⏰ Доставка в течение 2-4 часов</li>
                    <li>💳 Оплата при получении (наличные или карта)</li>
                    <li>🚚 Бесплатная доставка по городу</li>
                  </ul>
                </div>

                {/* Кнопки */}
                <div className="flex flex-col sm:flex-row gap-3">
                  <Button
                    type="submit"
                    isLoading={isSubmitting}
                    size="lg"
                    className="flex-1"
                  >
                    Подтвердить заказ
                  </Button>

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => router.push('/cart')}
                    disabled={isSubmitting}
                    size="lg"
                  >
                    Вернуться в корзину
                  </Button>
                </div>
              </form>
            </CardBody>
          </Card>
        </div>

        {/* Сводка заказа */}
        <div className="lg:col-span-1">
          <Card className="sticky top-20">
            <CardHeader>
              <h2 className="text-xl font-bold">Ваш заказ</h2>
            </CardHeader>

            <CardBody className="space-y-4">
              {/* Товары */}
              <div className="space-y-3 max-h-96 overflow-y-auto">
                {items.map((item) => (
                  <div key={item.id} className="flex items-start gap-3 pb-3 border-b last:border-b-0">
                    <div className="relative w-16 h-16 flex-shrink-0 rounded-lg overflow-hidden bg-gray-100">
                      <Image
                        src={item.image || '/images/placeholder.jpg'}
                        alt={item.name}
                        fill
                        className="object-cover"
                        sizes="64px"
                      />
                    </div>

                    <div className="flex-grow min-w-0">
                      <h4 className="font-semibold text-sm text-gray-900 truncate">
                        {item.name}
                      </h4>
                      <p className="text-xs text-gray-500">
                        {item.quantity} шт. × {formatPrice(item.price)}
                      </p>
                    </div>

                    <div className="text-right flex-shrink-0">
                      <span className="font-semibold text-sm">
                        {formatPrice(
                          parseFloat(item.price.toString()) * item.quantity
                        )}
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Итого */}
              <div className="border-t pt-4 space-y-2">
                <div className="flex justify-between text-gray-600">
                  <span>Товары ({items.length}):</span>
                  <span className="font-semibold">{formatPrice(totalPrice)}</span>
                </div>

                <div className="flex justify-between text-gray-600">
                  <span>Доставка:</span>
                  <span className="font-semibold text-green-600">Бесплатно</span>
                </div>

                <div className="flex justify-between text-lg font-bold pt-2 border-t">
                  <span>Итого:</span>
                  <span className="text-pink-600">{formatPrice(totalPrice)}</span>
                </div>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
