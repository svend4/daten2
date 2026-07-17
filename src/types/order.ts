// src/types/order.ts

export enum OrderStatus {
  NEW = 'NEW',
  CONFIRMED = 'CONFIRMED',
  PREPARING = 'PREPARING',
  DELIVERING = 'DELIVERING',
  COMPLETED = 'COMPLETED',
  CANCELLED = 'CANCELLED',
}

export enum PaymentStatus {
  PENDING = 'PENDING',
  PAID = 'PAID',
  REFUNDED = 'REFUNDED',
  FAILED = 'FAILED',
}

export interface Customer {
  id: number;
  name: string;
  phone: string;
  email: string | null;
  address: string;
  city?: string | null;
  postalCode?: string | null;
  createdAt: Date;
}

export interface OrderItem {
  id: number;
  orderId: number;
  productId: number | null;
  productName: string;
  quantity: number;
  unitPrice: number;
  lineTotal: number;
  product?: {
    name: string;
    image: string | null;
  };
}

export interface Order {
  id: number;
  orderNumber: string;
  customerId: number;
  subtotal: number;
  discount: number;
  deliveryFee: number;
  totalAmount: number;
  currency: string;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  deliveryAddress: string;
  deliveryDate: Date | null;
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
