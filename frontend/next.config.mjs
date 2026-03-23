/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  basePath: '/geo-auditor',
  assetPrefix: '/geo-auditor/',
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
