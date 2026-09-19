import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getSupabase } from "../lib/supabase";

const AuthContext = createContext(null);

/**
 * Flatten a Supabase user into the shape the UI actually asks for.
 *
 * Supabase keeps everything the identity provider sent in `user_metadata`,
 * under whichever key that provider happens to use — Google writes
 * `full_name` and `avatar_url`, the email sign-up form here writes
 * `full_name`, and a bare email/password sign-up writes nothing at all. Doing
 * that lookup once here keeps the `user_metadata?.full_name || user.email`
 * dance out of every component.
 */
function shapeUser(user) {
  if (!user) return null;

  const meta = user.user_metadata || {};
  const fullName = (meta.full_name || meta.name || "").trim();
  const email = user.email || meta.email || "";
  const parts = fullName ? fullName.split(/\s+/) : [];

  const firstName = parts[0] || "";
  const lastName = parts.slice(1).join(" ") || "";
  const initials =
    (firstName && lastName)
      ? `${firstName[0]}${lastName[0]}`.toUpperCase()
      : (fullName || email || "?").slice(0, 2).toUpperCase();

  return {
    id: user.id,
    email,
    fullName,
    firstName,
    lastName,
    initials,
    avatarUrl: meta.avatar_url || meta.picture || null,
    createdAt: user.created_at || null,
    raw: user,
  };
}

export function AuthProvider({ children }) {
  const supabase = useMemo(() => getSupabase(), []);
  const [session, setSession] = useState(null);
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    let active = true;

    // getSession() reads what is already in the cookie, so the first paint
    // does not have to wait on a network round trip. onAuthStateChange then
    // covers everything after: sign-in, sign-out, token refresh, and the
    // session another tab created.
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session ?? null);
      setIsLoaded(true);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => {
      if (!active) return;
      setSession(next ?? null);
      setIsLoaded(true);
    });

    return () => {
      active = false;
      listener?.subscription?.unsubscribe();
    };
  }, [supabase]);

  /**
   * The access token to send to the API, refreshed if it is about to expire.
   *
   * `getSession` does that refresh itself when the stored token is within its
   * expiry window, which is why this is async and why callers must not cache
   * what it returns — an access token lives about an hour.
   */
  const getToken = useCallback(async () => {
    const { data, error } = await supabase.auth.getSession();
    if (error) return null;
    return data.session?.access_token ?? null;
  }, [supabase]);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setSession(null);
  }, [supabase]);

  const value = useMemo(
    () => ({
      supabase,
      session,
      isLoaded,
      isSignedIn: Boolean(session?.user),
      user: shapeUser(session?.user),
      getToken,
      signOut,
    }),
    [supabase, session, isLoaded, getToken, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function useAuthContext() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider> (see pages/_app.js)");
  }
  return ctx;
}

/** Session state and the two actions that need it. */
export function useAuth() {
  const { isLoaded, isSignedIn, getToken, signOut, session } = useAuthContext();
  return { isLoaded, isSignedIn, getToken, signOut, session };
}

/** The signed-in user, already flattened — or null. */
export function useUser() {
  const { user, isLoaded, isSignedIn } = useAuthContext();
  return { user, isLoaded, isSignedIn };
}

/** The raw client, for the auth pages that drive sign-in themselves. */
export function useSupabase() {
  return useAuthContext().supabase;
}
