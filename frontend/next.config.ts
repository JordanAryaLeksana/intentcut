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

  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;