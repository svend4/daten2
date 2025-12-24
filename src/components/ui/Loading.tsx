// src/components/ui/Loading.tsx
import { Loader2 } from 'lucide-react';

interface LoadingProps {
  message?: string;
}

export default function Loading({ message = 'Загрузка...' }: LoadingProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <Loader2 className="w-12 h-12 text-pink-600 animate-spin" />
      <p className="mt-4 text-gray-600">{message}</p>
    </div>
  );
}
