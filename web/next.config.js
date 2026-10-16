/** @type {import('next').NextConfig} */
// Who may frame the app: itself, the instaEcosystem shell (desk PC and tailnet) and the admin page.
const frameAncestors = [
  "'self'",
  'http://localhost:28100',
  'http://127.0.0.1:28100',
  'http://localhost:28101',
  'https://beast.tail88cf35.ts.net:8444',
  'https://sathwik.info',
].join(' ')

const nextConfig = {
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [{ key: 'Content-Security-Policy', value: `frame-ancestors ${frameAncestors}` }],
      },
    ]
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.API_ORIGIN ?? 'http://localhost:8000'}/api/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
