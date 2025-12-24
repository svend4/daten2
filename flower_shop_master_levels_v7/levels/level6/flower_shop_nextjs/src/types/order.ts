// src/types/order.ts

export enum OrderStatus {
  NEW = 'NEW',
  CONFIRMED = 'CONFIRMED',
  PREPARING = 'PREPARING',
  DELIVERING = 'DELIVERING',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
}

export interface Customer {
  id: number;
  name: string;
  phone: string;
  email: string | null;
  address: string;
  createdAt: Date;
}

export interface OrderItem {
  id: number;
  orderId: number;
  productId: number;
  quantity: number;
  price: number;
  product?: {
    name: string;
    image: string | null;
  };
}

export interface Order {
  id: number;
  customerId: number;
  totalAmount: number;
  status: OrderStatus;
  deliveryAddress: string;
  notes: string | null;
  createdAt: Date;
  updatedAt: Date;
  customer?: Customer;
  items?: OrderItem[];
}

export interface CreateOrderData {
  customer: {
    name: string;
    phone: string;
    email?: string;
    address: string;
  };
  items: {
    productId: number;
    quantity: number;
  }[];
  notes?: string;
}
