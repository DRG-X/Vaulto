/**
 * Where to send someone after they sign in.
 *
 * The value arrives in a query string, so it is attacker-controllable: an
 * absolute URL here would turn our sign-in page into an open redirect onto
 * someone else's site, with our domain in the address bar on the way. Only
 * same-site paths are honoured — anything else falls back.
 */

// Pages that are steps IN the sign-in flow rather than destinations after it.
// Returning to one of these would loop: /post-auth sends you to the place you
// came from, and if that place is /post-auth, you never arrive anywhere.
const FLOW_PAGES = ["/auth", "/post-auth", "/sso-callback", "/onboarding"];

export function safeRedirect(value, fallback = "/dashboard") {
  if (typeof value !== "string") return fallback;
  const path = value.trim();
  // "//evil.com" and "/\evil.com" are protocol-relative URLs, not local paths.
  if (!path.startsWith("/") || path.startsWith("//") || path.startsWith("/\\")) return fallback;
  const base = path.split(/[?#]/)[0].replace(/\/+$/, "") || "/";
  if (FLOW_PAGES.includes(base)) return fallback;
  return path;
}

/** Pull `?redirect_url=` off a Next.js router query, safely. */
export function redirectFromQuery(query, fallback = "/dashboard") {
  const raw = query?.redirect_url;
  return safeRedirect(Array.isArray(raw) ? raw[0] : raw, fallback);
}

/** Append `?redirect_url=` to a path, skipping the default destination. */
export function withRedirect(path, redirectTo) {
  if (!redirectTo || redirectTo === "/dashboard") return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}redirect_url=${encodeURIComponent(redirectTo)}`;
}

/** The sign-in URL that returns the user to where they are now. */
export function signInPath(currentPath) {
  const path = safeRedirect(currentPath, "");
  return path ? `/auth?redirect_url=${encodeURIComponent(path)}` : "/auth";
}
