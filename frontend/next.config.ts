import type { NextConfig } from "next";

const backend = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000/api/v1";
const backendRoot = backend.replace(/\/api\/v1\/?$/, "");

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  allowedDevOrigins: ["localhost:3000", "127.0.0.1:3000", "10.0.0.140", "10.0.0.140:3000"],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backend}/:path*`,
      },
      // The backend's API docs, so the sidebar link works whatever port the backend runs on
      { source: "/docs", destination: `${backendRoot}/docs` },
      { source: "/openapi.json", destination: `${backendRoot}/openapi.json` },
    ];
  },
  // The old mock pages; the agent pages replace them
  async redirects() {
    return [
      { source: "/triage", destination: "/agents/triage", permanent: false },
      { source: "/resolution", destination: "/agents/resolution", permanent: false },
    ];
  },
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
