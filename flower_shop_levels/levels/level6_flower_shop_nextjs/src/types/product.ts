// src/types/product.ts

export interface Product {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  price: number;
  categoryId: number;
  image: string | null;
  stock: number;
  isActive: boolean;
  createdAt: Date;
  updatedAt: Date;
  category?: Category;
}

export interface Category {
  id: number;
  name: string;
  description: string | null;
  slug: string;
  createdAt: Date;
  productCount?: number;
}

export interface ProductWithCategory extends Product {
  category: Category;
}

export interface ProductsResponse {
  products: ProductWithCategory[];
  total: number;
  page: number;
  limit: number;
}

export interface ProductFilters {
  categoryId?: number;
  search?: string;
  minPrice?: number;
  maxPrice?: number;
}
