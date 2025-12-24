// src/components/products/ProductGrid.tsx
import { ProductWithCategory } from '@/types/product';
import ProductCard from './ProductCard';
import EmptyState from '@/components/ui/EmptyState';
import { Search } from 'lucide-react';

interface ProductGridProps {
  products: ProductWithCategory[];
}

export default function ProductGrid({ products }: ProductGridProps) {
  if (products.length === 0) {
    return (
      <EmptyState
        icon={<Search className="w-16 h-16 text-gray-400" />}
        title="Товары не найдены"
        message="Попробуйте изменить параметры поиска"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
      {products.map((product) => (
        <ProductCard key={product.id} product={product} />
      ))}
    </div>
  );
}
