// src/components/products/ProductCard.tsx
'use client';

import Link from 'next/link';
import Image from 'next/image';
import { ShoppingCart } from 'lucide-react';
import { ProductWithCategory } from '@/types/product';
import { formatPrice, getStockStatus, truncate } from '@/lib/utils';
import { Card, CardBody } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import { useCartStore } from '@/store/cartStore';
import { useState } from 'react';

interface ProductCardProps {
  product: ProductWithCategory;
}

export default function ProductCard({ product }: ProductCardProps) {
  const addItem = useCartStore((state) => state.addItem);
  const [isAdding, setIsAdding] = useState(false);
  
  const stockStatus = getStockStatus(product.stock);

  const handleAddToCart = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (product.stock <= 0) return;
    
    setIsAdding(true);
    addItem(product, 1);
    
    // Небольшая задержка для визуального эффекта
    setTimeout(() => {
      setIsAdding(false);
    }, 500);
  };

  return (
    <Link href={`/products/${product.id}`}>
      <Card className="h-full hover:shadow-xl transition-shadow duration-300 cursor-pointer group">
        {/* Изображение */}
        <div className="relative h-64 overflow-hidden bg-gray-100">
          <Image
            src={product.image || '/images/placeholder.jpg'}
            alt={product.name}
            fill
            className="object-cover group-hover:scale-105 transition-transform duration-300"
            sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"
          />
          
          {/* Бейдж категории */}
          <div className="absolute top-3 right-3 bg-pink-600 text-white text-xs font-semibold px-3 py-1 rounded-full">
            {product.category.name}
          </div>
        </div>

        {/* Контент */}
        <CardBody className="flex flex-col h-full">
          <h3 className="text-lg font-bold text-gray-900 mb-2 line-clamp-1">
            {product.name}
          </h3>

          <p className="text-gray-600 text-sm mb-4 flex-grow line-clamp-2">
            {truncate(product.description || '', 80)}
          </p>

          {/* Цена и наличие */}
          <div className="flex items-center justify-between mb-4">
            <span className="text-2xl font-bold text-pink-600">
              {formatPrice(product.price)}
            </span>
            
            <span className={`text-sm font-medium ${stockStatus.className}`}>
              {stockStatus.text}
            </span>
          </div>

          {/* Кнопка */}
          <Button
            onClick={handleAddToCart}
            disabled={product.stock <= 0}
            isLoading={isAdding}
            className="w-full"
          >
            {product.stock > 0 ? (
              <>
                <ShoppingCart className="w-4 h-4 mr-2" />
                В корзину
              </>
            ) : (
              'Нет в наличии'
            )}
          </Button>
        </CardBody>
      </Card>
    </Link>
  );
}
