import { createServerClient } from "@supabase/ssr";
import { NextResponse } from "next/server";

const PROTECTED = [
  /^\/dashboard(\/.*)?$/,
  /^\/onboarding(\/.*)?$/,
  /^\/history(\/.*)?$/,
  /^\/alerts(\/.*)?$/,
  /^\/settings(\/.*)?$/,
  /^\/admin(\/.*)?$/,
];

function isProtected(pathname) {
  return PROTECTED.some((pattern) => pattern.test(pathname));
}

export async function middleware(request) {
  // Every branch below returns THIS response object, because the Supabase
  // client writes refreshed session cookies onto it. Building a fresh
  // NextResponse on the redirect path instead would drop a token that was
  // just rotated, and the next request would arrive with a stale one.
  let response = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) {
    // Unconfigured: let the request through rather than locking the whole app
    // out of its own pages. The client-side guard still fires, and getSupabase()
    // throws with an actionable message.
    return response;
  }

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options)
        );
      },
    },
  });

  // getUser(), not getSession(): it revalidates the token with Supabase rather
  // than trusting the cookie, and the cookie is attacker-supplied data. It is
  // also what refreshes an expired token — the call that keeps a signed-in
  // user signed in across a reload.
  const { data: { user } } = await supabase.auth.getUser();

  if (!user && isProtected(request.nextUrl.pathname)) {
    const signIn = request.nextUrl.clone();
    signIn.pathname = "/auth";
    // Come back here after signing in, instead of dumping everyone on the
    // dashboard and making them navigate again.
    signIn.searchParams.set(
      "redirect_to",
      request.nextUrl.pathname + request.nextUrl.search
    );
    return NextResponse.redirect(signIn);
  }

  return response;
}

export const config = {
  matcher: [
    // Everything except Next's own assets and anything with a file extension.
    "/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)",
  ],
};
