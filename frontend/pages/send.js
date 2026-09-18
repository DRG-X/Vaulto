import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import { getRates } from "../lib/api";
import { money, rate, eta } from "../lib/format";
import { CURRENCIES } from "../lib/currencies";

const fmt = (n, dec = 2) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n);

const PROVIDER_URLS = {
  Wise: "https://wise.com",
  Remitly: "https://remitly.com",
  "Western Union": "https://westernunion.com",
};

export default function Send() {
  const router = useRouter();
  const { from = "AUD", to = "INR", amount = "5000" } = router.query;

  const [step, setStep] = useState(1);
  const [formFrom, setFormFrom] = useState(from);
  const [formTo, setFormTo] = useState(to);
  const [formAmount, setFormAmount] = useState(amount);
  const [rateData, setRateData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [chosen, setChosen] = useState(null);

  useEffect(() => {
    if (!router.isReady) return;
    setFormFrom(from);
    setFormTo(to);
    setFormAmount(amount);
  }, [router.isReady]);

  const handleConfirm = async (e) => {
    e.preventDefault();
    const p = parseFloat(formAmount);
    if (!p || p <= 0 || formFrom === formTo) { setError("Check your amount and currencies."); return; }
    setError("");
    setLoading(true);
    try {
      const data = await getRates({ from: formFrom, to: formTo, amount: p });
      setRateData(data);
      setStep(2);
    } catch (e) {
      setError(e.message || "Failed to fetch rates.");
    } finally {
      setLoading(false);
    }
  };

  // Already ranked by the backend (cheapest first) with failed providers
  // excluded — re-sorting here would disagree with the rails it chose.
  const sortedResults = rateData?.results || [];

  const fromCcy = CURRENCIES.find(c => c.code === formFrom);
  const toCcy = CURRENCIES.find(c => c.code === formTo);

  return (
    <>
      <Head>
        <title>Send {from} to {to} — Vaulto</title>
        <meta name="description" content={`Best way to send ${from} to ${to}. Compare live rates from Wise, Remitly, and Western Union.`} />
      </Head>
      <Nav variant="light" />

      <div className="send-page">
        <div className="container send-container">
          {/* Progress */}
          <div className="send-progress">
            {["Confirm details", "Choose provider", "Start transfer"].map((s, i) => (
              <div key={s} className={`send-step ${step > i + 1 ? "step-done" : step === i + 1 ? "step-active" : ""}`}>
                <div className="send-step-num">{step > i + 1 ? "✓" : i + 1}</div>
                <span>{s}</span>
              </div>
            ))}
          </div>

          {/* Step 1 */}
          {step === 1 && (
            <div className="send-card card">
              <p className="label-sm" style={{ marginBottom: "0.5rem" }}>Best way to send money</p>
              <h1 className="display-md" style={{ marginBottom: "0.5rem" }}>
                {fromCcy?.flag} {formFrom} → {toCcy?.flag} {formTo}
              </h1>
              <p style={{ color: "var(--muted)", marginBottom: "2rem" }}>Confirm your details below to see live rates.</p>

              <form onSubmit={handleConfirm}>
                <div className="send-form-grid">
                  <div className="field">
                    <label htmlFor="s-amount">Amount to send</label>
                    <input id="s-amount" type="number" min="1" value={formAmount} onChange={e => setFormAmount(e.target.value)} />
                  </div>
                  <div className="field">
                    <label htmlFor="s-from">From currency</label>
                    <select id="s-from" value={formFrom} onChange={e => setFormFrom(e.target.value)}>
                      {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code} — {c.name}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="s-to">To currency</label>
                    <select id="s-to" value={formTo} onChange={e => setFormTo(e.target.value)}>
                      {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code} — {c.name}</option>)}
                    </select>
                  </div>
                </div>
                {error && <div className="error-box" style={{ marginTop: "0.75rem" }}>{error}</div>}
                <button type="submit" className="btn-secondary" style={{ marginTop: "1.5rem", width: "100%", justifyContent: "center", padding: "0.9rem" }} disabled={loading} id="send-compare-btn">
                  {loading ? <><span className="spinner" style={{ width: 16, height: 16, margin: 0, marginRight: "0.5rem" }} />Fetching rates…</> : "Compare →"}
                </button>
              </form>
            </div>
          )}

          {/* Step 2 */}
          {step === 2 && rateData && (
            <div>
              <h2 style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "1.5rem", marginBottom: "0.5rem" }}>
                Live {formFrom} to {formTo} Comparison
              </h2>
              <p style={{ color: "var(--muted)", marginBottom: "1.5rem" }}>Sending {fmt(parseFloat(formAmount))} {formFrom}. Choose your provider below.</p>
              <div className="send-results">
                {sortedResults.map((r, i) => (
                  <div key={r.provider} className={`send-provider card ${chosen?.provider === r.provider ? "send-chosen" : ""}`} onClick={() => { setChosen(r); setStep(3); }}>
                    <div className="sp-left">
                      <div className="sp-rank">{i + 1}</div>
                      <div>
                        <div className="sp-name">{r.provider}</div>
                        <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginTop: "0.2rem" }}>
                          {i === 0 && <span className="pill pill-secondary" style={{ fontSize: "0.65rem" }}>⭐ Best value</span>}
                          {r.avoid && (
                            <span className="pill" style={{ fontSize: "0.65rem", color: "var(--error)", background: "var(--error-surface)" }}>
                              ⚠ Expensive
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="sp-right">
                      <div className="sp-receive">{money(r.receive_amount, r.currency_to)} <span style={{ fontSize: "0.6em", opacity: 0.7 }}>{r.currency_to}</span></div>
                      <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                        {/* True cost, not just the fee — a zero-fee provider
                            can still be the expensive one. */}
                        {r.total_cost != null
                          ? `True cost: ${money(r.total_cost, r.currency_from)} ${r.currency_from}`
                          : `Fee: ${money(r.fee, r.currency_from)} ${r.currency_from}`}
                        {" · "}{eta(r)}
                      </div>
                    </div>
                    <div style={{ fontSize: "0.8rem", color: "var(--secondary)", fontWeight: 600 }}>Select →</div>
                  </div>
                ))}
              </div>
              <button className="btn-ghost" onClick={() => setStep(1)} style={{ marginTop: "1rem" }}>← Change details</button>
            </div>
          )}

          {/* Step 3 */}
          {step === 3 && chosen && (
            <div className="send-card card" style={{ textAlign: "center" }}>
              <div style={{ fontSize: "2.5rem", marginBottom: "1rem" }}>🎉</div>
              <h2 style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "1.5rem", marginBottom: "0.5rem" }}>
                Ready to send with {chosen.provider}
              </h2>
              <p style={{ color: "var(--muted)", marginBottom: "1.5rem" }}>
                Recipient gets <strong style={{ color: "var(--tertiary)" }}>{money(chosen.receive_amount, chosen.currency_to)} {chosen.currency_to}</strong> at a rate of {rate(chosen.exchange_rate)}
                {chosen.total_cost != null && <> — costing {money(chosen.total_cost, chosen.currency_from)} {chosen.currency_from} all in</>}.
              </p>
              <a href={PROVIDER_URLS[chosen.provider] || "#"} target="_blank" rel="noopener noreferrer" className="btn-secondary" style={{ display: "inline-flex", margin: "0 auto" }} id="send-provider-cta">
                Continue on {chosen.provider} ↗
              </a>
              <div style={{ marginTop: "1rem" }}>
                <button className="btn-ghost" onClick={() => setStep(2)}>← Choose different provider</button>
              </div>
            </div>
          )}
        </div>
      </div>

      <Footer />

      <style jsx>{`
        .send-page { padding: 4rem 0 6rem; min-height: 70vh; }
        .send-container { max-width: 680px; }
        .send-progress { display: flex; gap: 0; margin-bottom: 2.5rem; }
        .send-step { display: flex; align-items: center; gap: 0.5rem; flex: 1; font-size: 0.8rem; color: var(--muted); }
        .send-step:not(:last-child)::after { content: "→"; margin-left: auto; margin-right: 0.5rem; }
        .send-step-num { width: 24px; height: 24px; border-radius: 50%; background: var(--surface-high); color: var(--muted); display: flex; align-items: center; justify-content: center; font-size: 0.7rem; font-weight: 700; flex-shrink: 0; }
        .step-active .send-step-num { background: var(--secondary); color: white; }
        .step-active { color: var(--secondary); font-weight: 600; }
        .step-done .send-step-num { background: var(--tertiary); color: white; }
        .step-done { color: var(--tertiary); }
        .send-card { padding: 2rem; }
        .send-form-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }
        @media (max-width: 600px) { .send-form-grid { grid-template-columns: 1fr; } }
        .send-results { display: flex; flex-direction: column; gap: 0.75rem; }
        .send-provider { display: flex; align-items: center; gap: 1.25rem; cursor: pointer; transition: box-shadow 0.15s, transform 0.1s; }
        .send-provider:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
        .send-chosen { box-shadow: 0 0 0 2px var(--secondary), var(--shadow-md); }
        .sp-left { display: flex; align-items: center; gap: 0.75rem; flex: 1; }
        .sp-rank { width: 28px; height: 28px; background: var(--primary); color: white; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.7rem; font-weight: 800; flex-shrink: 0; }
        .sp-name { font-family: var(--font-display); font-weight: 700; font-size: 1rem; }
        .sp-right { text-align: right; margin-left: auto; }
        .sp-receive { font-family: var(--font-display); font-weight: 800; font-size: 1.4rem; letter-spacing: -0.02em; color: var(--tertiary); }
      `}</style>
    </>
  );
}
