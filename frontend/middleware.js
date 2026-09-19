import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

const isProtectedRoute = createRouteMatcher([
  '/dashboard(.*)',
  '/onboarding(.*)',
  '/history(.*)',
  '/alerts(.*)',
  '/settings(.*)',
  '/admin(.*)',
]);

export default clerkMiddleware(async (auth, req) => {
  if (!isProtectedRoute(req)) return;

  const { userId } = await auth();
  if (userId) return;

  // Send them to our own sign-in screen, remembering where they were headed so
  // post-auth can drop them back there. `auth.protect()` would bounce them to
  // Clerk's hosted portal instead, and they'd come back to the wrong page.
  const signIn = new URL('/auth', req.url);
  signIn.searchParams.set('redirect_url', req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(signIn);
});

export const config = {
  matcher: ["/((?!.*\\..*|_next).*)", "/", "/(api|trpc)(.*)"],
};
