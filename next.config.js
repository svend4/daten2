// next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    domains: ['via.placeholder.com'],
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**',
      },
    ],
  },
  // Оптимизация для production
  reactStrictMode: true,
  swcMinify: true,
  // Compress
  compress: true,
  // Настройки для production
  poweredByHeader: false,
  // Experimental features
  experimental: {
    optimizeCss: true,
  },
};

module.exports = nextConfig;
