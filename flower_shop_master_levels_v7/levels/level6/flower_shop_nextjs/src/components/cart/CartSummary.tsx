// src/components/cart/CartSummary.tsx
'use client';

import { useRouter } from 'next/navigation';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import { useCartStore } from '@/store/cartStore';
import { formatPrice } from '@/lib/utils';
import { ShoppingCart } from 'lucide-react';

export default function CartSummary() {
  const router = useRouter();
  const { items, getTotalPrice, getTotalItems } = useCartStore();
  
  const totalItems = getTotalItems();
  const totalPrice = getTotalPrice();

  const handleCheckout = () => {
    router.push('/checkout');
  };

  return (
    <Card className="sticky top-20">
      <CardHeader>
        <h2 className="text-xl font-bold">Итого</h2>
      </CardHeader>

      <CardBody className="space-y-4">
        {/* Детали */}
        <div className="space-y-2">
          <div className="flex justify-between text-gray-600">
            <span>Товары ({totalItems}):</span>
            <span className="font-semibold">{formatPrice(totalPrice)}</span>
          </div>
          
          <div className="flex justify-between text-gray-600">
            <span>Доставка:</span>
            <span className="font-semibold text-green-600">Бесплатно</span>
          </div>
        </div>

        <div className="border-t pt-4">
          <div className="flex justify-between text-lg font-bold">
            <span>Итого:</span>
            <span className="text-pink-600">{formatPrice(totalPrice)}</span>
          </div>
        </div>

        {/* Кнопки */}
        <div className="space-y-2">
          <Button 
            onClick={handleCheckout}
            className="w-full"
            size="lg"
          >
            <ShoppingCart className="w-5 h-5 mr-2" />
            Оформить заказ
          </Button>

          <Button
            variant="outline"
            onClick={() => router.push('/')}
            className="w-full"
          >
            Продолжить покупки
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
