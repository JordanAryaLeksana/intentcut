import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next.js performance features
  cacheComponents: true,
  partialPrefetching: true,

  // Allow local development hosts
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
  ],
};

export default nextConfig;