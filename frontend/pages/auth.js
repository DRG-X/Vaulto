import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/router";
import { useAuth, useSupabase } from "../contexts/AuthContext";
import Head from "next/head";
import Link from "next/link";
import { redirectFromQuery, withRedirect } from "../lib/redirect";

const MODE_LOGIN  = "login";
const MODE_SIGNUP = "signup";
const MODE_FORGOT = "forgot";

// Sub-steps inside a mode. Every one of these used to be a dead end: the code
// was sent, and the screen had nowhere to type it.
const STEP_FORM    = "form";        // email + password
const STEP_VERIFY  = "verify";      // sign-up: confirm the emailed code
const STEP_RESET   = "reset";       // forgot: emailed code + new password
const STEP_FACTOR  = "factor";      // sign-in: emailed code (passwordless)
const STEP_2FA     = "2fa";         // sign-in: the enrolled MFA factor

const RESEND_SECONDS = 30;

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
 * Turn a Supabase auth error into something a person can act on.
 *
 * GoTrue's raw messages are accurate and unhelpful ("Invalid login
 * credentials"), and the default here used to be a flat "Login failed." that
 * told the user nothing about what to do next. `error.code` is the stable
 * handle — the message text is not, so it is only ever the last resort.
 */
function readAuthError(e, fallback) {
  const code = e?.code || e?.error_code;
  switch (code) {
    case "invalid_credentials":
      return "That email and password don't match an account. Try again, or reset your password.";
    case "user_not_found":
      return "We couldn't find an account with that email. Try signing up instead.";
    case "email_not_confirmed":
      return "Your email isn't confirmed yet. Enter the code we just sent to finish.";
    case "user_already_exists":
    case "email_exists":
      return "An account with this email already exists — log in instead.";
    case "weak_password":
      return "That password is too easy to guess. Mix in another word, number or symbol.";
    case "same_password":
      return "That's the password you already have. Pick a different one.";
    case "otp_expired":
      return "That code has expired. Send a new one and try again.";
    case "otp_disabled":
      return "Email codes are turned off for this project. Use your password instead.";
    case "over_email_send_rate_limit":
      return "We've sent a few emails already. Wait a minute, then ask for another.";
    case "over_request_rate_limit":
    case "too_many_requests":
      return "Too many attempts. Wait a minute, then try again.";
    case "signup_disabled":
      return "New accounts are closed at the moment. Please try again later.";
    case "provider_disabled":
    case "oauth_provider_not_supported":
      return "That sign-in method isn't enabled. Use your email and password instead.";
    case "validation_failed":
      return "That email doesn't look right. Check it and try again.";
    case "captcha_failed":
      return "We couldn't complete the security check. Reload the page and try again.";
    case "mfa_verification_failed":
      return "That code isn't right. Check the digits, or wait for the next one.";
    case "mfa_challenge_expired":
      return "That two-step prompt expired. Sign in again to get a new one.";
    default:
      break;
  }
  // A 422 from GoTrue on a sign-up is almost always the password rule.
  if (e?.status === 422 && /password/i.test(e?.message || "")) {
    return "Passwords need to be at least 8 characters.";
  }
  return e?.message || fallback;
}

export default function Auth() {
  const router = useRouter();
  const supabase = useSupabase();
  const { isLoaded: authLoaded, isSignedIn } = useAuth();

  const [mode, setMode] = useState(MODE_LOGIN);
  const [step, setStep] = useState(STEP_FORM);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [secondFactor, setSecondFactor] = useState(null);   // { factorId, challengeId, label, isPhone }
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [resendIn, setResendIn] = useState(0);

  // Set once we have a session and are on our way out. Without it, the
  // "already signed in" effect below races the redirect we just started and
  // can win — which is how a fresh sign-up used to land on /dashboard with no
  // account row behind it, skipping onboarding entirely.
  const leaving = useRef(false);

  // Set for as long as THIS page is driving a flow. A password sign-in against
  // an account with two-step verification creates a real (aal1) session before
  // the second factor is asked for, so the effect below would see
  // `isSignedIn` and redirect straight past the prompt. While we are driving,
  // only the handlers decide when to leave.
  const driving = useRef(false);

  const destination = redirectFromQuery(router.query, "/dashboard");
  const postAuthUrl = withRedirect("/post-auth", destination);

  useEffect(() => {
    if (router.query.mode === "signup") setMode(MODE_SIGNUP);
    else if (router.query.mode === "login") setMode(MODE_LOGIN);
  }, [router.query.mode]);

  // Already signed in (came back to /auth with a live session)? There is
  // nothing to do here — post-auth decides between onboarding and dashboard.
  useEffect(() => {
    if (authLoaded && isSignedIn && !leaving.current && !driving.current) {
      leaving.current = true;
      router.replace(postAuthUrl);
    }
  }, [authLoaded, isSignedIn, postAuthUrl]);

  // Resend cooldown
  useEffect(() => {
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn(s => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  const finish = useCallback(() => {
    leaving.current = true;
    router.replace(postAuthUrl);
  }, [router, postAuthUrl]);

  const emailRedirectTo = () =>
    typeof window === "undefined"
      ? undefined
      : new URL(withRedirect("/sso-callback", destination), window.location.origin).toString();

  const switchMode = (next) => {
    setMode(next);
    setStep(STEP_FORM);
    setError("");
    setNotice("");
    setCode("");
    setNewPassword("");
    setSecondFactor(null);
    driving.current = false;
  };

  const passwordStrength = getPasswordStrength(mode === MODE_FORGOT ? newPassword : password);
  const strengthLabels = ["", "Weak", "Fair", "Good", "Strong"];
  const strengthColors = ["", "#ef4444", "#f59e0b", "#3b82f6", "#10b981"];
  const busy = loading || googleLoading;

  /**
   * Ask for the enrolled second factor, if this session still owes one.
   *
   * Supabase grades a session's assurance level: a password gets you `aal1`,
   * and an account with a verified factor needs `aal2`. The gap between them is
   * exactly "signed in, but not all the way", and it is what this step closes.
   * Returns true when a prompt is now on screen.
   */
  const beginSecondFactor = async () => {
    const { data: aal, error: aalError } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    if (aalError) throw aalError;
    if (!aal || aal.nextLevel !== "aal2" || aal.nextLevel === aal.currentLevel) return false;

    const { data: factorData, error: listError } = await supabase.auth.mfa.listFactors();
    if (listError) throw listError;
    const factors = factorData?.all || factorData?.totp || [];
    const factor = factors.find(f => f.status === "verified") || factors[0];
    // An account that owes aal2 with nothing to challenge cannot be rescued
    // from this screen; letting it through beats stranding it here.
    if (!factor) return false;

    const { data: challenge, error: challengeError } =
      await supabase.auth.mfa.challenge({ factorId: factor.id });
    if (challengeError) throw challengeError;

    const isPhone = factor.factor_type === "phone";
    setSecondFactor({
      factorId: factor.id,
      challengeId: challenge.id,
      isPhone,
      label: isPhone
        ? "We texted a code to your phone."
        : "Enter the code from your authenticator app.",
    });
    setStep(STEP_2FA);
    setNotice("");
    return true;
  };

  /** A session exists — go on to the second factor, or leave. */
  const completeSession = async () => {
    if (await beginSecondFactor()) return;
    finish();
  };

  // ── Google ────────────────────────────────────────────────────────────────
  const handleGoogleAuth = async () => {
    setError("");
    setGoogleLoading(true);
    driving.current = true;
    try {
      // The browser client uses PKCE, so Google sends the user back with a
      // `code` that only this browser can exchange. /sso-callback does the
      // exchange and then hands off to /post-auth.
      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: emailRedirectTo() },
      });
      if (oauthError) throw oauthError;
      // On success the browser is navigating away; nothing to do here.
    } catch (e) {
      driving.current = false;
      setGoogleLoading(false);
      setError(readAuthError(e, "Google sign-in failed. Please try again."));
    }
  };

  // ── Sign-in ───────────────────────────────────────────────────────────────
  const handleLogin = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    setNotice("");
    setLoading(true);
    driving.current = true;
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (signInError) throw signInError;
      await completeSession();
    } catch (err) {
      driving.current = false;
      // The account exists but its email was never confirmed. Send the code
      // and show the box for it, rather than reporting a dead end.
      if (err?.code === "email_not_confirmed") {
        try {
          await supabase.auth.resend({
            type: "signup",
            email: email.trim(),
            options: { emailRedirectTo: emailRedirectTo() },
          });
          setStep(STEP_VERIFY);
          setMode(MODE_SIGNUP);
          setNotice(`Your email isn't confirmed yet — we sent a new code to ${email.trim()}.`);
          setResendIn(RESEND_SECONDS);
          return;
        } catch (resendErr) {
          setError(readAuthError(resendErr, "Your email isn't confirmed yet."));
          return;
        }
      }
      setError(readAuthError(err, "We couldn't sign you in. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  /** Passwordless: email a one-time code instead of asking for the password. */
  const handleEmailCode = async () => {
    if (loading || !email.trim()) {
      setError("Enter your email first, and we'll send you a code.");
      return;
    }
    setError("");
    setNotice("");
    setLoading(true);
    try {
      const { error: otpError } = await supabase.auth.signInWithOtp({
        email: email.trim(),
        // This is the sign-IN path: an unknown address should be told so, not
        // quietly turned into a half-finished account.
        options: { shouldCreateUser: false, emailRedirectTo: emailRedirectTo() },
      });
      if (otpError) throw otpError;
      setStep(STEP_FACTOR);
      setNotice(`We sent a 6-digit code to ${email.trim()}.`);
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      setError(readAuthError(err, "We couldn't send a code. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleFirstFactorCode = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    setLoading(true);
    driving.current = true;
    try {
      const { error: verifyError } = await supabase.auth.verifyOtp({
        email: email.trim(),
        token: code.trim(),
        type: "email",
      });
      if (verifyError) throw verifyError;
      await completeSession();
    } catch (err) {
      driving.current = false;
      setError(readAuthError(err, "That code isn't right. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleSecondFactor = async (e) => {
    e.preventDefault();
    if (loading || !secondFactor) return;
    setError("");
    setLoading(true);
    try {
      const { error: verifyError } = await supabase.auth.mfa.verify({
        factorId: secondFactor.factorId,
        challengeId: secondFactor.challengeId,
        code: code.trim(),
      });
      if (verifyError) throw verifyError;
      finish();
    } catch (err) {
      setError(readAuthError(err, "That code isn't right. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  // ── Sign-up ───────────────────────────────────────────────────────────────
  const handleSignUp = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    setNotice("");

    if (password.length < 8) {
      setError("Passwords need to be at least 8 characters.");
      return;
    }

    setLoading(true);
    driving.current = true;
    try {
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: email.trim(),
        password,
        options: {
          // Stored on the user and read back through useUser().fullName.
          data: { full_name: name.trim() },
          emailRedirectTo: emailRedirectTo(),
        },
      });
      if (signUpError) throw signUpError;

      // Supabase will not admit that an address is already taken — it returns
      // a user with no identities instead, to stop the form being used to
      // enumerate accounts. That shape is the only signal we get.
      if (data?.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
        driving.current = false;
        setMode(MODE_LOGIN);
        setStep(STEP_FORM);
        setError("You already have an account with this email — sign in below.");
        return;
      }

      // Email confirmation off: the session is live and we are done.
      if (data?.session) {
        await completeSession();
        return;
      }

      // The normal path for a project that confirms email: show the box to
      // type the code into. This is the step that was missing — sign-up
      // simply stopped here with "check your email".
      driving.current = false;
      setStep(STEP_VERIFY);
      setNotice(`We sent a 6-digit code to ${email.trim()}.`);
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      driving.current = false;
      setError(readAuthError(err, "We couldn't create your account. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyEmail = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    setLoading(true);
    driving.current = true;
    try {
      const { error: verifyError } = await supabase.auth.verifyOtp({
        email: email.trim(),
        token: code.trim(),
        type: "signup",
      });
      if (verifyError) throw verifyError;
      await completeSession();
    } catch (err) {
      driving.current = false;
      setError(readAuthError(err, "That code isn't right. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (resendIn > 0 || loading) return;
    setError("");
    setLoading(true);
    try {
      if (step === STEP_VERIFY) {
        const { error: resendError } = await supabase.auth.resend({
          type: "signup",
          email: email.trim(),
          options: { emailRedirectTo: emailRedirectTo() },
        });
        if (resendError) throw resendError;
      } else if (step === STEP_RESET) {
        const { error: resetError } = await supabase.auth.resetPasswordForEmail(email.trim(), {
          redirectTo: `${window.location.origin}/reset-password`,
        });
        if (resetError) throw resetError;
      } else {
        const { error: otpError } = await supabase.auth.signInWithOtp({
          email: email.trim(),
          options: { shouldCreateUser: false, emailRedirectTo: emailRedirectTo() },
        });
        if (otpError) throw otpError;
      }
      setNotice(`We sent a new code to ${email.trim()}.`);
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      setError(readAuthError(err, "We couldn't send another code just yet."));
    } finally {
      setLoading(false);
    }
  };

  // ── Forgot password ───────────────────────────────────────────────────────
  const handleForgot = async (e) => {
    e.preventDefault();
    if (loading || !email.trim()) return;
    setError("");
    setNotice("");
    setLoading(true);
    try {
      // The recovery email carries both a link and a code. The link lands on
      // /reset-password; the code is typed in on the next step here, so
      // whichever one the user reaches for works.
      const { error: resetError } = await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (resetError) throw resetError;
      setStep(STEP_RESET);
      setNotice(`We sent a 6-digit code to ${email.trim()}.`);
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      setError(readAuthError(err, "We couldn't send a reset code. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");

    if (newPassword.length < 8) {
      setError("Your new password needs to be at least 8 characters.");
      return;
    }

    setLoading(true);
    driving.current = true;
    try {
      // The code buys a session; that session is what authorises the change.
      const { error: verifyError } = await supabase.auth.verifyOtp({
        email: email.trim(),
        token: code.trim(),
        type: "recovery",
      });
      if (verifyError) throw verifyError;

      const { error: updateError } = await supabase.auth.updateUser({ password: newPassword });
      if (updateError) throw updateError;

      await completeSession();
    } catch (err) {
      driving.current = false;
      setError(readAuthError(err, "We couldn't reset your password. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  // ── Shared pieces ─────────────────────────────────────────────────────────
  // A recovery or authenticator code is always six digits here, so the box is
  // digits-only — pasting a formatted code still lands correctly.
  const codeField = (labelId) => (
    <div className="field">
      <label htmlFor={labelId}>6-digit code</label>
      <input
        id={labelId}
        className="code-input"
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        value={code}
        onChange={e => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
        placeholder="123456"
        required
        autoFocus
      />
    </div>
  );

  const codeIncomplete = code.length < 6;

  const resendRow = (
    <div className="resend-row">
      <span>Didn&rsquo;t get it?</span>
      <button type="button" onClick={handleResend} disabled={resendIn > 0 || loading} className="forgot-link">
        {resendIn > 0 ? `Resend in ${resendIn}s` : "Send a new code"}
      </button>
    </div>
  );

  const feedback = (
    <>
      {notice && <div className="notice-box" role="status">{notice}</div>}
      {error && <div className="error-box" role="alert">{error}</div>}
    </>
  );

  const heading =
    step === STEP_VERIFY ? "Verify your email"
    : step === STEP_RESET ? "Choose a new password"
    : step === STEP_FACTOR ? "Check your email"
    : step === STEP_2FA ? "Two-step verification"
    : null;

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
                  onClick={() => switchMode(t.key)}
                  disabled={busy}
                  id={`auth-tab-${t.key}`}
                  type="button"
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div className="auth-form-card">
              {heading && <h3 className="auth-step-title">{heading}</h3>}

              {/* Google OAuth — only on the first step of login/signup */}
              {step === STEP_FORM && mode !== MODE_FORGOT && (
                <>
                  <button
                    className="google-btn"
                    onClick={handleGoogleAuth}
                    disabled={busy}
                    id="auth-google-btn"
                    type="button"
                  >
                    <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                      <path d="M17.64 9.205c0-.639-.057-1.252-.164-1.841H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4"/>
                      <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z" fill="#34A853"/>
                      <path d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
                      <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
                    </svg>
                    {googleLoading ? "Opening Google…" : "Continue with Google"}
                  </button>
                  <div className="auth-divider"><span>or</span></div>
                </>
              )}

              {/* ── Login ── */}
              {mode === MODE_LOGIN && step === STEP_FORM && (
                <form onSubmit={handleLogin}>
                  <div className="field">
                    <label htmlFor="login-email">Email</label>
                    <input id="login-email" type="email" autoComplete="email" value={email}
                           onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required />
                  </div>
                  <div className="field" style={{ marginTop: "1rem" }}>
                    <label htmlFor="login-password">Password</label>
                    <div className="pw-wrap">
                      <input id="login-password" type={showPassword ? "text" : "password"}
                             autoComplete="current-password" value={password}
                             onChange={e => setPassword(e.target.value)} placeholder="••••••••" required />
                      <button type="button" className="pw-toggle" onClick={() => setShowPassword(v => !v)}
                              aria-label={showPassword ? "Hide password" : "Show password"}>
                        {showPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                  </div>
                  <div style={{ textAlign: "right", marginTop: "0.5rem" }}>
                    <button type="button" onClick={() => switchMode(MODE_FORGOT)} className="forgot-link">
                      Forgot password?
                    </button>
                  </div>
                  {feedback}
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy} id="login-submit">
                    {loading ? "Signing in…" : "Sign in →"}
                  </button>
                  <p className="auth-swap">
                    <button type="button" className="forgot-link" onClick={handleEmailCode} disabled={busy} id="login-email-code">
                      Email me a code instead
                    </button>
                  </p>
                  <p className="auth-swap">
                    New to Vaulto?{" "}
                    <button type="button" className="forgot-link" onClick={() => switchMode(MODE_SIGNUP)}>
                      Create an account
                    </button>
                  </p>
                </form>
              )}

              {/* ── Sign up ── */}
              {mode === MODE_SIGNUP && step === STEP_FORM && (
                <form onSubmit={handleSignUp}>
                  <div className="field">
                    <label htmlFor="su-name">Full name</label>
                    <input id="su-name" type="text" autoComplete="name" value={name}
                           onChange={e => setName(e.target.value)} placeholder="Alex Johnson" required />
                  </div>
                  <div className="field" style={{ marginTop: "1rem" }}>
                    <label htmlFor="su-email">Email</label>
                    <input id="su-email" type="email" autoComplete="email" value={email}
                           onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required />
                  </div>
                  <div className="field" style={{ marginTop: "1rem" }}>
                    <label htmlFor="su-password">Password</label>
                    <div className="pw-wrap">
                      <input id="su-password" type={showPassword ? "text" : "password"}
                             autoComplete="new-password" minLength={8} value={password}
                             onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" required />
                      <button type="button" className="pw-toggle" onClick={() => setShowPassword(v => !v)}
                              aria-label={showPassword ? "Hide password" : "Show password"}>
                        {showPassword ? "Hide" : "Show"}
                      </button>
                    </div>
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
                  {feedback}
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy} id="signup-submit">
                    {loading ? "Creating account…" : "Create account →"}
                  </button>
                  <p className="auth-swap">
                    Already have an account?{" "}
                    <button type="button" className="forgot-link" onClick={() => switchMode(MODE_LOGIN)}>
                      Log in
                    </button>
                  </p>
                </form>
              )}

              {/* ── Sign up: email verification ── */}
              {mode === MODE_SIGNUP && step === STEP_VERIFY && (
                <form onSubmit={handleVerifyEmail}>
                  <p className="auth-step-copy">
                    Enter the code we emailed you to finish creating your account —
                    or just click the link in that email.
                  </p>
                  {codeField("verify-code")}
                  {feedback}
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy || codeIncomplete} id="verify-submit">
                    {loading ? "Verifying…" : "Verify email →"}
                  </button>
                  {resendRow}
                  <button type="button" className="btn-ghost auth-back" onClick={() => switchMode(MODE_SIGNUP)}>
                    ← Use a different email
                  </button>
                </form>
              )}

              {/* ── Login: emailed code (passwordless) ── */}
              {mode === MODE_LOGIN && step === STEP_FACTOR && (
                <form onSubmit={handleFirstFactorCode}>
                  <p className="auth-step-copy">Enter the code we emailed you to continue.</p>
                  {codeField("factor-code")}
                  {feedback}
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy || codeIncomplete} id="factor-submit">
                    {loading ? "Checking…" : "Continue →"}
                  </button>
                  {resendRow}
                  <button type="button" className="btn-ghost auth-back" onClick={() => switchMode(MODE_LOGIN)}>
                    ← Back to login
                  </button>
                </form>
              )}

              {/* ── Login: second factor ── */}
              {step === STEP_2FA && (
                <form onSubmit={handleSecondFactor}>
                  <p className="auth-step-copy">{secondFactor?.label}</p>
                  {codeField("twofa-code")}
                  {feedback}
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy || codeIncomplete} id="twofa-submit">
                    {loading ? "Checking…" : "Verify →"}
                  </button>
                  <button type="button" className="btn-ghost auth-back" onClick={() => switchMode(MODE_LOGIN)}>
                    ← Back to login
                  </button>
                </form>
              )}

              {/* ── Forgot: ask for the email ── */}
              {mode === MODE_FORGOT && step === STEP_FORM && (
                <form onSubmit={handleForgot}>
                  <p className="auth-step-copy">
                    Enter your email and we&rsquo;ll send you a code to set a new password.
                  </p>
                  <div className="field">
                    <label htmlFor="forgot-email">Email</label>
                    <input id="forgot-email" type="email" autoComplete="email" value={email}
                           onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required />
                  </div>
                  {feedback}
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy} id="forgot-submit">
                    {loading ? "Sending…" : "Send reset code →"}
                  </button>
                  <button type="button" className="btn-ghost auth-back" onClick={() => switchMode(MODE_LOGIN)}>
                    ← Back to login
                  </button>
                </form>
              )}

              {/* ── Forgot: code + new password ── */}
              {mode === MODE_FORGOT && step === STEP_RESET && (
                <form onSubmit={handleReset}>
                  <p className="auth-step-copy">
                    Enter the code we emailed you and pick a new password.
                  </p>
                  {codeField("reset-code")}
                  <div className="field" style={{ marginTop: "1rem" }}>
                    <label htmlFor="reset-password">New password</label>
                    <div className="pw-wrap">
                      <input id="reset-password" type={showPassword ? "text" : "password"}
                             autoComplete="new-password" minLength={8} value={newPassword}
                             onChange={e => setNewPassword(e.target.value)}
                             placeholder="At least 8 characters" required />
                      <button type="button" className="pw-toggle" onClick={() => setShowPassword(v => !v)}
                              aria-label={showPassword ? "Hide password" : "Show password"}>
                        {showPassword ? "Hide" : "Show"}
                      </button>
                    </div>
                    {newPassword && (
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
                  {feedback}
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy || codeIncomplete} id="reset-submit">
                    {loading ? "Saving…" : "Set new password →"}
                  </button>
                  {resendRow}
                  <button type="button" className="btn-ghost auth-back" onClick={() => switchMode(MODE_LOGIN)}>
                    ← Back to login
                  </button>
                </form>
              )}

              {/* Footer */}
              <div className="auth-footer-links">
                <span>🔒 256-bit encrypted</span>
                <Link href="/privacy">Privacy</Link>
                <Link href="/terms">Terms</Link>
                <Link href="/cookies">Cookies</Link>
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
        .auth-tab:disabled { opacity: 0.6; cursor: not-allowed; }
        .auth-tab-active { color: var(--secondary) !important; border-bottom-color: var(--secondary); }

        .auth-form-card {
          background: var(--surface-float);
          border-radius: var(--radius-xl);
          padding: 2rem;
          box-shadow: var(--shadow-md);
        }

        .auth-step-title {
          font-family: var(--font-display);
          font-size: 1.15rem; font-weight: 800;
          letter-spacing: -0.02em;
          margin-bottom: 0.35rem;
        }
        .auth-step-copy {
          color: var(--text-mid); font-size: 0.875rem;
          line-height: 1.5; margin-bottom: 1.25rem;
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

        .auth-submit {
          width: 100%; justify-content: center; margin-top: 1rem;
        }
        .auth-back {
          width: 100%; justify-content: center; margin-top: 0.75rem;
        }
        .auth-swap {
          text-align: center; margin-top: 1rem;
          font-size: 0.8rem; color: var(--muted);
        }

        .forgot-link { background: none; border: none; color: var(--secondary); font-size: 0.8rem; cursor: pointer; font-family: var(--font-body); }
        .forgot-link:hover:not(:disabled) { text-decoration: underline; }
        .forgot-link:disabled { color: var(--muted); cursor: not-allowed; }

        .pw-wrap { position: relative; display: flex; }
        .pw-wrap input { width: 100%; padding-right: 3.75rem; }
        .pw-toggle {
          position: absolute; right: 0.6rem; top: 50%; transform: translateY(-50%);
          background: none; border: none; cursor: pointer;
          font-family: var(--font-body); font-size: 0.75rem; font-weight: 600;
          color: var(--muted);
        }
        .pw-toggle:hover { color: var(--text); }

        .pw-strength { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; }
        .pw-bars { display: flex; gap: 3px; }
        .pw-bar { width: 30px; height: 3px; border-radius: 2px; transition: background 0.3s; }

        .code-input {
          font-family: var(--font-display);
          font-size: 1.5rem; font-weight: 700;
          letter-spacing: 0.4em; text-align: center;
        }

        .resend-row {
          display: flex; align-items: center; justify-content: center; gap: 0.4rem;
          margin-top: 0.9rem; font-size: 0.8rem; color: var(--muted);
        }

        .notice-box {
          background: var(--tertiary-dim);
          color: var(--tertiary);
          border-radius: var(--radius-md);
          padding: 0.7rem 0.9rem;
          font-size: 0.8rem;
          margin-top: 1rem;
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
