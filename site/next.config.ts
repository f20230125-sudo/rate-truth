import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// Fonts, scripts and data are same-origin. Hotel names and tool output are untrusted
// text and are rendered through React escaping. Browser API traffic uses rewrites.
// 'unsafe-inline' is for the small scripts Next.js writes into each page and the one that sets the theme before
// first paint; nonces would stop pages being built ahead of time.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self' https://uzair-khan-lac.vercel.app",
].join("; ");

const nextConfig: NextConfig = {
  async rewrites() {
    const api = (process.env.RT_API_URL ?? "http://127.0.0.1:8170").replace(/\/$/, "");
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
      { source: "/mcp", destination: `${api}/mcp` },
    ];
  },
  allowedDevOrigins: ["127.0.0.1"],
  devIndicators: false,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
