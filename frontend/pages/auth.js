import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import { useAuth, useSupabase } from "../contexts/AuthContext";
import Head from "next/head";
import Link from "next/link";

const MODE_LOGIN = "login";
const MODE_SIGNUP = "signup";
const MODE_FORGOT = "forgot";

function getPasswordStrength(pw) {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  return score;
}

/**
 * Where to land once the session exists.
 *
 * `redirect_to` is set by middleware.js when it turns someone away from a
 * protected page. It is only honoured when it is a path on this site: an
 * absolute URL here would turn the sign-in page into an open redirect, which
 * is a ready-made phishing landing spot.
 */
function safeRedirect(target) {
  if (typeof target !== "string") return null;
  if (!target.startsWith("/") || target.startsWith("//")) return null;
  return target;
}

export default function Auth() {
  const router = useRouter();
  const supabase = useSupabase();
  const { isLoaded: authLoaded, isSignedIn } = useAuth();

  const [mode, setMode] = useState(MODE_LOGIN);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [forgotSent, setForgotSent] = useState(false);

  const redirectTo = safeRedirect(router.query.redirect_to);

  useEffect(() => {
    if (router.query.mode === "signup") setMode(MODE_SIGNUP);
  }, [router.query.mode]);

  useEffect(() => {
    // post-auth decides between /dashboard and /onboarding; it also syncs the
    // user row to the backend, so it must not be skipped on the way in.
    if (authLoaded && isSignedIn) {
      router.replace(redirectTo || "/post-auth");
    }
  }, [authLoaded, isSignedIn, redirectTo]);

  const passwordStrength = getPasswordStrength(password);
  const strengthLabels = ["", "Weak", "Fair", "Good", "Strong"];
  const strengthColors = ["", "#ef4444", "#f59e0b", "#3b82f6", "#10b981"];

  const handleGoogleAuth = async () => {
    setError("");
    try {
      // The browser client uses PKCE, so Google sends the user back with a
      // `code` that only this browser can exchange. /sso-callback does the
      // exchange and then hands off to /post-auth.
      const callback = new URL("/sso-callback", window.location.origin);
      if (redirectTo) callback.searchParams.set("redirect_to", redirectTo);

      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: callback.toString() },
      });
      if (oauthError) throw oauthError;
      // On success the browser is navigating away; nothing to do here.
    } catch (e) {
      setError(e.message || "Google sign-in failed.");
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (signInError) throw signInError;
      // The AuthProvider picks the new session up and the effect above routes;
      // pushing here too would race it.
    } catch (e) {
      setError(e.message || "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = async (e) => {
    e.preventDefault();
    setError("");
    setNotice("");
    setLoading(true);
    try {
      const { data, error: signUpError } = await supabase.auth.signUp({
        email,
        password,
        options: {
          // Stored on the user and read back through useUser().fullName.
          data: { full_name: name.trim() },
          emailRedirectTo: `${window.location.origin}/sso-callback`,
        },
      });
      if (signUpError) throw signUpError;

      // With "Confirm email" on (the Supabase default) no session is returned
      // — the account exists but cannot sign in until the link is clicked.
      // Saying so is the difference between "nothing happened" and "go check
      // your inbox".
      if (!data.session) {
        setNotice(
          `Almost there — we sent a confirmation link to ${email}. ` +
          `Click it to finish creating your account.`
        );
      }
    } catch (e) {
      setError(e.message || "Sign up failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleForgot = async (e) => {
    e.preventDefault();
    if (!email) return;
    setError("");
    setLoading(true);
    try {
      const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (resetError) throw resetError;
      setForgotSent(true);
    } catch (e) {
      setError(e.message || "Failed to send reset email.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Head>
        <title>{mode === MODE_SIGNUP ? "Create Account" : "Log In"} — Vaulto</title>
        <meta name="description" content="Sign in or create your free Vaulto account to save comparisons and set rate alerts." />
      </Head>

      <div className="auth-layout">
        {/* Left brand panel */}
        <div className="auth-left">
          <div className="auth-left-orb orb1" />
          <div className="auth-left-orb orb2" />
          <div className="auth-left-content">
            <Link href="/" className="logo auth-logo">
              <span className="logo-mark">V</span>
              <span>Vaulto</span>
            </Link>
            <h2 className="auth-brand-h2">
              Your money, moving<br />faster than ever.
            </h2>
            <div className="auth-stats">
              {[
                { value: "50K+", label: "Users this month" },
                { value: "3+", label: "Providers compared" },
                { value: "5%", label: "Avg savings" },
              ].map(s => (
                <div key={s.label} className="auth-stat">
                  <div className="auth-stat-val">{s.value}</div>
                  <div className="auth-stat-label">{s.label}</div>
                </div>
              ))}
            </div>
            <ul className="auth-bullets">
              {["Real-time rates from top providers", "Save comparisons & track history", "WhatsApp rate alerts — free"].map(b => (
                <li key={b} className="auth-bullet">
                  <span className="auth-bullet-icon">✓</span>
                  {b}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Right form panel */}
        <div className="auth-right">
          <div className="auth-form-wrap">
            {/* Mode tabs */}
            <div className="auth-tabs">
              {[
                { key: MODE_LOGIN, label: "Log In" },
                { key: MODE_SIGNUP, label: "Sign Up" },
                { key: MODE_FORGOT, label: "Forgot Password" },
              ].map(t => (
                <button
                  key={t.key}
                  className={`auth-tab ${mode === t.key ? "auth-tab-active" : ""}`}
                  onClick={() => { setMode(t.key); setError(""); setNotice(""); setForgotSent(false); }}
                  id={`auth-tab-${t.key}`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="auth-form-card">
              {/* Google OAuth */}
              {mode !== MODE_FORGOT && (
                <>
                  <button
                    className="google-btn"
                    onClick={handleGoogleAuth}
                    disabled={loading}
                    id="auth-google-btn"
                  >
                    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                      <path d="M17.64 9.205c0-.639-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
                      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
                      <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
                      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
                    </svg>
                    Continue with Google
                  </button>
                  <div className="auth-divider"><span>or</span></div>
                </>
              )}

              {/* Login form */}
              {mode === MODE_LOGIN && (
                <form onSubmit={handleLogin}>
                  <div className="field"><label htmlFor="login-email">Email</label>
                    <input id="login-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required /></div>
                  <div className="field" style={{ marginTop: "1rem" }}><label htmlFor="login-password">Password</label>
                    <input id="login-password" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" required /></div>
                  <div style={{ textAlign: "right", marginTop: "0.5rem" }}>
                    <button type="button" onClick={() => setMode(MODE_FORGOT)} className="forgot-link">Forgot password?</button>
                  </div>
                  {error && <div className="error-box">{error}</div>}
                  <button type="submit" className="btn-secondary" style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }} disabled={loading} id="login-submit">
                    {loading ? "Signing in…" : "Sign in →"}
                  </button>
                </form>
              )}

              {/* Sign up form */}
              {mode === MODE_SIGNUP && (
                <form onSubmit={handleSignUp}>
                  <div className="field"><label htmlFor="su-name">Full name</label>
                    <input id="su-name" type="text" value={name} onChange={e => setName(e.target.value)} placeholder="Alex Johnson" required /></div>
                  <div className="field" style={{ marginTop: "1rem" }}><label htmlFor="su-email">Email</label>
                    <input id="su-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required /></div>
                  <div className="field" style={{ marginTop: "1rem" }}>
                    <label htmlFor="su-password">Password</label>
                    <input id="su-password" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" required />
                    {password && (
                      <div className="pw-strength">
                        <div className="pw-bars">
                          {[1,2,3,4].map(n => (
                            <div key={n} className="pw-bar" style={{ background: n <= passwordStrength ? strengthColors[passwordStrength] : "var(--surface-high)" }} />
                          ))}
                        </div>
                        <span style={{ fontSize: "0.7rem", color: strengthColors[passwordStrength] }}>{strengthLabels[passwordStrength]}</span>
                      </div>
                    )}
                  </div>
                  {notice && <div className="notice-box">{notice}</div>}
                  {error && <div className="error-box">{error}</div>}
                  <button type="submit" className="btn-secondary" style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }} disabled={loading} id="signup-submit">
                    {loading ? "Creating account…" : "Create account →"}
                  </button>
                </form>
              )}

              {/* Forgot password */}
              {mode === MODE_FORGOT && (
                forgotSent ? (
                  <div className="forgot-success">
                    <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>📬</div>
                    <h3 style={{ fontFamily: "var(--font-display)", fontWeight: 700 }}>Check your email</h3>
                    <p style={{ color: "var(--muted)", fontSize: "0.875rem", marginTop: "0.5rem" }}>
                      We sent a reset link to {email}. Follow the instructions to reset your password.
                    </p>
                    <button className="btn-ghost" onClick={() => { setMode(MODE_LOGIN); setForgotSent(false); }} style={{ marginTop: "1rem", width: "100%", justifyContent: "center" }}>
                      Back to login
                    </button>
                  </div>
                ) : (
                  <form onSubmit={handleForgot}>
                    <p style={{ color: "var(--text-mid)", fontSize: "0.875rem", marginBottom: "1rem" }}>
                      Enter your email and we'll send you a link to reset your password.
                    </p>
                    <div className="field"><label htmlFor="forgot-email">Email</label>
                      <input id="forgot-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required /></div>
                    {error && <div className="error-box">{error}</div>}
                    <button type="submit" className="btn-secondary" style={{ width: "100%", justifyContent: "center", marginTop: "1rem" }} disabled={loading} id="forgot-submit">
                      {loading ? "Sending…" : "Send Reset Link →"}
                    </button>
                  </form>
                )
              )}

              {/* Footer */}
              <div className="auth-footer-links">
                <span>🔒 256-bit encrypted</span>
                <Link href="#">Privacy</Link>
                <Link href="#">Terms</Link>
                <Link href="#">Security</Link>
              </div>
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .auth-layout {
          display: flex;
          min-height: 100vh;
        }
        .auth-left {
          width: 45%;
          background: var(--primary);
          position: relative;
          overflow: hidden;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 3rem 2.5rem;
        }
        @media (max-width: 768px) { .auth-left { display: none; } }
        .auth-left-orb {
          position: absolute;
          border-radius: 50%;
          pointer-events: none;
        }
        .orb1 {
          width: 400px; height: 400px;
          top: -100px; left: -100px;
          background: radial-gradient(circle, rgba(0,88,190,0.25), transparent 70%);
        }
        .orb2 {
          width: 300px; height: 300px;
          bottom: -80px; right: -60px;
          background: radial-gradient(circle, rgba(16,185,129,0.15), transparent 70%);
        }
        .auth-left-content { position: relative; z-index: 1; max-width: 380px; }
        .auth-logo { color: white !important; margin-bottom: 2.5rem; display: inline-flex; }
        .auth-brand-h2 {
          font-family: var(--font-display);
          font-size: clamp(1.8rem, 3vw, 2.4rem);
          font-weight: 800; letter-spacing: -0.04em;
          color: white; line-height: 1.1; margin-bottom: 2rem;
        }
        .auth-stats { display: flex; gap: 1.5rem; margin-bottom: 2rem; }
        .auth-stat-val { font-family: var(--font-display); font-size: 1.6rem; font-weight: 800; color: white; }
        .auth-stat-label { font-size: 0.75rem; color: rgba(255,255,255,0.5); margin-top: 0.1rem; }
        .auth-bullets { list-style: none; display: flex; flex-direction: column; gap: 0.75rem; }
        .auth-bullet { display: flex; align-items: center; gap: 0.75rem; font-size: 0.9rem; color: rgba(255,255,255,0.7); }
        .auth-bullet-icon { color: var(--tertiary); font-weight: 700; }

        .auth-right {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 2rem;
          background: var(--bg);
        }
        .auth-form-wrap { width: 100%; max-width: 440px; }

        .auth-tabs {
          display: flex;
          border-bottom: 1px solid var(--surface-high);
          margin-bottom: 1.5rem;
          gap: 0.25rem;
        }
        .auth-tab {
          padding: 0.6rem 0.9rem;
          background: none; border: none;
          font-family: var(--font-body); font-size: 0.875rem; font-weight: 500;
          color: var(--muted); cursor: pointer;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
          transition: color 0.15s, border-color 0.15s;
        }
        .auth-tab:hover { color: var(--text); }
        .auth-tab-active { color: var(--secondary) !important; border-bottom-color: var(--secondary); }

        .auth-form-card {
          background: var(--surface-float);
          border-radius: var(--radius-xl);
          padding: 2rem;
          box-shadow: var(--shadow-md);
        }

        .google-btn {
          width: 100%;
          display: flex; align-items: center; justify-content: center; gap: 0.75rem;
          background: white; border: 1px solid var(--outline);
          border-radius: var(--radius-md); padding: 0.8rem 1.25rem;
          font-family: var(--font-body); font-size: 0.95rem; font-weight: 600;
          color: var(--text); cursor: pointer;
          box-shadow: var(--shadow-sm);
          transition: box-shadow 0.15s, border-color 0.15s;
        }
        .google-btn:hover:not(:disabled) { box-shadow: var(--shadow-md); border-color: var(--outline-strong); }
        .google-btn:disabled { opacity: 0.5; cursor: not-allowed; }

        .auth-divider {
          display: flex; align-items: center; gap: 1rem;
          margin: 1.25rem 0; color: var(--muted); font-size: 0.8rem;
        }
        .auth-divider::before, .auth-divider::after { content: ""; flex: 1; height: 1px; background: var(--surface-high); }

        .forgot-link { background: none; border: none; color: var(--secondary); font-size: 0.8rem; cursor: pointer; font-family: var(--font-body); }
        .forgot-link:hover { text-decoration: underline; }

        .pw-strength { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; }
        .pw-bars { display: flex; gap: 3px; }
        .pw-bar { width: 30px; height: 3px; border-radius: 2px; transition: background 0.3s; }

        .forgot-success { text-align: center; padding: 1rem 0; }

        .notice-box {
          margin-top: 1rem;
          padding: 0.75rem 1rem;
          border-radius: var(--radius-md);
          background: rgba(16, 185, 129, 0.1);
          border: 1px solid rgba(16, 185, 129, 0.35);
          color: var(--text);
          font-size: 0.85rem;
          line-height: 1.5;
        }

        .auth-footer-links {
          display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
          margin-top: 1.5rem; justify-content: center;
          font-size: 0.75rem; color: var(--muted);
        }
        .auth-footer-links a { color: var(--muted); text-decoration: none; }
        .auth-footer-links a:hover { color: var(--text-mid); }
      `}</style>
    </>
  );
}
