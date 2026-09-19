import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import { useAuth, useSupabase } from "../contexts/AuthContext";

/**
 * Where the "forgot password" email lands.
 *
 * The recovery link signs the user in with a short-lived session whose only
 * purpose is this form, so there is no old password to ask for — the presence
 * of the session IS the proof. If it is missing the link has expired or was
 * already used, and the only honest thing to offer is a fresh one.
 */
export default function ResetPassword() {
  const router = useRouter();
  const supabase = useSupabase();
  const { isLoaded, isSignedIn } = useAuth();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  // A `code` in the URL means the PKCE recovery flow; exchange it for the
  // session that authorises the update below.
  useEffect(() => {
    if (!router.isReady) return;
    const { code } = router.query;
    if (!code) return;
    supabase.auth.exchangeCodeForSession(String(code)).then(({ error: exchangeError }) => {
      if (exchangeError) setError("This reset link has expired. Request a new one.");
    });
  }, [router.isReady]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Use at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Those two passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const { error: updateError } = await supabase.auth.updateUser({ password });
      if (updateError) throw updateError;
      setDone(true);
      setTimeout(() => router.replace("/dashboard"), 1500);
    } catch (err) {
      setError(err.message || "Could not update your password.");
    } finally {
      setLoading(false);
    }
  };

  const linkIsDead = isLoaded && !isSignedIn && !router.query.code;

  return (
    <>
      <Head>
        <title>Reset Password — Vaulto</title>
      </Head>
      <div className="min-h-screen bg-[var(--bg)] flex items-center justify-center px-5 text-[var(--text)]">
        <div className="reset-card">
          <h1 style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "1.5rem", marginBottom: "0.5rem" }}>
            Choose a new password
          </h1>

          {done ? (
            <p style={{ color: "var(--muted)", fontSize: "0.9rem" }}>
              Password updated. Taking you to your dashboard…
            </p>
          ) : linkIsDead ? (
            <>
              <p style={{ color: "var(--muted)", fontSize: "0.9rem", marginBottom: "1rem" }}>
                This reset link has expired or was already used.
              </p>
              <button className="btn-secondary" style={{ width: "100%", justifyContent: "center" }}
                      onClick={() => router.replace("/auth")}>
                Request a new link
              </button>
            </>
          ) : (
            <form onSubmit={handleSubmit}>
              <div className="field" style={{ marginTop: "1rem" }}>
                <label htmlFor="rp-password">New password</label>
                <input id="rp-password" type="password" value={password} required
                       onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
              </div>
              <div className="field" style={{ marginTop: "1rem" }}>
                <label htmlFor="rp-confirm">Confirm password</label>
                <input id="rp-confirm" type="password" value={confirm} required
                       onChange={(e) => setConfirm(e.target.value)} placeholder="••••••••" />
              </div>
              {error && <div className="error-box">{error}</div>}
              <button type="submit" className="btn-secondary" disabled={loading}
                      style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }}>
                {loading ? "Saving…" : "Update password →"}
              </button>
            </form>
          )}
        </div>
      </div>

      <style jsx>{`
        .reset-card {
          width: 100%;
          max-width: 420px;
          background: var(--surface-float);
          border-radius: var(--radius-xl);
          padding: 2rem;
          box-shadow: var(--shadow-md);
        }
      `}</style>
    </>
  );
}
