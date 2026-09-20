import { useState, useEffect, useMemo, useRef } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import Link from "next/link";
import { useAuth } from "../contexts/AuthContext";
import { COUNTRIES_FULL, currencyForCountry, dialCodeForCountry, universitiesForCountry } from "../lib/countries";
import { CURRENCIES } from "../lib/currencies";
import { completeOnboarding, getMe } from "../lib/api";
import { redirectFromQuery } from "../lib/redirect";
import SearchableDropdown from "../components/SearchableDropdown";

const TOTAL_STEPS = 3;
const STEP_DONE = TOTAL_STEPS + 1;

const stepLabels = ["Corridor", "University", "Alerts"];

const countryItems = COUNTRIES_FULL.map(c => ({ name: c.name, flag: c.flag, code: c.code }));

// ═══════════════════════════════════════════════════════════════════════════════
// Onboarding Page
//
// Three questions, and the first one is the only one that has to be right: the
// corridor. It used to be derived twice from the same answer — the one country
// the user picked set BOTH the send and receive currency — so every user was
// saved as INR -> INR, and every "compare now" link built off that profile led
// to an error page. The corridor now has two ends because it has two ends.
// ═══════════════════════════════════════════════════════════════════════════════
export default function Onboarding() {
  const router = useRouter();
  const { isLoaded, isSignedIn, getToken } = useAuth();

  const [step, setStep] = useState(1);
  const [bootstrapping, setBootstrapping] = useState(true);

  // Step 1 — the corridor
  const [fromCountry, setFromCountry] = useState(null);   // where they live/study
  const [toCountry, setToCountry]     = useState(null);   // where the money goes
  const [fromCurrency, setFromCurrency] = useState("");
  const [toCurrency, setToCurrency]     = useState("");

  // Step 2 — university
  const [university, setUniversity] = useState(null);     // { name, city? }
  const [manualUniversity, setManualUniversity] = useState("");
  const [typingUniversity, setTypingUniversity] = useState(false);

  // Step 3 — alerts
  const [phoneCode, setPhoneCode] = useState("+91");
  const [phoneTouched, setPhoneTouched] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [waConsent, setWaConsent] = useState(false);

  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const destination = redirectFromQuery(router.query, "/dashboard");
  const leaving = useRef(false);

  // ── Auth gate + prefill ───────────────────────────────────────────────────
  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) { router.replace("/auth"); return; }

    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        const me = token ? await getMe(token) : null;
        if (cancelled || !me) return;

        // Already done? Don't make them fill it in twice — that is how a
        // returning user ends up re-answering questions we already have.
        if (me.is_onboarded) {
          leaving.current = true;
          router.replace(destination);
          return;
        }

        // Half-finished profile (a previous attempt that failed at the last
        // step) — pick up where they left off rather than from nothing.
        if (me.country) setFromCountry(COUNTRIES_FULL.find(c => c.code === me.country) || null);
        if (me.corridor_from) setFromCurrency(me.corridor_from);
        if (me.corridor_to) {
          setToCurrency(me.corridor_to);
          const home = COUNTRIES_FULL.find(c => c.currency === me.corridor_to);
          if (home) setToCountry(home);
        }
        if (me.university) setUniversity({ name: me.university });
        if (me.whatsapp_number) {
          const match = /^(\+\d{1,4})(\d+)$/.exec(me.whatsapp_number);
          if (match) {
            setPhoneCode(match[1]);
            setPhoneNumber(match[2]);
            setPhoneTouched(true);
            setWaConsent(true);
          }
        }
      } catch (err) {
        // A 404 just means "no row yet" — that is the normal first-run case.
        if (err?.status === 401) { leaving.current = true; router.replace("/auth"); return; }
      } finally {
        // Leave the loading screen up while a redirect is in flight, so the
        // form never flashes on its way off the page.
        if (!cancelled && !leaving.current) setBootstrapping(false);
      }
    })();

    return () => { cancelled = true; };
  }, [isLoaded, isSignedIn]);

  // Country choice drives the currency, but the user can still override it —
  // plenty of students hold an account in a currency other than their
  // country's (a EUR account in Switzerland, USD in the Gulf).
  useEffect(() => {
    if (fromCountry) setFromCurrency(currencyForCountry(fromCountry.code) || "");
  }, [fromCountry]);

  useEffect(() => {
    if (!toCountry) return;
    setToCurrency(currencyForCountry(toCountry.code) || "");
    if (!phoneTouched) setPhoneCode(dialCodeForCountry(toCountry.code) || "+91");
  }, [toCountry]);

  const universityItems = useMemo(
    () => universitiesForCountry(fromCountry?.code).map(u => ({ ...u, flag: "🏫" })),
    [fromCountry]
  );

  // No list for this country? Then the only sane control is a text box.
  const mustTypeUniversity = Boolean(fromCountry) && universityItems.length === 0;
  const universityName = (typingUniversity || mustTypeUniversity)
    ? manualUniversity.trim()
    : (university?.name || "");

  const sameCurrency = Boolean(fromCurrency) && fromCurrency === toCurrency;

  const payload = () => ({
    country:         fromCountry?.code || "",
    university:      universityName || null,
    whatsapp_number: waConsent && phoneNumber.trim() ? `${phoneCode}${phoneNumber.replace(/\D/g, "")}` : null,
    home_currency:   toCurrency || null,
    corridor_from:   fromCurrency || null,
    corridor_to:     toCurrency || null,
  });

  const submit = async () => {
    if (loading) return;
    setLoading(true);
    setSubmitError("");
    try {
      const token = await getToken();
      if (!token) { router.replace("/auth"); return; }
      await completeOnboarding(token, payload());
      setStep(STEP_DONE);
    } catch (err) {
      if (err?.status === 401) { router.replace("/auth"); return; }
      setSubmitError(err?.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // The success screen used to be unreachable — the wizard redirected straight
  // past it. Show it, then move on by itself so nobody has to click twice.
  useEffect(() => {
    if (step !== STEP_DONE) return;
    const t = setTimeout(() => {
      if (!leaving.current) { leaving.current = true; router.replace(destination); }
    }, 2200);
    return () => clearTimeout(t);
  }, [step, destination]);

  const goNext = () => { setErrors({}); setStep(s => Math.min(s + 1, TOTAL_STEPS)); };
  const goBack = () => { setErrors({}); setStep(s => Math.max(s - 1, 1)); };

  const handleContinue = async () => {
    const errs = {};

    if (step === 1) {
      if (!fromCountry) errs.fromCountry = "Tell us where you're sending from";
      if (!toCountry)   errs.toCountry = "Tell us where the money is going";
      if (!errs.fromCountry && !errs.toCountry && sameCurrency) {
        errs.toCountry = "Pick two places with different currencies — there's nothing to compare otherwise.";
      }
      setErrors(errs);
      if (Object.keys(errs).length === 0) goNext();
      return;
    }

    if (step === 2) {
      // University is useful, not essential. Blocking on it strands anyone
      // whose university isn't in our list.
      goNext();
      return;
    }

    if (step === 3) {
      if (phoneNumber.trim() && !waConsent) {
        setErrors({ consent: "Tick the box so we can message you — or clear the number to skip alerts." });
        return;
      }
      const digits = phoneNumber.replace(/\D/g, "");
      if (waConsent && (digits.length < 6 || digits.length > 14)) {
        setErrors({ phone: "That doesn't look like a complete phone number." });
        return;
      }
      setErrors({});
      await submit();
    }
  };

  const skipAlerts = async () => {
    setWaConsent(false);
    setPhoneNumber("");
    setErrors({});
    setLoading(true);
    setSubmitError("");
    try {
      const token = await getToken();
      if (!token) { router.replace("/auth"); return; }
      await completeOnboarding(token, {
        country:         fromCountry?.code || "",
        university:      universityName || null,
        whatsapp_number: null,
        home_currency:   toCurrency || null,
        corridor_from:   fromCurrency || null,
        corridor_to:     toCurrency || null,
      });
      setStep(STEP_DONE);
    } catch (err) {
      if (err?.status === 401) { router.replace("/auth"); return; }
      setSubmitError(err?.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // While the session loads or we're reading an existing profile, show the same
  // loading state as post-auth rather than a form that can't submit yet.
  if (!isLoaded || bootstrapping) {
    return (
      <>
        <Head><title>Set Up Your Account — Vaulto</title></Head>
        <div className="min-h-screen bg-[var(--bg)] flex flex-col items-center justify-center text-[var(--text)]">
          <div className="loading-box animate-pulse-glow">
            <div className="mb-6 flex justify-center logo">
              <span className="logo-mark">V</span><span>Vaulto</span>
            </div>
            <div className="spinner"></div>
            <p className="mt-4 text-[var(--muted)] text-sm tracking-wider uppercase font-semibold">
              Getting things ready
            </p>
          </div>
        </div>
      </>
    );
  }

  const corridorPreview = fromCurrency && toCurrency && !sameCurrency
    ? `${fromCurrency} → ${toCurrency}`
    : null;

  return (
    <>
      <Head>
        <title>Set Up Your Account — Vaulto</title>
        <meta name="description" content="Personalize your Vaulto experience in 3 easy steps." />
      </Head>

      <div className="min-h-screen bg-[var(--bg)] font-sans text-[var(--text)] relative overflow-hidden">
        <div className="relative z-10 flex flex-col items-center justify-center min-h-screen px-5 py-8">
          {/* Logo */}
          <Link href="/" className="logo mb-8">
            <span className="logo-mark">V</span><span>Vaulto</span>
          </Link>

          {/* Progress indicator */}
          {step <= TOTAL_STEPS && (
            <div className="mb-8 w-full max-w-md">
              <div className="flex items-center justify-center gap-1">
                {[1, 2, 3].map((s) => (
                  <div key={s} className="flex items-center gap-1">
                    <div
                      className={`transition-all duration-400 rounded-full ${
                        s === step
                          ? "w-7 h-2 bg-[var(--secondary)]"
                          : s < step
                          ? "w-2 h-2 bg-[var(--tertiary)]"
                          : "w-2 h-2 bg-[var(--surface-highest)]"
                      }`}
                    />
                    {s < 3 && <div className={`w-8 h-px ${s < step ? "bg-[var(--tertiary)]" : "bg-[var(--surface-highest)]"}`} />}
                  </div>
                ))}
              </div>
              <p className="text-center text-[var(--muted)] text-[11px] tracking-[0.12em] uppercase mt-3 font-semibold">
                Step {step} of {TOTAL_STEPS} — {stepLabels[step - 1]}
              </p>
            </div>
          )}

          {/* ═══════ STEP 1: Corridor ═══════ */}
          {step === 1 && (
            <div key="step1" className="w-full max-w-md card animate-slide-up">
              <h2 className="headline mb-1">
                Set up your <span className="text-[var(--secondary)]">transfer route</span>
              </h2>
              <p className="text-[var(--text-mid)] text-sm mb-6 leading-relaxed">
                Where your money starts and where it lands. We&rsquo;ll watch this corridor for you.
              </p>

              <div className="mb-4 field">
                <label className="mb-1">I&rsquo;m sending from</label>
                <SearchableDropdown
                  id="onboard-from-country"
                  items={countryItems}
                  value={fromCountry?.name || null}
                  onChange={(item) => {
                    setFromCountry(COUNTRIES_FULL.find(c => c.code === item.code) || null);
                    setUniversity(null);
                    setManualUniversity("");
                    setTypingUniversity(false);
                    setErrors({});
                  }}
                  placeholder="The country you live or study in…"
                />
                {errors.fromCountry && (
                  <p className="text-[var(--error)] text-xs mt-1.5">{errors.fromCountry}</p>
                )}
              </div>

              <div className="mb-1 field">
                <label className="mb-1">I&rsquo;m sending to</label>
                <SearchableDropdown
                  id="onboard-to-country"
                  items={countryItems}
                  value={toCountry?.name || null}
                  onChange={(item) => {
                    setToCountry(COUNTRIES_FULL.find(c => c.code === item.code) || null);
                    setErrors({});
                  }}
                  placeholder="Where the money should arrive…"
                />
                {errors.toCountry && (
                  <p className="text-[var(--error)] text-xs mt-1.5">{errors.toCountry}</p>
                )}
              </div>

              {/* Currency confirmation — derived, but overridable */}
              {(fromCountry || toCountry) && (
                <div className="mt-5 animate-fade-in">
                  <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", fontWeight: 600, marginBottom: "6px" }}>
                    Currencies
                  </p>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <select
                      id="onboard-from-currency"
                      aria-label="Send currency"
                      value={fromCurrency}
                      onChange={(e) => { setFromCurrency(e.target.value); setErrors({}); }}
                      style={{ flex: 1 }}
                    >
                      <option value="">Select…</option>
                      {CURRENCIES.map(c => (
                        <option key={c.code} value={c.code}>{c.flag} {c.code}</option>
                      ))}
                    </select>
                    <span className="text-[var(--muted)]">→</span>
                    <select
                      id="onboard-to-currency"
                      aria-label="Receive currency"
                      value={toCurrency}
                      onChange={(e) => { setToCurrency(e.target.value); setErrors({}); }}
                      style={{ flex: 1 }}
                    >
                      <option value="">Select…</option>
                      {CURRENCIES.map(c => (
                        <option key={c.code} value={c.code}>{c.flag} {c.code}</option>
                      ))}
                    </select>
                  </div>
                  {sameCurrency ? (
                    <p className="text-[var(--error)] text-xs mt-1.5">
                      Both sides are {fromCurrency} — there&rsquo;s no transfer to compare.
                    </p>
                  ) : corridorPreview ? (
                    <div className="mt-3 pill pill-secondary animate-fade-in">
                      {fromCountry?.flag} {corridorPreview} {toCountry?.flag}
                    </div>
                  ) : null}
                </div>
              )}

              <div className="mt-7 flex gap-3">
                <button
                  onClick={handleContinue}
                  id="onboard-step1-continue"
                  className="flex-1 btn-secondary justify-center"
                >
                  Continue →
                </button>
              </div>
            </div>
          )}

          {/* ═══════ STEP 2: University ═══════ */}
          {step === 2 && (
            <div key="step2" className="w-full max-w-md card animate-slide-up">
              <h2 className="headline mb-1">
                Where do you <span className="text-[var(--secondary)]">study</span>?
              </h2>
              <p className="text-[var(--text-mid)] text-sm mb-6 leading-relaxed">
                {fromCountry
                  ? `Optional — it helps us tune transfer routes and fee tips for students in ${fromCountry.name}.`
                  : "Optional — it helps us tune transfer routes for students."}
              </p>

              <div className="mb-1 field">
                <label className="mb-1">University</label>
                {(typingUniversity || mustTypeUniversity) ? (
                  <input
                    id="onboard-university-manual"
                    type="text"
                    value={manualUniversity}
                    onChange={(e) => setManualUniversity(e.target.value)}
                    placeholder="Type your university's name…"
                    maxLength={200}
                  />
                ) : (
                  <SearchableDropdown
                    id="onboard-university"
                    items={universityItems}
                    value={university?.name || null}
                    onChange={(item) => { setUniversity(item); setErrors({}); }}
                    placeholder="Search for your university…"
                  />
                )}
              </div>

              {!mustTypeUniversity && (
                <button
                  type="button"
                  onClick={() => {
                    setTypingUniversity(t => !t);
                    setUniversity(null);
                  }}
                  className="text-[var(--secondary)] text-xs mt-2 hover:underline"
                  id="onboard-university-toggle"
                >
                  {typingUniversity ? "← Pick from the list instead" : "Can't find it? Type it in"}
                </button>
              )}

              {universityName && !typingUniversity && !mustTypeUniversity && (
                <div className="mt-3 pill pill-secondary animate-fade-in">
                  🏫 {university.name}
                  {university.city && <span className="opacity-70">— {university.city}</span>}
                  <button
                    type="button"
                    onClick={() => setUniversity(null)}
                    className="opacity-70 hover:opacity-100 text-base leading-none ml-1"
                  >
                    ×
                  </button>
                </div>
              )}

              <div className="mt-7 flex gap-3">
                <button onClick={goBack} className="btn-ghost">← Back</button>
                <button
                  onClick={handleContinue}
                  id="onboard-step2-continue"
                  className="flex-1 btn-secondary justify-center"
                >
                  {universityName ? "Continue →" : "Skip for now →"}
                </button>
              </div>
            </div>
          )}

          {/* ═══════ STEP 3: WhatsApp ═══════ */}
          {step === 3 && (
            <div key="step3" className="w-full max-w-md card animate-slide-up">
              <h2 className="headline mb-1">
                Get <span className="text-[var(--tertiary)]">rate alerts</span> on WhatsApp
              </h2>
              <p className="text-[var(--text-mid)] text-sm mb-5 leading-relaxed">
                We&rsquo;ll notify you when {corridorPreview || "your"} rates improve. Never miss a good rate.
              </p>

              <div className="flex gap-3 bg-[var(--tertiary-dim)] rounded-xl p-4 mb-5">
                <span className="text-2xl leading-none shrink-0">💬</span>
                <div className="text-sm text-[var(--text-mid)] leading-relaxed">
                  <span className="text-[var(--tertiary)] font-semibold">Smart rate alerts —</span> We monitor rates 24/7 and message you when it&rsquo;s the best time to transfer. Saves users <span className="text-[var(--tertiary)] font-semibold">2-4%</span> per transfer.
                </div>
              </div>

              <div className="mb-1">
                <p style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--muted)", fontWeight: 600, marginBottom: "6px" }}>
                  WhatsApp Number
                  <span className="inline-flex ml-2 pill pill-muted !px-1.5 !py-0.5 !text-[9px] align-middle">
                    Optional
                  </span>
                </p>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                  <select
                    id="onboard-phone-code"
                    aria-label="Country dialling code"
                    value={phoneCode}
                    onChange={(e) => { setPhoneCode(e.target.value); setPhoneTouched(true); }}
                    style={{ width: "130px", flexShrink: 0 }}
                  >
                    {COUNTRIES_FULL.map((c) => (
                      <option key={c.code} value={c.dial}>
                        {c.flag} {c.dial}
                      </option>
                    ))}
                  </select>
                  <input
                    id="onboard-phone"
                    type="tel"
                    autoComplete="tel-national"
                    placeholder="Your phone number"
                    value={phoneNumber}
                    onChange={(e) => {
                      const next = e.target.value.replace(/[^\d\s()-]/g, "");
                      setPhoneNumber(next);
                      // Typing a number is the intent; the checkbox is the
                      // consent. Entering one and leaving the other used to
                      // drop the number silently on submit.
                      if (next.trim()) setErrors(err => ({ ...err, phone: undefined }));
                      else setWaConsent(false);
                    }}
                    style={{ flex: 1 }}
                  />
                </div>
                {errors.phone && <p className="text-[var(--error)] text-xs mt-1.5">{errors.phone}</p>}
              </div>

              <label className="flex items-start gap-2.5 mt-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={waConsent}
                  onChange={(e) => { setWaConsent(e.target.checked); setErrors({}); }}
                  className="mt-1"
                  id="onboard-wa-consent"
                  style={{ accentColor: 'var(--tertiary)' }}
                />
                <span className="text-[var(--text-mid)] text-xs leading-relaxed">
                  I agree to receive rate alerts via WhatsApp. We only message you about rates — no spam, ever.
                </span>
              </label>
              {errors.consent && <p className="text-[var(--error)] text-xs mt-1.5">{errors.consent}</p>}

              {submitError && (
                <div className="error-box animate-slide-up mt-4" role="alert">
                  {submitError}
                </div>
              )}

              <div className="mt-7 flex gap-3">
                <button onClick={goBack} className="btn-ghost" disabled={loading}>← Back</button>
                <button
                  onClick={handleContinue}
                  disabled={loading}
                  id="onboard-finish"
                  className="flex-1 btn-secondary justify-center flex items-center gap-2"
                >
                  {loading ? (
                    <div className="w-5 h-5 border-2 border-[var(--text-inverse)]/30 border-t-[var(--text-inverse)] rounded-full animate-spin" />
                  ) : (
                    "Finish Setup →"
                  )}
                </button>
              </div>
              <button
                onClick={skipAlerts}
                disabled={loading}
                className="w-full text-center text-[var(--muted)] text-sm mt-3 py-2 hover:text-[var(--text)] transition-colors disabled:opacity-50"
                type="button"
                id="onboard-skip-alerts"
              >
                Skip — I&rsquo;ll do this later
              </button>
            </div>
          )}

          {/* ═══════ COMPLETION ═══════ */}
          {step === STEP_DONE && (
            <div key="done" className="w-full max-w-md card text-center animate-slide-up">
              <div className="w-[72px] h-[72px] rounded-full bg-[var(--tertiary-dim)] flex items-center justify-center text-3xl mx-auto mb-5 animate-pulse-glow">
                🚀
              </div>
              <h2 className="headline mb-2">You&rsquo;re all set!</h2>
              <p className="text-[var(--text-mid)] text-sm leading-relaxed mb-6">
                Your Vaulto account is ready
                {corridorPreview && (
                  <> — tuned for <span className="text-[var(--text)] font-medium">{corridorPreview}</span></>
                )}.
              </p>

              <div className="grid grid-cols-2 gap-2.5 mb-6">
                {[
                  { icon: "📊", label: "Live rate comparison" },
                  { icon: "🔔", label: "Smart alerts" },
                  { icon: "💡", label: "Personalized picks" },
                  { icon: "🏦", label: "25+ providers" },
                ].map((f) => (
                  <div
                    key={f.label}
                    className="flex items-center gap-2 bg-[var(--surface-high)] rounded-lg px-3 py-2.5 text-[var(--text-mid)] text-xs"
                  >
                    <span className="text-base">{f.icon}</span>
                    {f.label}
                  </div>
                ))}
              </div>

              <button
                onClick={() => { leaving.current = true; router.replace(destination); }}
                id="onboard-go-dashboard"
                className="w-full btn-secondary justify-center"
              >
                Go to my dashboard →
              </button>
            </div>
          )}

          {/* Trust footer */}
          {step <= TOTAL_STEPS && (
            <div className="flex items-center justify-center gap-5 mt-8 text-[var(--muted)] text-[11px] font-semibold uppercase tracking-wider">
              <div className="flex items-center gap-1.5"><span>🔒</span> 256-bit encryption</div>
              <div className="flex items-center gap-1.5"><span>🛡️</span> No data selling</div>
              <div className="flex items-center gap-1.5"><span>⚡</span> Free forever</div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
