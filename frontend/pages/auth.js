import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/router";
import { useSignIn, useSignUp, useAuth } from "@clerk/nextjs";
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
const STEP_2FA     = "2fa";         // sign-in: TOTP / SMS / backup code

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
 * Turn a Clerk error into something a person can act on.
 *
 * Clerk's raw messages are accurate and unhelpful ("Identifier is invalid"),
 * and the default here used to be a flat "Login failed." that told the user
 * nothing about what to do next.
 */
function readClerkError(e, fallback) {
  const first = e?.errors?.[0];
  const code = first?.code;
  switch (code) {
    case "form_identifier_not_found":
      return "We couldn't find an account with that email. Try signing up instead.";
    case "form_password_incorrect":
    case "form_password_validation_failed":
      return "That password doesn't match this account. Try again, or reset it.";
    case "form_identifier_exists":
      return "An account with this email already exists — log in instead.";
    case "form_password_pwned":
      return "That password has appeared in a data breach. Please pick a different one.";
    case "form_password_length_too_short":
      return "Passwords need to be at least 8 characters.";
    case "form_param_format_invalid":
      return "That email doesn't look right. Check it and try again.";
    case "form_code_incorrect":
    case "verification_failed":
    case "form_param_nil":
      return "That code isn't right. Check the digits, or send a new one.";
    case "verification_expired":
      return "That code has expired. Send a new one and try again.";
    case "too_many_requests":
    case "rate_limit_exceeded":
      return "Too many attempts. Wait a minute, then try again.";
    case "captcha_invalid":
    case "captcha_unavailable":
      return "We couldn't complete the security check. Reload the page and try again.";
    default:
      return first?.longMessage || first?.message || fallback;
  }
}

export default function Auth() {
  const router = useRouter();
  const { isLoaded: authLoaded, isSignedIn } = useAuth();
  const { isLoaded: signInLoaded, signIn, setActive: setSignInActive } = useSignIn();
  const { isLoaded: signUpLoaded, signUp, setActive: setSignUpActive } = useSignUp();

  const [mode, setMode] = useState(MODE_LOGIN);
  const [step, setStep] = useState(STEP_FORM);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [secondFactor, setSecondFactor] = useState(null);   // { strategy, label }
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

  const destination = redirectFromQuery(router.query, "/dashboard");
  const postAuthUrl = withRedirect("/post-auth", destination);

  useEffect(() => {
    if (router.query.mode === "signup") setMode(MODE_SIGNUP);
    else if (router.query.mode === "login") setMode(MODE_LOGIN);
  }, [router.query.mode]);

  // Already signed in (came back to /auth with a live session)? There is
  // nothing to do here — post-auth decides between onboarding and dashboard.
  useEffect(() => {
    if (authLoaded && isSignedIn && !leaving.current) {
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

  const finish = useCallback(async (setActive, sessionId) => {
    leaving.current = true;
    await setActive({ session: sessionId });
    router.replace(postAuthUrl);
  }, [router, postAuthUrl]);

  const switchMode = (next) => {
    setMode(next);
    setStep(STEP_FORM);
    setError("");
    setNotice("");
    setCode("");
    setNewPassword("");
    setSecondFactor(null);
  };

  const passwordStrength = getPasswordStrength(mode === MODE_FORGOT ? newPassword : password);
  const strengthLabels = ["", "Weak", "Fair", "Good", "Strong"];
  const strengthColors = ["", "#ef4444", "#f59e0b", "#3b82f6", "#10b981"];
  const busy = loading || googleLoading;

  // ── Google ────────────────────────────────────────────────────────────────
  const handleGoogleAuth = async () => {
    setError("");
    // The button used to be live before Clerk had loaded, and clicking it
    // threw on `undefined.authenticateWithRedirect`.
    if (!signInLoaded || !signUpLoaded) return;
    setGoogleLoading(true);
    try {
      const method = mode === MODE_SIGNUP ? signUp : signIn;
      await method.authenticateWithRedirect({
        strategy: "oauth_google",
        redirectUrl: "/sso-callback",
        redirectUrlComplete: postAuthUrl,
      });
    } catch (e) {
      setGoogleLoading(false);
      setError(readClerkError(e, "Google sign-in failed. Please try again."));
    }
  };

  // ── Sign-in ───────────────────────────────────────────────────────────────
  const routeSignInResult = async (result) => {
    if (result.status === "complete") {
      await finish(setSignInActive, result.createdSessionId);
      return;
    }

    if (result.status === "needs_first_factor") {
      const factors = result.supportedFirstFactors || [];
      const emailCode = factors.find(f => f.strategy === "email_code");
      if (emailCode) {
        await signIn.prepareFirstFactor({
          strategy: "email_code",
          emailAddressId: emailCode.emailAddressId,
        });
        setStep(STEP_FACTOR);
        setNotice(`We sent a 6-digit code to ${email}.`);
        setResendIn(RESEND_SECONDS);
        return;
      }
      if (factors.some(f => f.strategy === "oauth_google")) {
        setError("This account was created with Google — use “Continue with Google” above.");
        return;
      }
      setError("This account needs another way to sign in. Try resetting your password.");
      return;
    }

    if (result.status === "needs_second_factor") {
      const factors = result.supportedSecondFactors || [];
      const totp  = factors.find(f => f.strategy === "totp");
      const phone = factors.find(f => f.strategy === "phone_code");
      if (totp) {
        setSecondFactor({ strategy: "totp", label: "Enter the code from your authenticator app." });
      } else if (phone) {
        await signIn.prepareSecondFactor({ strategy: "phone_code", phoneNumberId: phone.phoneNumberId });
        setSecondFactor({ strategy: "phone_code", label: "We texted a code to your phone." });
      } else {
        setSecondFactor({ strategy: "backup_code", label: "Enter one of your backup codes." });
      }
      setStep(STEP_2FA);
      return;
    }

    if (result.status === "needs_new_password") {
      // Hand them to the reset flow at its FIRST step: no code has been sent
      // yet, so dropping them straight on the "enter your code" screen would
      // strand them with nothing to type.
      setMode(MODE_FORGOT);
      setStep(STEP_FORM);
      setNotice("This account needs a new password. Send yourself a reset code to continue.");
      return;
    }

    setError("We couldn't finish signing you in. Please try again.");
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    if (!signInLoaded || loading) return;
    setError("");
    setNotice("");
    setLoading(true);
    try {
      const result = await signIn.create({ identifier: email.trim(), password });
      await routeSignInResult(result);
    } catch (err) {
      if (err?.errors?.[0]?.code === "session_exists") {
        leaving.current = true;
        router.replace(postAuthUrl);
        return;
      }
      setError(readClerkError(err, "We couldn't sign you in. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleFirstFactorCode = async (e) => {
    e.preventDefault();
    if (!signInLoaded || loading) return;
    setError("");
    setLoading(true);
    try {
      const result = await signIn.attemptFirstFactor({ strategy: "email_code", code: code.trim() });
      await routeSignInResult(result);
    } catch (err) {
      setError(readClerkError(err, "That code isn't right. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleSecondFactor = async (e) => {
    e.preventDefault();
    if (!signInLoaded || loading || !secondFactor) return;
    setError("");
    setLoading(true);
    try {
      const result = await signIn.attemptSecondFactor({
        strategy: secondFactor.strategy,
        code: code.trim(),
      });
      await routeSignInResult(result);
    } catch (err) {
      setError(readClerkError(err, "That code isn't right. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  // ── Sign-up ───────────────────────────────────────────────────────────────
  const handleSignUp = async (e) => {
    e.preventDefault();
    if (!signUpLoaded || loading) return;
    setError("");
    setNotice("");

    if (password.length < 8) {
      setError("Passwords need to be at least 8 characters.");
      return;
    }

    setLoading(true);
    try {
      const parts = name.trim().split(/\s+/);
      const firstName = parts[0] || "";
      const lastName = parts.slice(1).join(" ") || "";
      const result = await signUp.create({
        emailAddress: email.trim(),
        password,
        firstName,
        lastName,
      });

      if (result.status === "complete") {
        await finish(setSignUpActive, result.createdSessionId);
        return;
      }

      // The normal path for a Clerk instance that verifies email: send the
      // code and show the box to type it into. This is the step that was
      // missing — sign-up simply stopped here with "check your email".
      await signUp.prepareEmailAddressVerification({ strategy: "email_code" });
      setStep(STEP_VERIFY);
      setNotice(`We sent a 6-digit code to ${email.trim()}.`);
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      if (err?.errors?.[0]?.code === "form_identifier_exists") {
        setMode(MODE_LOGIN);
        setStep(STEP_FORM);
        setError("You already have an account with this email — sign in below.");
      } else if (err?.errors?.[0]?.code === "session_exists") {
        leaving.current = true;
        router.replace(postAuthUrl);
      } else {
        setError(readClerkError(err, "We couldn't create your account. Please try again."));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyEmail = async (e) => {
    e.preventDefault();
    if (!signUpLoaded || loading) return;
    setError("");
    setLoading(true);
    try {
      const result = await signUp.attemptEmailAddressVerification({ code: code.trim() });
      if (result.status === "complete") {
        await finish(setSignUpActive, result.createdSessionId);
        return;
      }
      const missing = (result.missingFields || []).join(", ");
      setError(
        missing
          ? `Your account still needs: ${missing}. Please contact support.`
          : "We couldn't verify that code. Please request a new one."
      );
    } catch (err) {
      setError(readClerkError(err, "That code isn't right. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (resendIn > 0 || loading) return;
    setError("");
    setLoading(true);
    try {
      if (mode === MODE_SIGNUP) {
        await signUp.prepareEmailAddressVerification({ strategy: "email_code" });
      } else if (mode === MODE_FORGOT) {
        await signIn.create({ strategy: "reset_password_email_code", identifier: email.trim() });
      } else {
        const factors = signIn?.supportedFirstFactors || [];
        const emailCode = factors.find(f => f.strategy === "email_code");
        await signIn.prepareFirstFactor({
          strategy: "email_code",
          emailAddressId: emailCode?.emailAddressId,
        });
      }
      setNotice(`We sent a new code to ${email.trim()}.`);
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      setError(readClerkError(err, "We couldn't send another code just yet."));
    } finally {
      setLoading(false);
    }
  };

  // ── Forgot password ───────────────────────────────────────────────────────
  const handleForgot = async (e) => {
    e.preventDefault();
    if (!signInLoaded || loading || !email.trim()) return;
    setError("");
    setNotice("");
    setLoading(true);
    try {
      await signIn.create({ strategy: "reset_password_email_code", identifier: email.trim() });
      setStep(STEP_RESET);
      setNotice(`We sent a 6-digit code to ${email.trim()}.`);
      setResendIn(RESEND_SECONDS);
    } catch (err) {
      setError(readClerkError(err, "We couldn't send a reset code. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async (e) => {
    e.preventDefault();
    if (!signInLoaded || loading) return;
    setError("");

    if (newPassword.length < 8) {
      setError("Your new password needs to be at least 8 characters.");
      return;
    }

    setLoading(true);
    try {
      const result = await signIn.attemptFirstFactor({
        strategy: "reset_password_email_code",
        code: code.trim(),
        password: newPassword,
      });
      await routeSignInResult(result);
    } catch (err) {
      setError(readClerkError(err, "We couldn't reset your password. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  // ── Shared pieces ─────────────────────────────────────────────────────────
  // Backup codes are alphanumeric and longer than six characters, so the
  // digits-only box would silently eat the one thing a locked-out user has.
  const isBackupCode = step === STEP_2FA && secondFactor?.strategy === "backup_code";

  const codeField = (labelId) => (
    <div className="field">
      <label htmlFor={labelId}>{isBackupCode ? "Backup code" : "6-digit code"}</label>
      <input
        id={labelId}
        className={isBackupCode ? "" : "code-input"}
        type="text"
        inputMode={isBackupCode ? "text" : "numeric"}
        autoComplete="one-time-code"
        maxLength={isBackupCode ? 24 : 6}
        value={code}
        onChange={e => setCode(
          isBackupCode
            ? e.target.value.trim().slice(0, 24)
            : e.target.value.replace(/\D/g, "").slice(0, 6)
        )}
        placeholder={isBackupCode ? "xxxxxxxx" : "123456"}
        required
        autoFocus
      />
    </div>
  );

  const codeIncomplete = isBackupCode ? code.trim().length === 0 : code.length < 6;

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
                    disabled={busy || !signInLoaded || !signUpLoaded}
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
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy || !signInLoaded} id="login-submit">
                    {loading ? "Signing in…" : "Sign in →"}
                  </button>
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
                  {/* Clerk drops its bot-protection widget in here when the
                      instance has it turned on. Without the target element
                      sign-up fails with captcha_unavailable. */}
                  <div id="clerk-captcha" className="clerk-captcha" />
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy || !signUpLoaded} id="signup-submit">
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
                    Enter the code we emailed you to finish creating your account.
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

              {/* ── Login: emailed code (passwordless / extra factor) ── */}
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
                  <button type="submit" className="btn-secondary auth-submit" disabled={busy || !signInLoaded} id="forgot-submit">
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

        .clerk-captcha:empty { display: none; }

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
