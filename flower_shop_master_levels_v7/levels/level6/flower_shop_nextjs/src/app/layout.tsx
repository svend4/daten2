// src/app/layout.tsx
import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import Navbar from '@/components/ui/Navbar';
import Footer from '@/components/ui/Footer';
import './globals.css';

const inter = Inter({ subsets: ['latin', 'cyrillic'] });

export const metadata: Metadata = {
  title: 'Магазин цветов - Свежие цветы с доставкой',
  description: 'Интернет-магазин цветов. Свежие букеты с быстрой доставкой по городу. Розы, тюльпаны, букеты на любой случай.',
  keywords: 'цветы, букеты, розы, тюльпаны, доставка цветов',
  authors: [{ name: 'Flower Shop' }],
  openGraph: {
    title: 'Магазин цветов',
    description: 'Свежие цветы с доставкой',
    type: 'website',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru">
      <body className={inter.className}>
        <div className="flex flex-col min-h-screen">
          <Navbar />
          <main className="flex-grow">{children}</main>
          <Footer />
        </div>
      </body>
    </html>
  );
}
