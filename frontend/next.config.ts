import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // the dev badge sat on top of the composer (bottom-left); errors still surface without it
  devIndicators: false,
  cacheComponents: true,
  partialPrefetching: true,
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
