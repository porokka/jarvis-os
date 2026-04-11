/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_JARVIS_TOKEN: process.env.JARVIS_API_TOKEN || "jarvis-local-token",
  },
};

module.exports = nextConfig;
