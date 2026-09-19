import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/router";
import { useAuth, useUser } from "@clerk/nextjs";
import Head from "next/head";
import { syncUser, checkUserStatus } from "../lib/api";
import { redirectFromQuery, withRedirect } from "../lib/redirect";

/** Clerk needs a tick or two after an OAuth redirect before a token exists. */
async function tokenWithRetry(getToken, attempts = 4) {
  for (let i = 0; i < attempts; i++) {
    try {
      const token = await getToken();
      if (token) return token;
    } catch (_) { /* fall through to the retry */ }
    await new Promise(r => setTimeout(r, 400 * (i + 1)));
  }
  return null;
}

/**
 * Retry the calls that decide where the user lands.
 *
 * A cold backend (Railway spins containers down) answers the first request of
 * the day with a timeout or a 502. Retrying twice costs a couple of seconds;
 * not retrying costs the user their first impression. Client errors — a bad
 * token, a refused account — are returned immediately: they will not improve.
 */
async function withRetry(fn, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const status = err?.status;
      if (status && status >= 400 && status < 500) throw err;
      if (i < attempts - 1) await new Promise(r => setTimeout(r, 600 * (i + 1)));
    }
  }
  throw lastErr;
}

export default function PostAuth() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { isLoaded: userLoaded, user } = useUser();
  const [errorMsg, setErrorMsg] = useState("");
  const [attempt, setAttempt] = useState(0);
  const ran = useRef(false);

  useEffect(() => {
    if (!isLoaded || !userLoaded) return;
    if (!isSignedIn) { router.replace("/auth"); return; }
    // Wait for the user object: syncing with a half-hydrated id used to send
    // an empty clerk_id and get a 403 back.
    if (!user?.id) return;
    if (ran.current) return;
    ran.current = true;

    let cancelled = false;
    const destination = redirectFromQuery(router.query, "/dashboard");

    (async () => {
      try {
        const token = await tokenWithRetry(getToken);
        if (cancelled) return;
        if (!token) {
          setErrorMsg("We couldn't confirm your session. Please sign in again.");
          return;
        }

        await withRetry(() => syncUser(token, {
          clerk_id:  user.id,
          email:     user.primaryEmailAddress?.emailAddress || "",
          full_name: user.fullName || user.username || "",
        }));
        if (cancelled) return;

        const { exists, is_onboarded: isOnboarded } = await withRetry(() => checkUserStatus(token));
        if (cancelled) return;

        if (exists && isOnboarded) router.replace(destination);
        else router.replace(withRedirect("/onboarding", destination));
      } catch (err) {
        if (cancelled) return;
        if (err?.status === 401) {
          setErrorMsg("Your session expired. Please sign in again.");
        } else {
          setErrorMsg(
            err?.message
              ? `We couldn't finish setting up your account: ${err.message}`
              : "We couldn't reach Vaulto just now. Check your connection and try again."
          );
        }
      }
    })();

    return () => { cancelled = true; };
    // `attempt` re-arms the effect when the user hits Retry.
  }, [isLoaded, userLoaded, isSignedIn, user?.id, attempt]);

  const retry = () => {
    ran.current = false;
    setErrorMsg("");
    setAttempt(a => a + 1);
  };

  return (
    <>
      <Head>
        <title>Signing you in… — Vaulto</title>
      </Head>
      <div className="min-h-screen bg-[var(--bg)] flex flex-col items-center justify-center text-[var(--text)]">
        {errorMsg ? (
          <div className="text-center animate-fade-in max-w-md w-full px-5">
            <div className="error-box" role="alert">{errorMsg}</div>
            <div className="flex gap-3 mt-3 justify-center">
              <button onClick={retry} className="btn-secondary" id="post-auth-retry">
                Try again
              </button>
              <button
                onClick={() => router.replace("/auth")}
                className="btn-ghost"
                id="post-auth-signin"
              >
                Back to sign in
              </button>
            </div>
          </div>
        ) : (
          <div className="loading-box animate-pulse-glow">
            <div className="mb-6 flex justify-center logo">
              <span className="logo-mark">V</span><span>Vaulto</span>
            </div>
            <div className="spinner"></div>
            <p className="mt-4 text-[var(--muted)] text-sm tracking-wider uppercase font-semibold">
              Preparing your Vaulto
            </p>
          </div>
        )}
      </div>
    </>
  );
}
