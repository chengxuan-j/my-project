/** @type {import('next').NextConfig} */
// 后端地址：容器/线上通过环境变量 BACKEND_URL 注入（Next rewrites 在构建期生效）
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

const nextConfig = {
  reactStrictMode: true,
  // 构建输出目录，可用 NEXT_DIST_DIR 覆盖。默认 .next；
  // 当 .next 被中断的构建写坏、又不方便删目录时，指向一个新目录即可绕过。
  distDir: process.env.NEXT_DIST_DIR || '.next',
  // 仅 Docker 构建（BUILD_STANDALONE=1）生成 standalone 产物；本地构建保持快速
  output: process.env.BUILD_STANDALONE === '1' ? 'standalone' : undefined,
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${BACKEND_URL}/api/v1/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: '/sw.js',
        headers: [
          { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
          { key: 'Service-Worker-Allowed', value: '/' },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
