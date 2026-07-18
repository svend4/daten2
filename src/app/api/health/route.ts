import { NextResponse } from 'next/server';

// Единый контракт: идентификация уровня для gateway/роутера
export async function GET() {
  return NextResponse.json({ ok: true, level: 6, stack: 'Next.js' });
}
