/** @type {import('next').NextConfig} */

// Security headers for the financial-data view. The dashboard is a self-contained
// server-rendered app (no third-party scripts, no embeds), so a tight CSP is safe.
// 'unsafe-inline' is required for Next's hydration bootstrap script and inline
// styles (Tailwind / Next inject them); switching to nonces would need a custom
// middleware/CSP plumbing that is overkill for a read-only status page.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "font-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig = {
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Content-Security-Policy", value: csp },
        ],
      },
    ];
  },
};

export default nextConfig;
