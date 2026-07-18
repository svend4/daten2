// src/app/cart/page.tsx
'use client';

import Link from 'next/link';
import { ShoppingBag } from 'lucide-react';
import { useCartStore } from '@/store/cartStore';
import CartItem from '@/components/cart/CartItem';
import CartSummary from '@/components/cart/CartSummary';
import EmptyState from '@/components/ui/EmptyState';
import Button from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';

export default function CartPage() {
  const { items, clearCart } = useCartStore();

  const handleClearCart = () => {
    if (confirm('Очистить всю корзину?')) {
      clearCart();
    }
  };

  if (items.length === 0) {
    return (
      <div className="container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">
          Корзина покупок
        </h1>

        <EmptyState
          icon={<ShoppingBag className="w-16 h-16 text-gray-400" />}
          title="Ваша корзина пуста"
          message="Добавьте товары из каталога"
          actionText="Перейти в каталог"
          actionLink="/"
        />
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold text-gray-900 mb-8">
        Корзина покупок
      </h1>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Товары */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <h2 className="text-xl font-bold">Товары в корзине</h2>
              <Button
                variant="outline"
                size="sm"
                onClick={handleClearCart}
              >
                Очистить корзину
              </Button>
            </CardHeader>

            <CardBody>
              <div className="divide-y">
                {items.map((item) => (
                  <CartItem key={item.id} item={item} />
                ))}
              </div>
            </CardBody>
          </Card>
        </div>

        {/* Итого */}
        <div className="lg:col-span-1">
          <CartSummary />
        </div>
      </div>
    </div>
  );
}
