import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // create-next-app 16.4 has no PostCSS config: Turbopack runs Tailwind through this loader.
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
