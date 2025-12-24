// src/components/ui/Navbar.tsx
'use client';

import Link from 'next/link';
import { ShoppingCart, Flower2 } from 'lucide-react';
import { useCartStore } from '@/store/cartStore';

export default function Navbar() {
  const totalItems = useCartStore((state) => state.getTotalItems());

  return (
    <nav className="bg-gradient-to-r from-pink-600 to-pink-400 text-white shadow-lg">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Логотип */}
          <Link 
            href="/" 
            className="flex items-center space-x-2 text-2xl font-bold hover:opacity-90 transition-opacity"
          >
            <Flower2 className="w-8 h-8" />
            <span>Магазин цветов</span>
          </Link>

          {/* Навигация */}
          <div className="flex items-center space-x-6">
            <Link 
              href="/" 
              className="hover:text-pink-100 transition-colors"
            >
              Каталог
            </Link>

            <Link 
              href="/cart" 
              className="relative flex items-center space-x-2 hover:text-pink-100 transition-colors"
            >
              <ShoppingCart className="w-6 h-6" />
              <span>Корзина</span>
              {totalItems > 0 && (
                <span className="absolute -top-2 -right-2 bg-red-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center">
                  {totalItems}
                </span>
              )}
            </Link>
          </div>
        </div>
      </div>
    </nav>
  );
}
