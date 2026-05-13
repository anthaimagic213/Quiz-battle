/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  compiler: {
    removeConsole: process.env.NODE_ENV === "production",
  },
  async rewrites() {
    return {
      fallback: [
        {
          source: '/api/:path*',
          destination: 'http://backend:8000/api/:path*'
        }
      ]
    }
  },
  env: {
    NEXT_PUBLIC_API_URL: "/api/v1",
    // WebSocket URL will be auto-detected in websocketService.ts based on page protocol
    NEXT_PUBLIC_WS_URL: "/",
  },
};

module.exports = nextConfig;
