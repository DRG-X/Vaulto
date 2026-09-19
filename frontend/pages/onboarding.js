import { useState, useEffect, useMemo } from "react";
import Head from "next/head";
import { useRouter } from "next/router";
import Link from "next/link";
import { COUNTRIES, UNIVERSITIES } from "../lib/universities";
import { PHONE_CODES } from "../lib/countryPhoneCodes";
import { COUNTRY_CURRENCY_MAP } from "../lib/currencies";
import { useAuth } from "../contexts/AuthContext";
import { useUserProfile } from "../hooks/useUserProfile";
import { completeOnboarding } from "../lib/api";
import SearchableDropdown from "../components/SearchableDropdown";

const TOTAL_STEPS = 3;

// ═══════════════════════════════════════════════════════════════════════════════
// Onboarding Page
// ═══════════════════════════════════════════════════════════════════════════════
export default function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState(1);

  // Step 1
  const [selectedCountry, setSelectedCountry] = useState(null);
  // Step 2 — university + corridor
  const [selectedUniversity, setSelectedUniversity] = useState(null);
  const [homeCurrency, setHomeCurrency]     = useState("GBP");
  const [corridorTo, setCorridorTo]         = useState("INR");
  // Step 3
  const [phoneCode, setPhoneCode] = useState("+91");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [waConsent, setWaConsent] = useState(false);

  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { createProfile } = useUserProfile();
  const [submitError, setSubmitError] = useState("");

  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      router.push("/auth");
    }
  }, [isLoaded, isSignedIn, router]);

  const goNext = () => setStep((s) => Math.min(s + 1, TOTAL_STEPS + 1));
  const goBack = () => setStep((s) => Math.max(s - 1, 1));

  const countryItems = useMemo(
    () => COUNTRIES.map((c) => ({ name: c.name, flag: c.flag, code: c.code })),
    []
  );

  const universityItems = useMemo(() => {
    if (!selectedCountry) return [];
    return (UNIVERSITIES[selectedCountry.code] || []).map((u) => ({
      ...u,
      flag: "🏫",
    }));
  }, [selectedCountry]);

  // Auto-set home currency when country changes
  useEffect(() => {
    if (selectedCountry) {
      const cur = COUNTRY_CURRENCY_MAP[selectedCountry.code];
      if (cur) setHomeCurrency(cur);
    }
  }, [selectedCountry]);

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleContinue = async () => {
    const errs = {};

    if (step === 1) {
      if (!selectedCountry) errs.country = "Please select a country";
      setErrors(errs);
      if (Object.keys(errs).length === 0) goNext();
    } else if (step === 2) {
      if (!selectedUniversity) errs.university = "Please select a university";
      setErrors(errs);
      if (Object.keys(errs).length === 0) goNext();
    } else if (step === 3) {
      setLoading(true);
      setSubmitError("");
      const whatsappFull = waConsent && phoneNumber ? `${phoneCode}${phoneNumber}` : null;
      try {
        const token = await getToken();
        await completeOnboarding(token, {
          country:          selectedCountry?.code || "",
          university:       selectedUniversity?.name || null,
          whatsapp_number:  whatsappFull,
          home_currency:    homeCurrency || null,
          corridor_from:    homeCurrency || null,
          corridor_to:      corridorTo   || null,
        });
        router.push("/dashboard");
      } catch (err) {
        setSubmitError(err.message || "Something went wrong. Please try again.");
      } finally {
        setLoading(false);
      }
    }
  };

  const stepLabels = [
    "Destination",
    "University",
    "Alerts",
  ];

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
              {/* Step dots with connecting lines */}
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

          {/* ═══════ STEP 1: Country ═══════ */}
          {step === 1 && (
            <div
              key="step1"
              className="w-full max-w-md card animate-slide-up"
            >
              <h2 className="headline mb-1">
                Where are you <span className="text-[var(--secondary)]">sending money</span>?
              </h2>
              <p className="text-[var(--text-mid)] text-sm mb-6 leading-relaxed">
                Select the country you&rsquo;re transferring funds to. We&rsquo;ll customize your experience.
              </p>

              <div className="mb-1 field">
                <label className="mb-1">
                  Destination Country
                </label>
                <SearchableDropdown
                  id="onboard-country"
                  items={countryItems}
                  value={selectedCountry?.name || null}
                  onChange={(item) => {
                    const c = COUNTRIES.find((cc) => cc.code === item.code);
                    setSelectedCountry(c);
                    setSelectedUniversity(null);
                    setErrors({});
                  }}
                  placeholder="Search or select a country…"
                />
                {errors.country && (
                  <p className="text-[var(--error)] text-xs mt-1.5">{errors.country}</p>
                )}
              </div>

              {selectedCountry && (
                <div className="mt-3 pill pill-secondary animate-fade-in">
                  {selectedCountry.flag} {selectedCountry.name}
                  <button
                    type="button"
                    onClick={() => { setSelectedCountry(null); setSelectedUniversity(null); }}
                    className="opacity-70 hover:opacity-100 text-base leading-none ml-1"
                  >
                    ×
                  </button>
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
            <div
              key="step2"
              className="w-full max-w-md card animate-slide-up"
            >
              <h2 className="headline mb-1">
                Select your <span className="text-[var(--secondary)]">university</span>
              </h2>
              <p className="text-[var(--text-mid)] text-sm mb-6 leading-relaxed">
                {selectedCountry
                  ? `Showing universities in ${selectedCountry.name}. This helps us personalize transfer routes for you.`
                  : "Select your university to personalize your experience."}
              </p>

              <div className="mb-1 field">
                <label className="mb-1">
                  University
                </label>
                <SearchableDropdown
                  id="onboard-university"
                  items={universityItems}
                  value={selectedUniversity?.name || null}
                  onChange={(item) => {
                    setSelectedUniversity(item);
                    setErrors({});
                  }}
                  placeholder="Search for your university…"
                />
                {errors.university && (
                  <p className="text-[var(--error)] text-xs mt-1.5">{errors.university}</p>
                )}
              </div>

              {selectedUniversity && (
                <div className="mt-3 pill pill-secondary animate-fade-in">
                  🏫 {selectedUniversity.name}
                  {selectedUniversity.city && <span className="opacity-70">— {selectedUniversity.city}</span>}
                  <button
                    type="button"
                    onClick={() => setSelectedUniversity(null)}
                    className="opacity-70 hover:opacity-100 text-base leading-none ml-1"
                  >
                    ×
                  </button>
                </div>
              )}

              <div className="mt-7 flex gap-3">
                <button
                  onClick={goBack}
                  className="btn-ghost"
                >
                  ← Back
                </button>
                <button
                  onClick={handleContinue}
                  id="onboard-step2-continue"
                  className="flex-1 btn-secondary justify-center"
                >
                  Continue →
                </button>
              </div>
            </div>
          )}

          {/* ═══════ STEP 3: WhatsApp ═══════ */}
          {step === 3 && (
            <div
              key="step3"
              className="w-full max-w-md card animate-slide-up"
            >
              <h2 className="headline mb-1">
                Get <span className="text-[var(--tertiary)]">rate alerts</span> on WhatsApp
              </h2>
              <p className="text-[var(--text-mid)] text-sm mb-5 leading-relaxed">
                We&rsquo;ll notify you when exchange rates improve for your corridor. Never miss a good rate.
              </p>

              {/* Value prop banner */}
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
                    value={phoneCode}
                    onChange={(e) => setPhoneCode(e.target.value)}
                    style={{ width: "110px", flexShrink: 0 }}
                  >
                    {PHONE_CODES.map((pc) => (
                      <option key={`${pc.flag}-${pc.code}-${pc.country}`} value={pc.code}>
                        {pc.flag} {pc.code}
                      </option>
                    ))}
                  </select>
                  <input
                    id="onboard-phone"
                    type="tel"
                    placeholder="Your phone number"
                    value={phoneNumber}
                    onChange={(e) => setPhoneNumber(e.target.value.replace(/[^\d\s()-]/g, ""))}
                    style={{ flex: 1 }}
                  />
                </div>
              </div>

              {/* WhatsApp consent checkbox */}
              <label className="flex items-start gap-2.5 mt-4 cursor-pointer">
                <input
                  type="checkbox"
                  checked={waConsent}
                  onChange={(e) => setWaConsent(e.target.checked)}
                  className="mt-1"
                  id="onboard-wa-consent"
                  style={{ accentColor: 'var(--tertiary)' }}
                />
                <span className="text-[var(--text-mid)] text-xs leading-relaxed">
                  I agree to receive rate alerts via WhatsApp. We only message you about rates — no spam, ever.
                </span>
              </label>

              {submitError && (
                <div className="error-box animate-slide-up mt-4">
                  {submitError}
                </div>
              )}

              <div className="mt-7 flex gap-3">
                <button
                  onClick={goBack}
                  className="btn-ghost"
                >
                  ← Back
                </button>
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
                onClick={async () => {
                  if (loading) return;
                  setLoading(true);
                  setSubmitError("");
                  try {
                    const token = await getToken();
                    await completeOnboarding(token, {
                      country:          selectedCountry?.code || "",
                      university:       selectedUniversity?.name || null,
                      whatsapp_number:  null,
                      home_currency:    homeCurrency || null,
                      corridor_from:    homeCurrency || null,
                      corridor_to:      corridorTo   || null,
                    });
                    router.push("/dashboard");
                  } catch (err) {
                    setSubmitError(err.message || "Something went wrong. Please try again.");
                  } finally {
                    setLoading(false);
                  }
                }}
                disabled={loading}
                className="w-full text-center text-[var(--muted)] text-sm mt-3 py-2 hover:text-[var(--text)] transition-colors disabled:opacity-50"
                type="button"
              >
                Skip — I&rsquo;ll do this later
              </button>
            </div>
          )}

          {/* ═══════ COMPLETION ═══════ */}
          {step > TOTAL_STEPS && (
            <div
              key="done"
              className="w-full max-w-md card text-center animate-slide-up"
            >
              <div className="w-[72px] h-[72px] rounded-full bg-[var(--tertiary-dim)] flex items-center justify-center text-3xl mx-auto mb-5 animate-pulse-glow">
                🚀
              </div>
              <h2 className="headline mb-2">
                You&rsquo;re all set!
              </h2>
              <p className="text-[var(--text-mid)] text-sm leading-relaxed mb-6">
                Your Vaulto account is ready
                {selectedCountry && (
                  <> — optimized for transfers to <span className="text-[var(--text)] font-medium">{selectedCountry.name}</span></>
                )}.
              </p>

              {/* Features grid */}
              <div className="grid grid-cols-2 gap-2.5 mb-6">
                {[
                  { icon: "📊", label: "Live rate comparison" },
                  { icon: "🔔", label: "Smart alerts" },
                  { icon: "💡", label: "Personalized picks" },
                  { icon: "🏦", label: "3+ providers" },
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
                onClick={() => router.push("/")}
                id="onboard-go-dashboard"
                className="w-full btn-secondary justify-center"
              >
                Start Comparing Rates →
              </button>
            </div>
          )}

          {/* Trust footer */}
          {step <= TOTAL_STEPS && (
            <div className="flex items-center justify-center gap-5 mt-8 text-[var(--muted)] text-[11px] font-semibold uppercase tracking-wider">
              <div className="flex items-center gap-1.5">
                <span>🔒</span> 256-bit encryption
              </div>
              <div className="flex items-center gap-1.5">
                <span>🛡️</span> No data selling
              </div>
              <div className="flex items-center gap-1.5">
                <span>⚡</span> Free forever
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
