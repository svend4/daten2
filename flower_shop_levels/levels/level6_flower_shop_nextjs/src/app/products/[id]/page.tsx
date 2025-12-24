// src/app/products/[id]/page.tsx
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import Link from 'next/link';
import { ShoppingCart, ChevronLeft, Check } from 'lucide-react';
import { ProductWithCategory } from '@/types/product';
import { formatPrice, getStockStatus } from '@/lib/utils';
import { useCartStore } from '@/store/cartStore';
import Button from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import Loading from '@/components/ui/Loading';

interface PageProps {
  params: {
    id: string;
  };
}

export default function ProductDetailPage({ params }: PageProps) {
  const router = useRouter();
  const addItem = useCartStore((state) => state.addItem);

  const [product, setProduct] = useState<ProductWithCategory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [isAdding, setIsAdding] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);

  useEffect(() => {
    loadProduct();
  }, [params.id]);

  const loadProduct = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(`/api/products/${params.id}`);
      const data = await response.json();

      if (data.success) {
        setProduct(data.data);
      } else {
        setError(data.error || 'Товар не найден');
      }
    } catch (err) {
      setError('Ошибка при загрузке товара');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleAddToCart = async () => {
    if (!product) return;

    setIsAdding(true);
    addItem(product, quantity);

    // Показать уведомление
    setShowSuccess(true);
    setTimeout(() => {
      setShowSuccess(false);
    }, 3000);

    setIsAdding(false);
  };

  if (loading) {
    return <Loading message="Загрузка товара..." />;
  }

  if (error || !product) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
          {error || 'Товар не найден'}
        </div>
        <Link href="/">
          <Button>
            <ChevronLeft className="w-4 h-4 mr-2" />
            Вернуться в каталог
          </Button>
        </Link>
      </div>
    );
  }

  const stockStatus = getStockStatus(product.stock);

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <nav className="flex items-center space-x-2 text-sm text-gray-600 mb-6">
        <Link href="/" className="hover:text-pink-600">
          Каталог
        </Link>
        <span>/</span>
        <Link href={`/?category=${product.categoryId}`} className="hover:text-pink-600">
          {product.category.name}
        </Link>
        <span>/</span>
        <span className="text-gray-900">{product.name}</span>
      </nav>

      {/* Уведомление об успехе */}
      {showSuccess && (
        <div className="fixed top-20 right-4 z-50 bg-green-500 text-white px-6 py-3 rounded-lg shadow-lg flex items-center space-x-2 animate-slide-in">
          <Check className="w-5 h-5" />
          <span>Товар добавлен в корзину!</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Изображение */}
        <div>
          <div className="relative aspect-square rounded-xl overflow-hidden bg-gray-100">
            <Image
              src={product.image || '/images/placeholder.jpg'}
              alt={product.name}
              fill
              className="object-cover"
              priority
              sizes="(max-width: 768px) 100vw, 50vw"
            />
          </div>
        </div>

        {/* Информация */}
        <div>
          <Card>
            <CardBody className="space-y-6">
              {/* Категория */}
              <div>
                <span className="inline-block bg-pink-100 text-pink-700 text-sm font-semibold px-3 py-1 rounded-full">
                  {product.category.name}
                </span>
              </div>

              {/* Название */}
              <h1 className="text-3xl font-bold text-gray-900">
                {product.name}
              </h1>

              {/* Описание */}
              <p className="text-gray-600 text-lg leading-relaxed">
                {product.description}
              </p>

              <div className="border-t pt-6" />

              {/* Цена */}
              <div>
                <h3 className="text-4xl font-bold text-pink-600">
                  {formatPrice(product.price)}
                </h3>
              </div>

              {/* Наличие */}
              <div>
                {product.stock > 10 ? (
                  <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg">
                    <div className="flex items-center space-x-2">
                      <Check className="w-5 h-5" />
                      <span className="font-semibold">В наличии</span>
                      <span className="text-sm">({product.stock} шт.)</span>
                    </div>
                  </div>
                ) : product.stock > 0 ? (
                  <div className="bg-yellow-50 border border-yellow-200 text-yellow-700 px-4 py-3 rounded-lg">
                    <div className="flex items-center space-x-2">
                      <span className="font-semibold">Осталось мало</span>
                      <span className="text-sm">({product.stock} шт.)</span>
                    </div>
                  </div>
                ) : (
                  <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
                    <span className="font-semibold">Нет в наличии</span>
                  </div>
                )}
              </div>

              {/* Количество */}
              {product.stock > 0 && (
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Количество:
                  </label>
                  <input
                    type="number"
                    min="1"
                    max={product.stock}
                    value={quantity}
                    onChange={(e) => {
                      const value = parseInt(e.target.value);
                      if (value >= 1 && value <= product.stock) {
                        setQuantity(value);
                      }
                    }}
                    className="w-32 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-pink-600"
                  />
                </div>
              )}

              {/* Кнопки */}
              <div className="space-y-3">
                {product.stock > 0 ? (
                  <Button
                    onClick={handleAddToCart}
                    isLoading={isAdding}
                    size="lg"
                    className="w-full"
                  >
                    <ShoppingCart className="w-5 h-5 mr-2" />
                    Добавить в корзину
                  </Button>
                ) : (
                  <Button disabled size="lg" className="w-full">
                    Нет в наличии
                  </Button>
                )}

                <Link href="/" className="block">
                  <Button variant="outline" className="w-full">
                    <ChevronLeft className="w-4 h-4 mr-2" />
                    Вернуться в каталог
                  </Button>
                </Link>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>

      {/* Дополнительная информация */}
      <div className="mt-12">
        <Card>
          <CardBody>
            <h2 className="text-2xl font-bold text-gray-900 mb-6">
              Информация о доставке и оплате
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <h3 className="font-semibold text-gray-900 mb-2">
                  🚚 Доставка
                </h3>
                <p className="text-gray-600 text-sm">
                  Доставка по городу в течение 2-4 часов.
                  <br />
                  Бесплатная доставка при заказе от 2000 ₽.
                </p>
              </div>

              <div>
                <h3 className="font-semibold text-gray-900 mb-2">
                  💳 Оплата
                </h3>
                <p className="text-gray-600 text-sm">
                  Оплата при получении наличными или картой.
                  <br />
                  Также доступна онлайн-оплата.
                </p>
              </div>

              <div>
                <h3 className="font-semibold text-gray-900 mb-2">
                  🌺 Качество
                </h3>
                <p className="text-gray-600 text-sm">
                  Гарантируем свежесть цветов.
                  <br />
                  Замена букета, если он не понравился.
                </p>
              </div>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
