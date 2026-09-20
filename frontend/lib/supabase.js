import { createBrowserClient } from "@supabase/ssr";

export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

let client = null;

/**
 * The browser-side Supabase client, created once per page load.
 *
 * `createBrowserClient` (from @supabase/ssr) rather than plain
 * `createClient`: it stores the session in COOKIES instead of localStorage,
 * which is the only reason middleware.js can see whether someone is signed in.
 * With localStorage the session exists solely inside the tab, so every
 * protected route would have to flash its skeleton and redirect from the
 * client — the thing middleware exists to avoid.
 *
 * Memoised because each call otherwise starts its own auth listener and token
 * refresh timer, and several of them racing is how a session ends up being
 * refreshed twice with the same rotated refresh token.
 */
export function getSupabase() {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set. " +
      "Copy frontend/.env.example to .env.local and fill them in."
    );
  }
  if (!client) {
    client = createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  }
  return client;
}

export default getSupabase;
