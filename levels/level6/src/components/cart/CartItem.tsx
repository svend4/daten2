// src/components/cart/CartItem.tsx
'use client';

import Image from 'next/image';
import { Minus, Plus, Trash2 } from 'lucide-react';
import { CartItem as CartItemType } from '@/types/cart';
import { formatPrice } from '@/lib/utils';
import { useCartStore } from '@/store/cartStore';
import Button from '@/components/ui/Button';

interface CartItemProps {
  item: CartItemType;
}

export default function CartItem({ item }: CartItemProps) {
  const { updateQuantity, removeItem } = useCartStore();

  const handleDecrease = () => {
    if (item.quantity > 1) {
      updateQuantity(item.id, item.quantity - 1);
    }
  };

  const handleIncrease = () => {
    if (item.quantity < item.stock) {
      updateQuantity(item.id, item.quantity + 1);
    }
  };

  const handleRemove = () => {
    if (confirm('Удалить товар из корзины?')) {
      removeItem(item.id);
    }
  };

  const subtotal = parseFloat(item.price.toString()) * item.quantity;

  return (
    <div className="flex items-center gap-4 py-4 border-b last:border-b-0">
      {/* Изображение */}
      <div className="relative w-24 h-24 flex-shrink-0 rounded-lg overflow-hidden bg-gray-100">
        <Image
          src={item.image || '/images/placeholder.jpg'}
          alt={item.name}
          fill
          className="object-cover"
          sizes="96px"
        />
      </div>

      {/* Информация */}
      <div className="flex-grow">
        <h3 className="font-semibold text-gray-900 mb-1">{item.name}</h3>
        <p className="text-sm text-gray-500">{item.category?.name}</p>
        <p className="text-lg font-bold text-pink-600 mt-2">
          {formatPrice(item.price)}
        </p>
      </div>

      {/* Количество */}
      <div className="flex items-center gap-2">
        <button
          onClick={handleDecrease}
          className="w-8 h-8 flex items-center justify-center rounded-lg border border-gray-300 hover:bg-gray-100 transition-colors"
          disabled={item.quantity <= 1}
        >
          <Minus className="w-4 h-4" />
        </button>

        <span className="w-12 text-center font-semibold">{item.quantity}</span>

        <button
          onClick={handleIncrease}
          className="w-8 h-8 flex items-center justify-center rounded-lg border border-gray-300 hover:bg-gray-100 transition-colors"
          disabled={item.quantity >= item.stock}
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {/* Сумма */}
      <div className="text-right min-w-[100px]">
        <p className="font-bold text-lg text-gray-900">
          {formatPrice(subtotal)}
        </p>
      </div>

      {/* Удалить */}
      <button
        onClick={handleRemove}
        className="text-red-600 hover:text-red-700 transition-colors p-2"
        title="Удалить"
      >
        <Trash2 className="w-5 h-5" />
      </button>
    </div>
  );
}
