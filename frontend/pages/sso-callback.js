import Head from "next/head";
import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";

/**
 * Where Google drops the user back. Clerk finishes creating the session here,
 * then hands off to /post-auth.
 *
 * It must be /post-auth and not /dashboard: post-auth is what creates the user
 * row and decides between onboarding and the dashboard. Sending OAuth users
 * straight to /dashboard skipped both, so a brand-new Google sign-up landed on
 * a dashboard with no profile behind it.
 */
export default function SSOCallback() {
  return (
    <>
      <Head>
        <title>Signing you in… — Vaulto</title>
      </Head>

      <div className="min-h-screen bg-[var(--bg)] flex flex-col items-center justify-center text-[var(--text)]">
        <div className="loading-box animate-pulse-glow">
          <div className="mb-6 flex justify-center logo">
            <span className="logo-mark">V</span><span>Vaulto</span>
          </div>
          <div className="spinner"></div>
          <p className="mt-4 text-[var(--muted)] text-sm tracking-wider uppercase font-semibold">
            Signing you in
          </p>
        </div>
      </div>

      {/* Only fallbacks, deliberately: a forced URL overrides the
          `redirectUrlComplete` the sign-in page set, which is what carries the
          "take me back to the comparison I was looking at" path. */}
      <AuthenticateWithRedirectCallback
        signInFallbackRedirectUrl="/post-auth"
        signUpFallbackRedirectUrl="/post-auth"
        continueSignUpUrl="/auth?mode=signup"
      />
    </>
  );
}
