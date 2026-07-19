/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  env: {
    API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "http://api:8000",
  },
  // /api/* is proxied at request time via app/api/[...path]/route.ts which
  // reads process.env.BACKEND_URL at runtime. Keeping rewrites here would
  // bake the build-time value and shadow the Route Handler.
};
export default nextConfig;
