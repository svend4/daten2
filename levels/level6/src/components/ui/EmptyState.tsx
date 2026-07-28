// src/components/ui/EmptyState.tsx
import { ReactNode } from 'react';
import Link from 'next/link';
import Button from './Button';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  message?: string;
  actionText?: string;
  actionLink?: string;
}

export default function EmptyState({
  icon,
  title,
  message,
  actionText = 'На главную',
  actionLink = '/',
}: EmptyStateProps) {
  return (
    <div className="text-center py-12">
      {icon && <div className="flex justify-center mb-4">{icon}</div>}
      
      <h3 className="text-2xl font-bold text-gray-900 mb-2">{title}</h3>
      
      {message && <p className="text-gray-600 mb-6">{message}</p>}
      
      <Link href={actionLink}>
        <Button>{actionText}</Button>
      </Link>
    </div>
  );
}
