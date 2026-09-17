import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/router";
import { useAuth } from "@clerk/nextjs";
import Head from "next/head";
import Link from "next/link";
import Nav from "../components/Nav";
import Footer from "../components/Footer";
import ProviderCard from "../components/ProviderCard";
import AlertModal from "../components/AlertModal";
import { getRates } from "../lib/api";
import { CURRENCIES } from "../lib/currencies";

const SORT_OPTIONS = [
  { key: "rate", label: "Best rate" },
  { key: "fee", label: "Lowest fee" },
  { key: "speed", label: "Fastest" },
];

// Speed ordering uses the backend's numeric ETA (eta_max_minutes) when it is
// present. The old fallback below matched words in the prose label, which
// could only tell minutes from hours from days — it sorted "10-12 days" ahead
// of "2-3 days" and treated a 1-day transfer the same as a 5-day one.
function etaRank(quote) {
  if (quote.eta_max_minutes != null) return quote.eta_max_minutes;
  if (quote.eta_min_minutes != null) return quote.eta_min_minutes;

  const t = quote.transfer_time;
  if (!t) return Number.MAX_SAFE_INTEGER;
  if (t.match(/min/i)) return 15;
  if (t.match(/hour|hr/i)) return 60;
  if (t.match(/day/i)) return 1440;
  return Number.MAX_SAFE_INTEGER;
}

function sortResults(results, sortBy) {
  const r = [...results];
  if (sortBy === "rate") return r.sort((a, b) => b.receive_amount - a.receive_amount);
  if (sortBy === "fee") return r.sort((a, b) => a.fee - b.fee);
  if (sortBy === "speed") {
    // Break ties on money received, so two equally fast providers do not get
    // ordered arbitrarily.
    return r.sort(
      (a, b) => etaRank(a) - etaRank(b) || b.receive_amount - a.receive_amount
    );
  }
  return r;
}

const fmt = (n, dec = 2) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(n);

export default function Results() {
  const router = useRouter();
  const { isSignedIn } = useAuth();

  const { from = "GBP", to = "INR", amount = "1000" } = router.query;

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sortBy, setSortBy] = useState("rate");
  const [alertTarget, setAlertTarget] = useState(null);
  const [alertOpen, setAlertOpen] = useState(false);
  const [avoidOpen, setAvoidOpen] = useState(false);

  // Inline search form state
  const [formFrom, setFormFrom] = useState(from);
  const [formTo, setFormTo] = useState(to);
  const [formAmount, setFormAmount] = useState(amount);

  const refreshTimer = useRef(null);

  const fetchRates = useCallback(async () => {
    if (!from || !to || !amount) return;
    setLoading(true);
    setError("");
    try {
      const result = await getRates({ from, to, amount: parseFloat(amount) });
      setData(result);
    } catch (e) {
      setError(e.message || "Failed to fetch rates. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [from, to, amount]);

  useEffect(() => {
    if (!router.isReady) return;
    setFormFrom(from);
    setFormTo(to);
    setFormAmount(amount);
    fetchRates();
  }, [router.isReady, from, to, amount]);

  // Auto-refresh stale results every 30s
  useEffect(() => {
    refreshTimer.current = setInterval(() => {
      if (data?.stale) fetchRates();
    }, 30000);
    return () => clearInterval(refreshTimer.current);
  }, [data?.stale, fetchRates]);

  const handleSearch = (e) => {
    e.preventDefault();
    const p = parseFloat(formAmount);
    if (!p || p <= 0 || formFrom === formTo) return;
    router.push(`/results?from=${formFrom}&to=${formTo}&amount=${p}`);
  };

  const handleAlert = (provider) => {
    if (!isSignedIn) {
      router.push('/auth?mode=signup');
      return;
    }
    setAlertTarget(provider);
    setAlertOpen(true);
  };

  const sortedResults = data?.results ? sortResults(data.results.filter(r => !r.error), sortBy) : [];
  const best = data?.best_provider
    ? sortedResults.find(r => r.provider === data.best_provider) || sortedResults[0]
    : sortedResults[0];

  const fromFlag = CURRENCIES.find(c => c.code === from)?.flag || "";
  const toFlag = CURRENCIES.find(c => c.code === to)?.flag || "";

  return (
    <>
      <Head>
        <title>Compare {from} → {to} — Vaulto Live Rates</title>
        <meta name="description" content={`Compare live ${from} to ${to} exchange rates from Wise, Remitly, and Western Union. Find the best rate instantly.`} />
      </Head>

      <Nav variant="light" />

      {/* Header */}
      <section className="results-header">
        <div className="container">
          <p className="label-sm" style={{ color: "var(--secondary)", marginBottom: "0.5rem" }}>Live comparison</p>
          <div className="results-title-row">
            <h1 className="display-md">
              Send {fromFlag} {from} → {toFlag} {to}
            </h1>
            {data?.cached && (
              <span className="pill pill-muted" style={{ alignSelf: "center" }}>⚡ Cached</span>
            )}
            {data?.stale && (
              <span className="pill" style={{ alignSelf: "center", background: "var(--warn-surface)", color: "var(--warn)" }}>⏰ Stale</span>
            )}
          </div>

          {/* Inline search form */}
          <form onSubmit={handleSearch} className="results-form card" style={{ marginTop: "1.5rem" }}>
            <div className="results-form-fields">
              <div className="field">
                <label htmlFor="rf-amount">Amount</label>
                <input id="rf-amount" type="number" min="1" value={formAmount} onChange={e => setFormAmount(e.target.value)} placeholder="1000" />
              </div>
              <div className="field">
                <label htmlFor="rf-from">You send</label>
                <select id="rf-from" value={formFrom} onChange={e => setFormFrom(e.target.value)}>
                  {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="rf-to">Recipient gets</label>
                <select id="rf-to" value={formTo} onChange={e => setFormTo(e.target.value)}>
                  {CURRENCIES.map(c => <option key={c.code} value={c.code}>{c.flag} {c.code}</option>)}
                </select>
              </div>
              <div className="field">
                <label>&nbsp;</label>
                <button type="submit" className="btn-secondary">Compare →</button>
              </div>
            </div>
          </form>
        </div>
      </section>

      <div className="container results-layout">
        {/* Left: Results */}
        <main className="results-main">
          {error && (
            <div className="error-box" style={{ marginBottom: "1rem" }}>
              ⚠️ {error}
              <button onClick={fetchRates} style={{ marginLeft: "1rem", textDecoration: "underline", background: "none", border: "none", color: "inherit", cursor: "pointer" }}>Retry</button>
            </div>
          )}

          {loading ? (
            <>
              <div className="loading-box"><div className="spinner" /><p>Fetching live rates…</p></div>
              {[1,2,3].map(i => (
                <div key={i} className="card" style={{ marginBottom: "1rem", padding: "1.5rem" }}>
                  <div className="skeleton-line" style={{ width: "40%", marginBottom: "0.75rem" }} />
                  <div className="skeleton-line" style={{ width: "60%", marginBottom: "0.5rem" }} />
                  <div className="skeleton-line" style={{ width: "30%" }} />
                </div>
              ))}
            </>
          ) : (
            <>
              {/* Best Provider Banner */}
              {best && !error && (
                <div className="best-card anim-fade-up" style={{ marginBottom: "1.5rem" }}>
                  <div>
                    <div className="best-badge">⭐ Best Rate Today</div>
                    <div className="best-provider-name">{best.provider}</div>
                    <div className="best-meta">
                      <span>Rate: {fmt(best.exchange_rate, 4)}</span>
                      <span>Fee: {best.currency_from} {fmt(best.fee)}</span>
                      <span>{best.transfer_time}</span>
                    </div>
                    {data?.savings_vs_worst > 0 && (
                      <div className="savings-pill">
                        💰 Save up to {best.currency_to} {fmt(data.savings_vs_worst)} vs worst option
                      </div>
                    )}
                  </div>
                  <div className="best-receive">
                    <div className="best-receive-label">Recipient gets</div>
                    <div className="best-receive-amount">{fmt(best.receive_amount)}</div>
                    <div className="best-receive-currency">{best.currency_to}</div>
                  </div>
                </div>
              )}

              {/* Sort Controls */}
              {sortedResults.length > 0 && (
                <div className="sort-bar anim-fade-up anim-delay-1">
                  {SORT_OPTIONS.map(opt => (
                    <button
                      key={opt.key}
                      className={`sort-pill ${sortBy === opt.key ? "sort-active" : ""}`}
                      onClick={() => setSortBy(opt.key)}
                      id={`sort-${opt.key}`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}

              {/* Provider Cards */}
              <div className="provider-list">
                {sortedResults.map((p, i) => (
                  <ProviderCard
                    key={p.provider}
                    provider={p}
                    rank={i + 1}
                    isBest={p.provider === data?.best_provider}
                    sortBy={sortBy}
                    onAlert={handleAlert}
                    ratesData={data}
                  />
                ))}
              </div>

              <button 
                className="avoid-toggle-btn"
                onClick={() => setAvoidOpen(!avoidOpen)}
              >
                {avoidOpen ? "🏦 Why banks cost more ▲" : "🏦 See why banks are expensive ▼"}
              </button>

              {avoidOpen && (
                <div className="avoid-banks-section anim-fade-up">
                  <div className="avoid-grid">
                    {['CommBank', 'ANZ', 'Westpac', 'NAB'].map((bank) => (
                      <div key={bank} className="avoid-card">
                        <div className="avoid-card-header">
                          <span className="avoid-bank-name">{bank}</span>
                          <span className="pill" style={{ color: "var(--error)", background: "var(--error-surface)" }}>
                            ⚠ AVOID
                          </span>
                        </div>
                        <div className="avoid-card-body">
                          <p className="avoid-placeholder-text">Rate: ~52–54 INR per AUD (estimated)</p>
                          <p className="avoid-placeholder-text">Fee: AUD 20–30 typical</p>
                          <div className="avoid-badge">3–5× higher fees than Wise</div>
                          <p className="avoid-body-copy">
                            Your bank charges an estimated <strong>AUD 15–25</strong> more than Wise for the same AUD 1,000 transfer.
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="avoid-disclaimer">
                    Rates are indicative estimates. Banks do not publish live FX rates via API.
                  </p>
                </div>
              )}

              {/* No results */}
              {sortedResults.length === 0 && !error && (
                <div className="empty-state card">
                  <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>📡</div>
                  <h3>No rates available</h3>
                  <p style={{ color: "var(--muted)", marginTop: "0.5rem" }}>We couldn't fetch live rates for this corridor right now.</p>
                  <button className="btn-secondary" onClick={fetchRates} style={{ marginTop: "1rem" }}>Try again</button>
                </div>
              )}

              {/* Failed providers */}
              {data?.failed_providers?.length > 0 && (
                <div className="warn-box">
                  ⚠️ Could not fetch rates from: {data.failed_providers.join(", ")}
                </div>
              )}

              {/* Disclaimer */}
              <p className="results-disclaimer">
                Rates are indicative and fetched live from provider APIs. Actual rates may differ at time of transfer. Not financial advice.
              </p>
            </>
          )}
        </main>

        {/* Right sidebar */}
        <aside className="results-sidebar">
          {/* Expert tips */}
          <div className="card" style={{ marginBottom: "1.5rem" }}>
            <p className="label-sm" style={{ marginBottom: "1rem" }}>💡 Expert tips</p>
            <ul className="tips-list">
              <li>Send on weekdays — rates are often 0.2–0.5% better than weekends.</li>
              <li>Avoid bank transfers — they markup rates by 2–5%.</li>
              <li>Set a rate alert to transfer at your target rate automatically.</li>
              <li>Compare fees carefully — a lower rate can still win with lower fees.</li>
            </ul>
          </div>

          {/* Sign-up CTA if not signed in */}
          {!isSignedIn && (
            <div className="sidebar-cta">
              <p className="label-sm" style={{ color: "rgba(255,255,255,0.6)", marginBottom: "0.75rem" }}>🔔 Rate alerts</p>
              <h3 style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: "1.2rem", color: "white", marginBottom: "0.5rem" }}>
                Never miss a great rate
              </h3>
              <p style={{ color: "rgba(255,255,255,0.6)", fontSize: "0.85rem", marginBottom: "1rem" }}>
                Create a free account to save comparisons and set WhatsApp alerts.
              </p>
              <Link href="/auth?mode=signup" className="btn-secondary" style={{ width: "100%", justifyContent: "center" }}>
                Create free account →
              </Link>
            </div>
          )}
        </aside>
      </div>

      {/* Alert Modal */}
      <AlertModal
        isOpen={alertOpen}
        onClose={() => setAlertOpen(false)}
        onSuccess={() => setAlertOpen(false)}
        defaultFrom={alertTarget?.currency_from || from}
        defaultTo={alertTarget?.currency_to || to}
        defaultAmount={alertTarget?.send_amount || parseFloat(amount)}
      />

      <Footer />

      <style jsx>{`
        .results-header {
          background: var(--surface-low);
          padding: 2.5rem 0 0;
          border-bottom: 1px solid var(--surface-high);
        }
        .results-title-row { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
        .results-form-fields {
          display: grid;
          grid-template-columns: 1.4fr 1fr 1fr auto;
          gap: 0.75rem;
          align-items: end;
        }
        @media (max-width: 700px) {
          .results-form-fields { grid-template-columns: 1fr; }
        }
        .results-form { margin-bottom: 0; border-radius: var(--radius-lg) var(--radius-lg) 0 0; }

        .results-layout {
          display: grid;
          grid-template-columns: 1fr 320px;
          gap: 2rem;
          padding-top: 2rem;
          padding-bottom: 4rem;
          align-items: start;
        }
        @media (max-width: 900px) {
          .results-layout { grid-template-columns: 1fr; }
          .results-sidebar { order: -1; }
        }

        .sort-bar { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .sort-pill {
          padding: 0.45rem 1rem;
          border-radius: var(--radius-full);
          font-size: 0.85rem;
          font-weight: 600;
          font-family: var(--font-body);
          border: 1px solid var(--outline);
          background: var(--surface-float);
          color: var(--text-mid);
          cursor: pointer;
          transition: background 0.15s, color 0.15s, border-color 0.15s;
        }
        .sort-pill:hover { border-color: var(--secondary); color: var(--secondary); }
        .sort-active { background: var(--secondary) !important; color: white !important; border-color: var(--secondary) !important; }

        .provider-list { display: flex; flex-direction: column; gap: 1rem; }

        .tips-list { list-style: none; display: flex; flex-direction: column; gap: 0.75rem; }
        .tips-list li { font-size: 0.85rem; color: var(--text-mid); padding-left: 1rem; position: relative; line-height: 1.5; }
        .tips-list li::before { content: "→"; position: absolute; left: 0; color: var(--secondary); font-weight: 700; }

        .sidebar-cta {
          background: linear-gradient(135deg, var(--primary), #1e3460);
          border-radius: var(--radius-lg);
          padding: 1.5rem;
          position: relative;
          overflow: hidden;
        }
        .sidebar-cta::before {
          content: "";
          position: absolute;
          top: -30px; right: -30px;
          width: 120px; height: 120px;
          background: radial-gradient(circle, var(--secondary), transparent);
          opacity: 0.15;
          border-radius: 50%;
        }

        .empty-state { text-align: center; padding: 3rem 1.5rem; }
        .empty-state h3 { font-family: var(--font-display); font-weight: 700; font-size: 1.1rem; }

        .results-disclaimer {
          margin-top: 2rem;
          font-size: 0.75rem;
          color: var(--muted);
          line-height: 1.6;
        }

        .avoid-toggle-btn {
          background: var(--surface-float);
          border: 1px solid var(--outline);
          border-radius: var(--radius-md);
          padding: 0.65rem 1.25rem;
          font-family: var(--font-body);
          font-weight: 600;
          font-size: 0.875rem;
          color: var(--error);
          cursor: pointer;
          width: 100%;
          text-align: left;
          margin-top: 1.5rem;
        }
        .avoid-banks-section { margin-top: 1rem; }
        .avoid-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
          margin-bottom: 1rem;
        }
        @media (max-width: 600px) {
          .avoid-grid { grid-template-columns: 1fr; }
        }
        .avoid-card {
          border-left: 3px solid var(--error);
          background: var(--error-surface);
          border-radius: var(--radius-md);
          padding: 1rem;
        }
        .avoid-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.75rem;
        }
        .avoid-bank-name {
          font-family: var(--font-display);
          font-weight: 700;
        }
        .avoid-placeholder-text {
          font-size: 0.85rem;
          color: var(--muted);
          margin-bottom: 0.25rem;
        }
        .avoid-badge {
          font-size: 0.7rem;
          font-weight: 700;
          color: var(--error);
          margin: 0.5rem 0;
        }
        .avoid-body-copy {
          font-size: 0.85rem;
          line-height: 1.4;
        }
        .avoid-disclaimer {
          font-size: 0.8rem;
          color: var(--muted);
          text-align: center;
        }
      `}</style>
    </>
  );
}
