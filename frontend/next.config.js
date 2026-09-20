/**
 * Build-time configuration.
 *
 * The checks below run during `next build`. That is deliberate: every
 * NEXT_PUBLIC_ value is INLINED into the JavaScript bundle at build time, so a
 * variable that is missing when Vercel builds cannot be supplied later by
 * setting it in the dashboard — the bundle is already wrong, and only a rebuild
 * fixes it. Failing the build is the only feedback that arrives in time.
 *
 * This config previously defaulted NEXT_PUBLIC_API_URL to http://localhost:8000,
 * which meant a production deploy with the variable unset built successfully and
 * then had every browser call its own machine. The site looked deployed and
 * nothing worked.
 */

const REQUIRED_IN_PRODUCTION = [
  ["NEXT_PUBLIC_SUPABASE_URL", "Supabase → Project Settings → Data API → Project URL"],
  ["NEXT_PUBLIC_SUPABASE_ANON_KEY", "Supabase → Project Settings → API Keys → anon / publishable"],
  ["NEXT_PUBLIC_API_URL", "the public URL of the deployed backend, e.g. https://vaulto-api.onrender.com"],
];

const isProductionBuild =
  process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_SKIP_ENV_CHECK !== "1";

if (isProductionBuild) {
  const missing = REQUIRED_IN_PRODUCTION.filter(([name]) => !(process.env[name] || "").trim());
  if (missing.length) {
    throw new Error(
      "Cannot build for production — these environment variables are not set:\n\n" +
        missing.map(([name, where]) => `  • ${name}\n      get it from: ${where}`).join("\n") +
        "\n\nOn Vercel: Project → Settings → Environment Variables, then redeploy.\n" +
        "Locally: copy frontend/.env.example to frontend/.env.local and fill it in.\n" +
        "See ENVIRONMENT.md for what each value is.\n" +
        "(Set NEXT_PUBLIC_SKIP_ENV_CHECK=1 to bypass this — the build will produce a broken site.)\n"
    );
  }

  const api = (process.env.NEXT_PUBLIC_API_URL || "").trim();
  if (api.startsWith("http://") && !api.includes("localhost") && !api.includes("127.0.0.1")) {
    throw new Error(
      `NEXT_PUBLIC_API_URL is plaintext HTTP (${api}). A page served over HTTPS cannot ` +
        "call it — the browser blocks the request as mixed content. Use https://.\n"
    );
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // NEXT_PUBLIC_* variables are inlined by Next.js on their own; the explicit
  // `env` block that used to be here existed only to add the localhost default.
  async redirects() {
    return [
      { source: "/signup", destination: "/auth", permanent: true },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
