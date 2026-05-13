/** @type {import('next').NextConfig} */

const nextConfig = {
  async rewrites() {
    return {
      fallback: [
        {
          source: '/api/:path*',
          destination: 'http://backend:8000/api/:path*'
        },
        {
          source: '/ws/:path*',
          destination: 'ws://backend:8000/ws/:path*'
        }
      ]
    }
  },
  env: {
    NEXT_PUBLIC_API_URL: '/api/v1',
    NEXT_PUBLIC_WS_URL: 'ws://localhost:8000'
  }
}

module.exports = nextConfig
